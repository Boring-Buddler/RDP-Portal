"""Mock Microsoft Graph client for Phase 1 development."""

from typing import Optional, Any
from dataclasses import dataclass


@dataclass
class MockGraphClient:
    """Mock Microsoft Graph client for development."""
    
    base_url: str = "https://graph.microsoft.com/v1.0"
    
    def get_user(self, user_id: Optional[str] = None) -> dict:
        """Mock get user."""
        return {
            "id": user_id or "mock-user-id",
            "displayName": "Mock User",
            "userPrincipalName": "user@prof-kirschke.de",
            "mail": "user@prof-kirschke.de",
        }
    
    def get_users(self) -> list[dict]:
        """Mock get users."""
        return [
            {
                "id": "user-1",
                "displayName": "User 1",
                "userPrincipalName": "user1@prof-kirschke.de",
                "mail": "user1@prof-kirschke.de",
            },
            {
                "id": "user-2",
                "displayName": "User 2",
                "userPrincipalName": "user2@prof-kirschke.de",
                "mail": "user2@prof-kirschke.de",
            },
        ]
    
    def get_groups(self) -> list[dict]:
        """Mock get groups."""
        return [
            {
                "id": "group-1",
                "displayName": "RDP Portal Users",
                "description": "Users with access to RDP Portal",
            },
            {
                "id": "group-2",
                "displayName": "RDP Portal Admins",
                "description": "Administrators of RDP Portal",
            },
        ]
    
    def get_group_members(self, group_id: str) -> list[dict]:
        """Mock get group members."""
        return [
            {
                "id": "user-1",
                "displayName": "User 1",
                "userPrincipalName": "user1@prof-kirschke.de",
            }
        ]
    
    def get_sharepoint_list_items(self, site_id: str, list_name: str) -> list[dict]:
        """Mock get SharePoint list items."""
        if list_name == "RDP_Workstations":
            return [
                {
                    "id": "1",
                    "fields": {
                        "WorkstationId": "WS-001",
                        "DisplayName": "Workstation 001",
                        "Hostname": "ws001.kirschke.local",
                        "Enabled": True,
                        "AgentStatus": "online",
                    }
                }
            ]
        return []
    
    def create_sharepoint_list_item(self, site_id: str, list_name: str, data: dict) -> dict:
        """Mock create SharePoint list item."""
        return {
            "id": "new-id",
            "fields": data,
        }
    
    def update_sharepoint_list_item(
        self, site_id: str, list_name: str, item_id: str, data: dict, etag: Optional[str] = None
    ) -> dict:
        """Mock update SharePoint list item."""
        return {
            "id": item_id,
            "fields": data,
            "etag": etag or "new-etag",
        }


__all__ = ["MockGraphClient"]
