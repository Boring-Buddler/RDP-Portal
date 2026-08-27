"""Microsoft Graph API client for Kirschke RDP Workstation Portal.

This module provides a wrapper around Microsoft Graph API with:
- Automatic token acquisition and refresh
- Request retry logic with exponential backoff
- Error handling and logging
- Support for batch requests
- Pagination handling
"""

import os
import json
import time
import logging
from typing import Optional, Any, TypeVar, Generic
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urljoin, urlencode
from http import HTTPStatus

import requests
from requests.exceptions import RequestException, Timeout, JSONDecodeError

from portal_app.auth.entra_auth import EntraAuthProvider, EntraAuthConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Exceptions
# =============================================================================

class GraphAPIError(Exception):
    """Base exception for Graph API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response = response
    
    def __str__(self) -> str:
        return f"GraphAPIError({self.status_code}): {self.message}"


class GraphRateLimitError(GraphAPIError):
    """Exception for rate limiting errors."""
    
    def __init__(self, message: str, retry_after: int = 0, status_code: int = 429):
        super().__init__(message, status_code)
        self.retry_after = retry_after


class GraphAuthError(GraphAPIError):
    """Exception for authentication errors."""
    pass


class GraphNotFoundError(GraphAPIError):
    """Exception for resource not found errors."""
    pass


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class GraphClientConfig:
    """Configuration for Microsoft Graph client."""
    
    base_url: str = "https://graph.microsoft.com/v1.0"
    beta_url: str = "https://graph.microsoft.com/beta"
    
    # Timeout settings
    connect_timeout: int = 30
    read_timeout: int = 60
    write_timeout: int = 60
    
    # Retry settings
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    retry_exponential_base: float = 2.0
    
    # Pagination settings
    default_page_size: int = 100
    max_page_size: int = 1000
    
    # Request batching
    batch_max_requests: int = 20
    batch_max_body_size: int = 4000000  # 4MB
    
    # Caching
    cache_enabled: bool = True
    cache_ttl: int = 300  # 5 minutes
    
    # Debug
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    @classmethod
    def from_env(cls) -> "GraphClientConfig":
        """Create configuration from environment variables."""
        return cls(
            base_url=os.getenv("GRAPH_API_URL", "https://graph.microsoft.com/v1.0"),
            beta_url=os.getenv("GRAPH_BETA_URL", "https://graph.microsoft.com/beta"),
            connect_timeout=int(os.getenv("GRAPH_CONNECT_TIMEOUT", "30")),
            read_timeout=int(os.getenv("GRAPH_READ_TIMEOUT", "60")),
            write_timeout=int(os.getenv("GRAPH_WRITE_TIMEOUT", "60")),
            max_retries=int(os.getenv("GRAPH_MAX_RETRIES", "3")),
            retry_base_delay=float(os.getenv("GRAPH_RETRY_DELAY", "1.0")),
            retry_max_delay=float(os.getenv("GRAPH_RETRY_MAX_DELAY", "30.0")),
            retry_exponential_base=float(os.getenv("GRAPH_RETRY_EXPONENTIAL_BASE", "2.0")),
            default_page_size=int(os.getenv("GRAPH_PAGE_SIZE", "100")),
            max_page_size=int(os.getenv("GRAPH_MAX_PAGE_SIZE", "1000")),
            debug=os.getenv("DEBUG", "false").lower() == "true",
        )


# =============================================================================
# Response Models
# =============================================================================

@dataclass
class GraphResponse(Generic[T]):
    """Generic response from Graph API."""
    
    status_code: int
    data: Optional[T] = None
    raw_data: Optional[dict] = None
    headers: dict = field(default_factory=dict)
    next_link: Optional[str] = None
    delta_link: Optional[str] = None
    
    @property
    def is_success(self) -> bool:
        """Check if the request was successful."""
        return 200 <= self.status_code < 300
    
    @property
    def is_error(self) -> bool:
        """Check if the request failed."""
        return self.status_code >= 400
    
    @property
    def is_rate_limited(self) -> bool:
        """Check if the request was rate limited."""
        return self.status_code == 429
    
    @property
    def retry_after(self) -> Optional[int]:
        """Get retry-after value from headers."""
        retry_after = self.headers.get("Retry-After", None)
        if retry_after:
            try:
                return int(retry_after)
            except ValueError:
                pass
        return None


@dataclass
class PaginatedResponse(Generic[T]):
    """Paginated response from Graph API."""
    
    value: list[T] = field(default_factory=list)
    next_link: Optional[str] = None
    delta_link: Optional[str] = None
    raw_response: Optional[dict] = None
    
    @property
    def has_more(self) -> bool:
        """Check if there are more pages."""
        return self.next_link is not None


# =============================================================================
# HTTP Client
# =============================================================================

class GraphHTTPClient:
    """Low-level HTTP client for Microsoft Graph API."""
    
    def __init__(
        self,
        auth_provider: Optional[EntraAuthProvider] = None,
        config: Optional[GraphClientConfig] = None,
        access_token: Optional[str] = None,
    ):
        """Initialize the HTTP client.
        
        Args:
            auth_provider: Entra ID authentication provider
            config: Graph client configuration
            access_token: Optional access token to use directly
        """
        self.config = config or GraphClientConfig()
        self.auth_provider = auth_provider
        self._access_token = access_token
        self._session = requests.Session()
        
        # Configure session
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "SdkVersion": "KirschkeRdpPortal/1.0",
            "User-Agent": "Kirschke RDP Workstation Portal/1.0",
        })
    
    def _get_access_token(self) -> Optional[str]:
        """Get the current access token."""
        if self._access_token:
            return self._access_token
        
        if self.auth_provider:
            token = self.auth_provider.get_token()
            if token:
                return token
            
            # Try to refresh
            if self.auth_provider.refresh_token():
                return self.auth_provider.get_token()
        
        return None
    
    def _get_auth_headers(self) -> dict:
        """Get headers with authorization token."""
        token = self._get_access_token()
        if not token:
            raise GraphAuthError("No access token available", 401)
        
        return {
            "Authorization": f"Bearer {token}",
        }
    
    def request(
        self,
        method: str,
        url: str,
        params: Optional[dict] = None,
        data: Optional[Any] = None,
        json_data: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: Optional[tuple] = None,
        retry_count: int = 0,
    ) -> GraphResponse[dict]:
        """Make an HTTP request to Graph API.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            url: Request URL
            params: Query parameters
            data: Request body (for non-JSON)
            json_data: Request body (for JSON)
            headers: Additional headers
            timeout: Request timeout (connect, read)
            retry_count: Current retry count (internal)
            
        Returns:
            GraphResponse with the result
            
        Raises:
            GraphAPIError: If the request fails after all retries
        """
        # Build full URL
        if not url.startswith("http"):
            url = urljoin(self.config.base_url, url)
        
        # Prepare headers
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        if headers:
            request_headers.update(headers)
        
        # Add auth headers
        try:
            request_headers.update(self._get_auth_headers())
        except GraphAuthError:
            raise
        
        # Prepare timeout
        if timeout is None:
            timeout = (self.config.connect_timeout, self.config.read_timeout)
        
        # Make request
        try:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=request_headers,
                timeout=timeout,
            )
            
            # Parse response
            return self._parse_response(response)
            
        except Timeout:
            if retry_count < self.config.max_retries:
                delay = min(
                    self.config.retry_max_delay,
                    self.config.retry_base_delay * (self.config.retry_exponential_base ** retry_count)
                )
                logger.warning(f"Request timeout, retrying in {delay:.2f}s... ({retry_count + 1}/{self.config.max_retries})")
                time.sleep(delay)
                return self.request(method, url, params, data, json_data, headers, timeout, retry_count + 1)
            raise GraphAPIError("Request timeout", HTTPStatus.REQUEST_TIMEOUT)
            
        except RequestException as e:
            if retry_count < self.config.max_retries:
                delay = min(
                    self.config.retry_max_delay,
                    self.config.retry_base_delay * (self.config.retry_exponential_base ** retry_count)
                )
                logger.warning(f"Request failed, retrying in {delay:.2f}s... ({retry_count + 1}/{self.config.max_retries})")
                time.sleep(delay)
                return self.request(method, url, params, data, json_data, headers, timeout, retry_count + 1)
            raise GraphAPIError(f"Request failed: {str(e)}", HTTPStatus.INTERNAL_SERVER_ERROR)
    
    def _parse_response(self, response: requests.Response) -> GraphResponse[dict]:
        """Parse the HTTP response.
        
        Args:
            response: HTTP response from requests
            
        Returns:
            GraphResponse with parsed data
            
        Raises:
            GraphAPIError: If the response indicates an error
        """
        status_code = response.status_code
        headers = dict(response.headers)
        
        # Handle rate limiting
        if status_code == 429:
            retry_after = headers.get("Retry-After", None)
            try:
                retry_seconds = int(retry_after) if retry_after else 60
            except ValueError:
                retry_seconds = 60
            
            raise GraphRateLimitError(
                f"Rate limited. Retry after {retry_seconds} seconds",
                retry_after=retry_seconds,
                status_code=429,
            )
        
        # Try to parse JSON
        raw_data: Optional[dict] = None
        try:
            if response.content:
                raw_data = response.json()
        except JSONDecodeError:
            # Not JSON, that's ok
            pass
        
        # Check for error response
        if status_code >= 400:
            error_message = raw_data.get("error", {}).get("message", "Unknown error") if raw_data else str(response.content)
            
            if status_code == 401:
                raise GraphAuthError(error_message, status_code, raw_data)
            elif status_code == 404:
                raise GraphNotFoundError(error_message, status_code, raw_data)
            else:
                raise GraphAPIError(error_message, status_code, raw_data)
        
        # Extract next and delta links
        next_link = headers.get("@odata.nextLink") or raw_data.get("@odata.nextLink") if raw_data else None
        delta_link = headers.get("@odata.deltaLink") or raw_data.get("@odata.deltaLink") if raw_data else None
        
        return GraphResponse(
            status_code=status_code,
            data=raw_data,
            raw_data=raw_data,
            headers=headers,
            next_link=next_link,
            delta_link=delta_link,
        )
    
    def get(self, url: str, params: Optional[dict] = None, **kwargs) -> GraphResponse[dict]:
        """GET request."""
        return self.request("GET", url, params=params, **kwargs)
    
    def post(self, url: str, json_data: Optional[dict] = None, data: Optional[Any] = None, **kwargs) -> GraphResponse[dict]:
        """POST request."""
        return self.request("POST", url, json_data=json_data, data=data, **kwargs)
    
    def put(self, url: str, json_data: Optional[dict] = None, data: Optional[Any] = None, **kwargs) -> GraphResponse[dict]:
        """PUT request."""
        return self.request("PUT", url, json_data=json_data, data=data, **kwargs)
    
    def patch(self, url: str, json_data: Optional[dict] = None, data: Optional[Any] = None, **kwargs) -> GraphResponse[dict]:
        """PATCH request."""
        return self.request("PATCH", url, json_data=json_data, data=data, **kwargs)
    
    def delete(self, url: str, **kwargs) -> GraphResponse[dict]:
        """DELETE request."""
        return self.request("DELETE", url, **kwargs)
    
    def close(self) -> None:
        """Close the session."""
        self._session.close()
    
    def __enter__(self) -> "GraphHTTPClient":
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


# =============================================================================
# Graph API Client
# =============================================================================

class GraphClient(GraphHTTPClient):
    """High-level Microsoft Graph API client.
    
    This client provides convenience methods for common Graph API operations
    and handles pagination automatically.
    """
    
    def __init__(
        self,
        auth_provider: Optional[EntraAuthProvider] = None,
        config: Optional[GraphClientConfig] = None,
        access_token: Optional[str] = None,
    ):
        """Initialize the Graph client.
        
        Args:
            auth_provider: Entra ID authentication provider
            config: Graph client configuration
            access_token: Optional access token to use directly
        """
        super().__init__(auth_provider, config, access_token)
    
    def get_paginated(
        self,
        url: str,
        params: Optional[dict] = None,
        page_size: Optional[int] = None,
    ) -> PaginatedResponse[dict]:
        """Get paginated results from Graph API.
        
        Args:
            url: Request URL
            params: Query parameters
            page_size: Number of items per page (uses default if None)
            
        Returns:
            PaginatedResponse with all results
        """
        if params is None:
            params = {}
        
        if page_size is None:
            page_size = self.config.default_page_size
        
        params["$top"] = min(page_size, self.config.max_page_size)
        
        all_results: list[dict] = []
        response = self.get(url, params=params)
        
        if not response.is_success:
            return PaginatedResponse(value=[], raw_response=response.raw_data)
        
        if response.data and isinstance(response.data, dict):
            all_results.extend(response.data.get("value", []))
        
        next_link = response.next_link
        
        # Follow pagination
        while next_link:
            # Extract query parameters from next link
            next_params = self._parse_next_link(next_link)
            if next_params:
                params.update(next_params)
            
            response = self.get(url, params=params)
            
            if not response.is_success:
                break
            
            if response.data and isinstance(response.data, dict):
                all_results.extend(response.data.get("value", []))
            
            next_link = response.next_link
        
        return PaginatedResponse(
            value=all_results,
            next_link=next_link,
            delta_link=response.delta_link,
            raw_response=response.raw_data,
        )
    
    def _parse_next_link(self, next_link: str) -> dict:
        """Parse query parameters from a next link URL."""
        from urllib.parse import urlparse, parse_qs
        
        parsed = urlparse(next_link)
        query_params = parse_qs(parsed.query)
        
        # Flatten single-value lists
        return {k: v[0] if len(v) == 1 else v for k, v in query_params.items()}
    
    def get_all_pages(self, url: str, params: Optional[dict] = None) -> list[dict]:
        """Get all pages of results as a single list.
        
        Args:
            url: Request URL
            params: Query parameters
            
        Returns:
            List of all results
        """
        paginated = self.get_paginated(url, params)
        return paginated.value
    
    def batch_request(self, requests: list[dict]) -> GraphResponse[dict]:
        """Execute a batch request.
        
        Args:
            requests: List of request dictionaries, each with:
                - id: Unique request ID
                - method: HTTP method
                - url: Request URL
                - body: Optional request body
                
        Returns:
            GraphResponse with batch results
        """
        if len(requests) > self.config.batch_max_requests:
            raise GraphAPIError(
                f"Too many requests in batch: {len(requests)} (max: {self.config.batch_max_requests})"
            )
        
        # Check total size
        total_size = sum(
            len(json.dumps(req.get("body", {}))) + len(req.get("url", ""))
            for req in requests
        )
        
        if total_size > self.config.batch_max_body_size:
            raise GraphAPIError(
                f"Batch request too large: {total_size} bytes (max: {self.config.batch_max_body_size})"
            )
        
        batch_body = {"requests": requests}
        return self.post("$batch", json_data=batch_body)
    
    # =========================================================================
    # User Operations
    # =========================================================================
    
    def get_me(self) -> GraphResponse[dict]:
        """Get current user information."""
        return self.get("/me")
    
    def get_user(self, user_id: str) -> GraphResponse[dict]:
        """Get a specific user by ID."""
        return self.get(f"/users/{user_id}")
    
    def get_users(self, filter: Optional[str] = None, select: Optional[list[str]] = None) -> PaginatedResponse[dict]:
        """Get all users.
        
        Args:
            filter: OData filter expression
            select: List of properties to select
            
        Returns:
            PaginatedResponse with user list
        """
        params: dict = {}
        
        if filter:
            params["$filter"] = filter
        
        if select:
            params["$select"] = ",".join(select)
        
        return self.get_paginated("/users", params)
    
    def get_user_groups(self, user_id: Optional[str] = None) -> PaginatedResponse[dict]:
        """Get groups that a user is a member of.
        
        Args:
            user_id: User ID (defaults to current user)
            
        Returns:
            PaginatedResponse with group list
        """
        if user_id:
            return self.get_paginated(f"/users/{user_id}/memberOf")
        return self.get_paginated("/me/memberOf")
    
    def get_user_photo(self, user_id: Optional[str] = None, size: int = 64) -> GraphResponse[bytes]:
        """Get user photo.
        
        Args:
            user_id: User ID (defaults to current user)
            size: Photo size in pixels
            
        Returns:
            GraphResponse with photo data
        """
        if user_id:
            url = f"/users/{user_id}/photo/$value"
        else:
            url = "/me/photo/$value"
        
        # Override accept header for binary data
        headers = {"Accept": "image/jpeg"}
        return self.get(url, headers=headers)
    
    # =========================================================================
    # Group Operations
    # =========================================================================
    
    def get_group(self, group_id: str) -> GraphResponse[dict]:
        """Get a specific group by ID."""
        return self.get(f"/groups/{group_id}")
    
    def get_groups(self, filter: Optional[str] = None, select: Optional[list[str]] = None) -> PaginatedResponse[dict]:
        """Get all groups.
        
        Args:
            filter: OData filter expression
            select: List of properties to select
            
        Returns:
            PaginatedResponse with group list
        """
        params: dict = {}
        
        if filter:
            params["$filter"] = filter
        
        if select:
            params["$select"] = ",".join(select)
        
        return self.get_paginated("/groups", params)
    
    def get_group_members(self, group_id: str) -> PaginatedResponse[dict]:
        """Get members of a group.
        
        Args:
            group_id: Group ID
            
        Returns:
            PaginatedResponse with member list
        """
        return self.get_paginated(f"/groups/{group_id}/members")
    
    def is_user_in_group(self, user_id: str, group_id: str) -> bool:
        """Check if a user is a member of a group.
        
        Args:
            user_id: User ID
            group_id: Group ID
            
        Returns:
            True if user is in group, False otherwise
        """
        try:
            response = self.get(f"/groups/{group_id}/members/{user_id}/$ref")
            return response.is_success
        except GraphNotFoundError:
            return False
    
    # =========================================================================
    # Site and SharePoint Operations
    # =========================================================================
    
    def get_site(self, site_id: str) -> GraphResponse[dict]:
        """Get a SharePoint site by ID.
        
        Args:
            site_id: Site ID (GUID)
            
        Returns:
            GraphResponse with site data
        """
        return self.get(f"/sites/{site_id}")
    
    def get_site_by_url(self, site_url: str) -> GraphResponse[dict]:
        """Get a SharePoint site by URL.
        
        Args:
            site_url: Full site URL
            
        Returns:
            GraphResponse with site data
        """
        # Encode the URL
        encoded_url = site_url.replace("https://", "").replace("/", "%2F").replace(":", "%3A")
        return self.get(f"/sites/{encoded_url}")
    
    def get_site_lists(self, site_id: str) -> PaginatedResponse[dict]:
        """Get all lists in a SharePoint site.
        
        Args:
            site_id: Site ID
            
        Returns:
            PaginatedResponse with list of lists
        """
        return self.get_paginated(f"/sites/{site_id}/lists")
    
    def get_list(self, site_id: str, list_id: str) -> GraphResponse[dict]:
        """Get a specific SharePoint list.
        
        Args:
            site_id: Site ID
            list_id: List ID
            
        Returns:
            GraphResponse with list data
        """
        return self.get(f"/sites/{site_id}/lists/{list_id}")
    
    def get_list_by_name(self, site_id: str, list_name: str) -> GraphResponse[dict]:
        """Get a SharePoint list by name.
        
        Args:
            site_id: Site ID
            list_name: List name
            
        Returns:
            GraphResponse with list data
        """
        return self.get(f"/sites/{site_id}/lists/{list_name}")
    
    def get_list_items(
        self,
        site_id: str,
        list_id: str,
        filter: Optional[str] = None,
        select: Optional[list[str]] = None,
        expand: Optional[list[str]] = None,
        order_by: Optional[list[str]] = None,
        top: Optional[int] = None,
    ) -> PaginatedResponse[dict]:
        """Get items from a SharePoint list.
        
        Args:
            site_id: Site ID
            list_id: List ID
            filter: OData filter expression
            select: List of properties to select
            expand: List of properties to expand
            order_by: List of order by expressions
            top: Maximum number of items to return
            
        Returns:
            PaginatedResponse with list items
        """
        params: dict = {}
        
        if filter:
            params["$filter"] = filter
        
        if select:
            params["$select"] = ",".join(select)
        
        if expand:
            params["$expand"] = ",".join(expand)
        
        if order_by:
            params["$orderby"] = ",".join(order_by)
        
        if top:
            params["$top"] = top
        
        return self.get_paginated(f"/sites/{site_id}/lists/{list_id}/items", params)
    
    def get_list_item(self, site_id: str, list_id: str, item_id: str) -> GraphResponse[dict]:
        """Get a specific list item.
        
        Args:
            site_id: Site ID
            list_id: List ID
            item_id: Item ID
            
        Returns:
            GraphResponse with item data
        """
        return self.get(f"/sites/{site_id}/lists/{list_id}/items/{item_id}")
    
    def create_list_item(
        self,
        site_id: str,
        list_id: str,
        data: dict,
    ) -> GraphResponse[dict]:
        """Create a new list item.
        
        Args:
            site_id: Site ID
            list_id: List ID
            data: Item data as dictionary
            
        Returns:
            GraphResponse with created item
        """
        return self.post(f"/sites/{site_id}/lists/{list_id}/items", json_data=data)
    
    def update_list_item(
        self,
        site_id: str,
        list_id: str,
        item_id: str,
        data: dict,
        etag: Optional[str] = None,
    ) -> GraphResponse[dict]:
        """Update a list item.
        
        Args:
            site_id: Site ID
            list_id: List ID
            item_id: Item ID
            data: Item data to update
            etag: ETag for concurrency control
            
        Returns:
            GraphResponse with updated item
        """
        headers = {}
        if etag:
            headers["If-Match"] = etag
        
        return self.patch(
            f"/sites/{site_id}/lists/{list_id}/items/{item_id}",
            json_data=data,
            headers=headers,
        )
    
    def delete_list_item(
        self,
        site_id: str,
        list_id: str,
        item_id: str,
        etag: Optional[str] = None,
    ) -> GraphResponse[dict]:
        """Delete a list item.
        
        Args:
            site_id: Site ID
            list_id: List ID
            item_id: Item ID
            etag: ETag for concurrency control
            
        Returns:
            GraphResponse with delete confirmation
        """
        headers = {}
        if etag:
            headers["If-Match"] = etag
        
        return self.delete(
            f"/sites/{site_id}/lists/{list_id}/items/{item_id}",
            headers=headers,
        )


# =============================================================================
# Factory and Exports
# =============================================================================

def create_graph_client(
    auth_provider: Optional[EntraAuthProvider] = None,
    config: Optional[GraphClientConfig] = None,
    access_token: Optional[str] = None,
) -> GraphClient:
    """Factory function to create a GraphClient.
    
    Args:
        auth_provider: Optional Entra ID authentication provider
        config: Optional client configuration
        access_token: Optional access token
        
    Returns:
        Configured GraphClient instance
    """
    return GraphClient(auth_provider, config, access_token)


__all__ = [
    "GraphAPIError",
    "GraphRateLimitError",
    "GraphAuthError",
    "GraphNotFoundError",
    "GraphClientConfig",
    "GraphResponse",
    "PaginatedResponse",
    "GraphHTTPClient",
    "GraphClient",
    "create_graph_client",
]
