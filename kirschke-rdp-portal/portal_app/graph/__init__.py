"""Microsoft Graph client for Kirschke RDP Workstation Portal."""

# Phase 2: Microsoft Graph integration
# For Phase 1, mock data is used

from portal_app.graph.mock_graph import MockGraphClient
from portal_app.graph.client import (
    GraphAPIError,
    GraphRateLimitError,
    GraphAuthError,
    GraphNotFoundError,
    GraphClientConfig,
    GraphResponse,
    PaginatedResponse,
    GraphHTTPClient,
    GraphClient,
    create_graph_client,
)
from portal_app.graph.sharepoint import (
    SharePointConfig,
    SharePointFieldMappings,
    SharePointDataConverter,
    WorkstationConverter,
    SessionEventConverter,
    AdminCommandConverter,
    AccessRuleConverter,
    SharePointManager,
    create_sharepoint_manager,
)

__all__ = [
    "MockGraphClient",
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
    "SharePointConfig",
    "SharePointFieldMappings",
    "SharePointDataConverter",
    "WorkstationConverter",
    "SessionEventConverter",
    "AdminCommandConverter",
    "AccessRuleConverter",
    "SharePointManager",
    "create_sharepoint_manager",
]

