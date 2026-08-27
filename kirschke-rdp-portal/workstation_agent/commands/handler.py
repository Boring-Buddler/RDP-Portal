"""Admin command handling for Kirschke RDP Workstation Agent.

This module provides functionality to:
- Execute admin commands received from the portal
- Disconnect RDP sessions
- Log off RDP sessions
- Clear manual flags
- Refresh agent status
"""

from __future__ import annotations

import os
import json
import logging
import ctypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any

from shared.enums import CommandType, CommandStatus, EventResult
from shared.schemas import AdminCommandSchema

logger = logging.getLogger(__name__)


# =============================================================================
# Command Result
# =============================================================================

@dataclass
class CommandResult:
    """Result of executing an admin command."""
    
    success: bool
    message: str
    command_id: str = ""
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    result_message: Optional[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "message": self.message,
            "command_id": self.command_id,
            "executed_at": self.executed_at.isoformat(),
            "result_message": self.result_message,
        }


# =============================================================================
# Command Handler
# =============================================================================

class AdminCommandHandler:
    """Handle execution of admin commands from the portal.
    
    This class provides methods to execute various admin commands:
    - DISCONNECT_SESSION: Disconnect an active RDP session
    - LOGOFF_SESSION: Log off an active RDP session
    - CLEAR_MANUAL_FLAG: Clear the manual flag on the workstation
    - REFRESH_STATUS: Force a status update to the portal
    """
    
    def __init__(self):
        """Initialize the command handler."""
        pass
    
    def execute(self, command: AdminCommandSchema) -> CommandResult:
        """Execute an admin command.
        
        Args:
            command: Admin command to execute
            
        Returns:
            CommandResult with execution outcome
        """
        try:
            if command.command_type == CommandType.DISCONNECT_SESSION:
                return self._execute_disconnect_session(command)
            elif command.command_type == CommandType.LOGOFF_SESSION:
                return self._execute_logoff_session(command)
            elif command.command_type == CommandType.CLEAR_MANUAL_FLAG:
                return self._execute_clear_manual_flag(command)
            elif command.command_type == CommandType.REFRESH_STATUS:
                return self._execute_refresh_status(command)
            else:
                return CommandResult(
                    success=False,
                    message=f"Unknown command type: {command.command_type.value}",
                    command_id=command.command_id,
                )
        except Exception as e:
            logger.error(f"Command execution failed: {command.command_id} - {str(e)}")
            return CommandResult(
                success=False,
                message=str(e),
                command_id=command.command_id,
            )
    
    def _execute_disconnect_session(self, command: AdminCommandSchema) -> CommandResult:
        """Execute disconnect session command.
        
        Args:
            command: Admin command
            
        Returns:
            CommandResult with execution outcome
        """
        target_session_id = command.target_windows_session_id
        
        if target_session_id is None:
            return CommandResult(
                success=False,
                message="Target session ID not specified",
                command_id=command.command_id,
            )
        
        try:
            # Use WTS API to disconnect session
            wtsapi32 = ctypes.windll.Wtsapi32
            
            # WTSDisconnectSession function
            # BOOL WTSDisconnectSession(
            #   HANDLE hServer,
            #   DWORD SessionId,
            #   BOOL bWait
            # );
            wtsapi32.WTSDisconnectSession.argtypes = [
                ctypes.c_void_p,  # HANDLE hServer
                ctypes.c_ulong,    # DWORD SessionId
                ctypes.c_bool,     # BOOL bWait
            ]
            wtsapi32.WTSDisconnectSession.restype = ctypes.c_bool
            
            # Open server handle
            server_handle = wtsapi32.WTSOpenServerA(None)
            if not server_handle:
                return CommandResult(
                    success=False,
                    message="Failed to open WTS server handle",
                    command_id=command.command_id,
                )
            
            try:
                # Disconnect the session
                result = wtsapi32.WTSDisconnectSession(
                    server_handle,
                    target_session_id,
                    False,  # Don't wait for disconnect
                )
                
                if result:
                    return CommandResult(
                        success=True,
                        message=f"Session {target_session_id} disconnected successfully",
                        command_id=command.command_id,
                        result_message="Session disconnected",
                    )
                else:
                    # Get error code
                    error_code = ctypes.get_last_error()
                    return CommandResult(
                        success=False,
                        message=f"Failed to disconnect session {target_session_id} (error: {error_code})",
                        command_id=command.command_id,
                    )
            finally:
                # Close server handle
                wtsapi32.WTSCloseServer(server_handle)
                
        except Exception as e:
            return CommandResult(
                success=False,
                message=f"Failed to disconnect session: {str(e)}",
                command_id=command.command_id,
            )
    
    def _execute_logoff_session(self, command: AdminCommandSchema) -> CommandResult:
        """Execute logoff session command.
        
        Args:
            command: Admin command
            
        Returns:
            CommandResult with execution outcome
        """
        target_session_id = command.target_windows_session_id
        
        if target_session_id is None:
            return CommandResult(
                success=False,
                message="Target session ID not specified",
                command_id=command.command_id,
            )
        
        try:
            # Use WTS API to log off session
            wtsapi32 = ctypes.windll.Wtsapi32
            
            # WTSLogoffSession function
            # BOOL WTSLogoffSession(
            #   HANDLE hServer,
            #   DWORD SessionId,
            #   BOOL bWait
            # );
            wtsapi32.WTSLogoffSession.argtypes = [
                ctypes.c_void_p,  # HANDLE hServer
                ctypes.c_ulong,    # DWORD SessionId
                ctypes.c_bool,     # BOOL bWait
            ]
            wtsapi32.WTSLogoffSession.restype = ctypes.c_bool
            
            # Open server handle
            server_handle = wtsapi32.WTSOpenServerA(None)
            if not server_handle:
                return CommandResult(
                    success=False,
                    message="Failed to open WTS server handle",
                    command_id=command.command_id,
                )
            
            try:
                # Log off the session
                result = wtsapi32.WTSLogoffSession(
                    server_handle,
                    target_session_id,
                    False,  # Don't wait for logoff
                )
                
                if result:
                    return CommandResult(
                        success=True,
                        message=f"Session {target_session_id} logged off successfully",
                        command_id=command.command_id,
                        result_message="Session logged off",
                    )
                else:
                    # Get error code
                    error_code = ctypes.get_last_error()
                    return CommandResult(
                        success=False,
                        message=f"Failed to log off session {target_session_id} (error: {error_code})",
                        command_id=command.command_id,
                    )
            finally:
                # Close server handle
                wtsapi32.WTSCloseServer(server_handle)
                
        except Exception as e:
            return CommandResult(
                success=False,
                message=f"Failed to log off session: {str(e)}",
                command_id=command.command_id,
            )
    
    def _execute_clear_manual_flag(self, command: AdminCommandSchema) -> CommandResult:
        """Execute clear manual flag command.
        
        Args:
            command: Admin command
            
        Returns:
            CommandResult with execution outcome
        """
        # This command clears the manual flag on the workstation
        # The actual flag clearing happens in SharePoint via the agent's status update
        # This command is mainly for admin override
        
        return CommandResult(
            success=True,
            message="Manual flag cleared",
            command_id=command.command_id,
            result_message="Manual flag cleared by admin command",
        )
    
    def _execute_refresh_status(self, command: AdminCommandSchema) -> CommandResult:
        """Execute refresh status command.
        
        Args:
            command: Admin command
            
        Returns:
            CommandResult with execution outcome
        """
        # This command forces the agent to update its status immediately
        return CommandResult(
            success=True,
            message="Status refresh requested",
            command_id=command.command_id,
            result_message="Agent will update status on next poll cycle",
        )


# =============================================================================
# Batch Command Handler
# =============================================================================

class BatchCommandHandler:
    """Handle execution of multiple admin commands."""
    
    def __init__(self):
        """Initialize the batch command handler."""
        self._handler = AdminCommandHandler()
    
    def execute_batch(self, commands: list[AdminCommandSchema]) -> list[CommandResult]:
        """Execute a batch of admin commands.
        
        Args:
            commands: List of admin commands to execute
            
        Returns:
            List of CommandResult objects
        """
        results = []
        
        for command in commands:
            result = self._handler.execute(command)
            results.append(result)
            
            # Log the result
            if result.success:
                logger.info(f"Command executed: {command.command_id} - {command.command_type.value}")
            else:
                logger.warning(f"Command failed: {command.command_id} - {result.message}")
        
        return results
    
    def execute_and_report(
        self,
        commands: list[AdminCommandSchema],
        report_callback: Optional[callable] = None,
    ) -> tuple[int, int]:
        """Execute commands and report results via callback.
        
        Args:
            commands: List of commands to execute
            report_callback: Optional callback function(result: CommandResult)
            
        Returns:
            Tuple of (success_count, failure_count)
        """
        success_count = 0
        failure_count = 0
        
        for command in commands:
            result = self._handler.execute(command)
            
            if result.success:
                success_count += 1
            else:
                failure_count += 1
            
            if report_callback:
                report_callback(result)
        
        return success_count, failure_count


# =============================================================================
# Command Queue
# =============================================================================

class CommandQueue:
    """Queue for storing pending admin commands."""
    
    def __init__(self):
        """Initialize the command queue."""
        self._commands: list[AdminCommandSchema] = []
        self._processed: set[str] = set()
    
    def add_command(self, command: AdminCommandSchema) -> None:
        """Add a command to the queue.
        
        Args:
            command: Command to add
        """
        if command.command_id not in self._processed:
            self._commands.append(command)
    
    def add_commands(self, commands: list[AdminCommandSchema]) -> None:
        """Add multiple commands to the queue.
        
        Args:
            commands: List of commands to add
        """
        for command in commands:
            self.add_command(command)
    
    def get_pending_commands(self) -> list[AdminCommandSchema]:
        """Get all pending commands.
        
        Returns:
            List of pending commands
        """
        return list(self._commands)
    
    def mark_command_processed(self, command_id: str) -> bool:
        """Mark a command as processed.
        
        Args:
            command_id: ID of the command to mark as processed
            
        Returns:
            True if command was found and marked
        """
        if command_id in self._processed:
            return False
        
        self._processed.add(command_id)
        
        # Remove from queue
        self._commands = [
            c for c in self._commands
            if c.command_id != command_id
        ]
        
        return True
    
    def clear(self) -> None:
        """Clear all commands from the queue."""
        self._commands.clear()
        self._processed.clear()
    
    def count(self) -> int:
        """Get the number of pending commands.
        
        Returns:
            Number of pending commands
        """
        return len(self._commands)


# =============================================================================
# Factory and Exports
# =============================================================================

def create_command_handler() -> AdminCommandHandler:
    """Create an AdminCommandHandler instance.
    
    Returns:
        AdminCommandHandler instance
    """
    return AdminCommandHandler()


def create_batch_command_handler() -> BatchCommandHandler:
    """Create a BatchCommandHandler instance.
    
    Returns:
        BatchCommandHandler instance
    """
    return BatchCommandHandler()


def create_command_queue() -> CommandQueue:
    """Create a CommandQueue instance.
    
    Returns:
        CommandQueue instance
    """
    return CommandQueue()


__all__ = [
    "CommandResult",
    "AdminCommandHandler",
    "BatchCommandHandler",
    "CommandQueue",
    "create_command_handler",
    "create_batch_command_handler",
    "create_command_queue",
]
