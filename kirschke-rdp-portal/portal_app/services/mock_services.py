"""Mock services for Phase 1 development."""

from typing import Optional
from portal_app.models.workstation import Workstation, create_mock_workstations


class MockWorkstationService:
    """Mock workstation service for development."""
    
    def __init__(self):
        """Initialize the mock service."""
        self.workstations: list[Workstation] = create_mock_workstations(20)
    
    def get_all_workstations(self) -> list[Workstation]:
        """Get all workstations."""
        return self.workstations
    
    def get_workstation(self, workstation_id: str) -> Optional[Workstation]:
        """Get a specific workstation by ID."""
        for ws in self.workstations:
            if ws.workstation_id == workstation_id:
                return ws
        return None
    
    def create_workstation(self, workstation: Workstation) -> Workstation:
        """Create a new workstation."""
        self.workstations.append(workstation)
        return workstation
    
    def update_workstation(self, workstation: Workstation) -> Workstation:
        """Update an existing workstation."""
        for i, ws in enumerate(self.workstations):
            if ws.workstation_id == workstation.workstation_id:
                self.workstations[i] = workstation
                return workstation
        return workstation
    
    def delete_workstation(self, workstation_id: str) -> bool:
        """Delete a workstation."""
        for i, ws in enumerate(self.workstations):
            if ws.workstation_id == workstation_id:
                del self.workstations[i]
                return True
        return False
    
    def set_flag(
        self,
        workstation_id: str,
        flag_type: str,
        reason: str,
        user_upn: str,
        user_object_id: str
    ) -> bool:
        """Set a manual flag on a workstation."""
        from shared.enums import ManualFlagType
        from datetime import datetime
        
        ws = self.get_workstation(workstation_id)
        if not ws:
            return False
        
        flag_enum = ManualFlagType(flag_type)
        ws.manual_flag_type = flag_enum
        ws.manual_flag_reason = reason
        ws.manual_flag_set_by_upn = user_upn
        ws.manual_flag_set_by_object_id = user_object_id
        ws.manual_flag_set_at_utc = datetime.now()
        
        return True
    
    def clear_flag(self, workstation_id: str) -> bool:
        """Clear a manual flag on a workstation."""
        from shared.enums import ManualFlagType
        
        ws = self.get_workstation(workstation_id)
        if not ws:
            return False
        
        ws.manual_flag_type = ManualFlagType.NONE
        ws.manual_flag_reason = None
        ws.manual_flag_set_by_upn = None
        ws.manual_flag_set_by_object_id = None
        ws.manual_flag_set_at_utc = None
        
        return True


__all__ = ["MockWorkstationService"]
