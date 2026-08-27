"""Admin command model for Kirschke RDP Workstation Portal."""

from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass
from shared.enums import CommandType, CommandStatus
from shared.schemas import AdminCommandSchema
from shared.validation import generate_test_entra_id, generate_test_upn


@dataclass
class AdminCommand:
    """An admin command to be executed by the workstation agent."""
    
    command_id: str
    target_workstation_id: str
    target_windows_session_id: Optional[int]
    command_type: CommandType
    requested_by_object_id: str
    requested_by_upn: str
    requested_at_utc: datetime
    expires_at_utc: datetime
    reason: Optional[str] = None
    status: CommandStatus = CommandStatus.PENDING
    executed_at_utc: Optional[datetime] = None
    result_message: Optional[str] = None
    
    def __post_init__(self):
        """Validate and initialize after creation."""
        if isinstance(self.command_type, str):
            self.command_type = CommandType(self.command_type)
        if isinstance(self.status, str):
            self.status = CommandStatus(self.status)
    
    def to_schema(self) -> AdminCommandSchema:
        """Convert to Pydantic schema."""
        return AdminCommandSchema(
            command_id=self.command_id,
            target_workstation_id=self.target_workstation_id,
            target_windows_session_id=self.target_windows_session_id,
            command_type=self.command_type,
            requested_by_object_id=self.requested_by_object_id,
            requested_by_upn=self.requested_by_upn,
            requested_at_utc=self.requested_at_utc,
            expires_at_utc=self.expires_at_utc,
            reason=self.reason,
            status=self.status,
            executed_at_utc=self.executed_at_utc,
            result_message=self.result_message,
        )
    
    @classmethod
    def from_schema(cls, schema: AdminCommandSchema) -> "AdminCommand":
        """Create from Pydantic schema."""
        return cls(
            command_id=schema.command_id,
            target_workstation_id=schema.target_workstation_id,
            target_windows_session_id=schema.target_windows_session_id,
            command_type=schema.command_type,
            requested_by_object_id=schema.requested_by_object_id,
            requested_by_upn=schema.requested_by_upn,
            requested_at_utc=schema.requested_at_utc,
            expires_at_utc=schema.expires_at_utc,
            reason=schema.reason,
            status=schema.status,
            executed_at_utc=schema.executed_at_utc,
            result_message=schema.result_message,
        )
    
    def is_expired(self) -> bool:
        """Check if the command has expired."""
        return datetime.now() > self.expires_at_utc
    
    def is_pending(self) -> bool:
        """Check if the command is still pending."""
        return self.status == CommandStatus.PENDING and not self.is_expired()
    
    def can_be_executed(self) -> bool:
        """Check if the command can be executed."""
        return self.is_pending()
    
    def mark_executed(self, result_message: str = "Success") -> None:
        """Mark the command as executed."""
        self.status = CommandStatus.EXECUTED
        self.executed_at_utc = datetime.now()
        self.result_message = result_message
    
    def mark_failed(self, result_message: str) -> None:
        """Mark the command as failed."""
        self.status = CommandStatus.FAILED
        self.executed_at_utc = datetime.now()
        self.result_message = result_message
    
    def get_display_type(self) -> str:
        """Get human-readable command type."""
        type_names = {
            CommandType.REFRESH_STATUS: "Status aktualisieren",
            CommandType.DISCONNECT_SESSION: "Sitzung trennen",
            CommandType.LOGOFF_SESSION: "Sitzung abmelden",
            CommandType.CLEAR_MANUAL_FLAG: "Flag entfernen",
        }
        return type_names.get(self.command_type, str(self.command_type))
    
    def get_display_status(self) -> str:
        """Get human-readable status."""
        status_names = {
            CommandStatus.PENDING: "Ausstehend",
            CommandStatus.EXECUTED: "Ausgefuehrt",
            CommandStatus.FAILED: "Fehlgeschlagen",
            CommandStatus.EXPIRED: "Abgelaufen",
        }
        return status_names.get(self.status, str(self.status))


def create_mock_admin_commands(count: int = 5) -> list[AdminCommand]:
    """Create mock admin commands for development."""
    commands = []
    workstation_ids = [f"WS-{i:03d}" for i in range(1, 6)]
    command_types = [
        CommandType.REFRESH_STATUS,
        CommandType.DISCONNECT_SESSION,
        CommandType.LOGOFF_SESSION,
        CommandType.CLEAR_MANUAL_FLAG,
    ]
    
    base_time = datetime.now() - timedelta(hours=1)
    
    for i in range(count):
        command_type = command_types[i % len(command_types)]
        
        command = AdminCommand(
            command_id=f"CMD-{i:05d}",
            target_workstation_id=workstation_ids[i % len(workstation_ids)],
            target_windows_session_id=1,
            command_type=command_type,
            requested_by_object_id=generate_test_entra_id(),
            requested_by_upn=generate_test_upn(),
            requested_at_utc=base_time + timedelta(minutes=i * 10),
            expires_at_utc=base_time + timedelta(minutes=i * 10 + 5),
            reason=f"Testbefehl {i + 1}" if command_type != CommandType.REFRESH_STATUS else None,
            status=CommandStatus.PENDING if i % 3 != 0 else CommandStatus.EXECUTED,
            executed_at_utc=datetime.now() if i % 3 == 0 else None,
            result_message="Erfolgreich ausgefuehrt" if i % 3 == 0 else None,
        )
        commands.append(command)
    
    return commands


__all__ = ["AdminCommand", "create_mock_admin_commands"]
