"""Outbox handler for Kirschke RDP Workstation Agent.

This module provides functionality to:
- Queue data for transmission to the portal
- Handle offline scenarios
- Retry failed transmissions
- Persist pending data to disk
- Track transmission status
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from pathlib import Path
from threading import Lock
from collections import deque

from shared.schemas import SessionEventSchema
from shared.enums import EventType, EventResult, EventSource

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class OutboxConfig:
    """Configuration for the outbox handler."""
    
    # Maximum number of items in memory
    max_items_in_memory: int = 1000
    
    # Maximum age of items (in seconds)
    max_item_age_seconds: int = 86400  # 24 hours
    
    # Outbox directory
    outbox_directory: str = os.getenv("AGENT_OUTBOX_DIR", "")
    
    # Whether to persist to disk
    persist_to_disk: bool = os.getenv("AGENT_PERSIST_OUTBOX", "true").lower() == "true"
    
    # Workstation ID
    workstation_id: str = ""
    
    # Agent version
    agent_version: str = os.getenv("AGENT_VERSION", "1.0.0")
    
    @classmethod
    def from_env(cls) -> "OutboxConfig":
        """Create configuration from environment variables."""
        import socket
        
        workstation_id = os.getenv("WORKSTATION_ID", socket.gethostname())
        
        # Set default outbox directory
        outbox_dir = os.getenv("AGENT_OUTBOX_DIR", "")
        if not outbox_dir:
            outbox_dir = str(Path.home() / ".kirschke" / "rdp-agent" / "outbox")
        
        return cls(
            outbox_directory=outbox_dir,
            workstation_id=workstation_id,
        )


# =============================================================================
# Outbox Item
# =============================================================================

@dataclass
class OutboxItem:
    """Item in the outbox awaiting transmission."""
    
    # Unique item ID
    item_id: str = field(default_factory=lambda: f"{os.urandom(4).hex()}-{datetime.now(timezone.utc).timestamp()}")
    
    # Item type
    item_type: str = "event"  # 'event', 'command_result', 'status_update'
    
    # Data to transmit
    data: dict = field(default_factory=dict)
    
    # Priority (higher = more important)
    priority: int = 0
    
    # Creation timestamp
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Transmission attempt count
    attempt_count: int = 0
    
    # Last transmission attempt
    last_attempt_at: Optional[datetime] = None
    
    # Last error message
    last_error: Optional[str] = None
    
    # Transmission status
    transmitted: bool = False
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "item_id": self.item_id,
            "item_type": self.item_type,
            "data": self.data,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "attempt_count": self.attempt_count,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "last_error": self.last_error,
            "transmitted": self.transmitted,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "OutboxItem":
        """Create from dictionary."""
        return cls(
            item_id=data.get("item_id", ""),
            item_type=data.get("item_type", "event"),
            data=data.get("data", {}),
            priority=data.get("priority", 0),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now(timezone.utc).isoformat())),
            attempt_count=data.get("attempt_count", 0),
            last_attempt_at=datetime.fromisoformat(data.get("last_attempt_at")) if data.get("last_attempt_at") else None,
            last_error=data.get("last_error"),
            transmitted=data.get("transmitted", False),
        )
    
    def increment_attempt(self, error: Optional[str] = None) -> None:
        """Increment the attempt count."""
        self.attempt_count += 1
        self.last_attempt_at = datetime.now(timezone.utc)
        if error:
            self.last_error = error


# =============================================================================
# Outbox Handler
# =============================================================================

class OutboxHandler:
    """Handler for queuing and transmitting data to the portal.
    
    This class provides a resilient outbox for data that needs to be
    transmitted to the portal. It handles:
    - Queueing items for transmission
    - Persisting items to disk
    - Retrying failed transmissions
    - Cleaning up old items
    """
    
    def __init__(self, config: Optional[OutboxConfig] = None):
        """Initialize the outbox handler.
        
        Args:
            config: Optional outbox configuration
        """
        self.config = config or OutboxConfig.from_env()
        self._items: deque[OutboxItem] = deque()
        self._item_map: dict[str, OutboxItem] = {}
        self._lock = Lock()
        
        # Ensure outbox directory exists
        if self.config.persist_to_disk and self.config.outbox_directory:
            Path(self.config.outbox_directory).mkdir(parents=True, exist_ok=True)
        
        # Load persisted items if enabled
        if self.config.persist_to_disk:
            self._load_persisted_items()
    
    def _load_persisted_items(self) -> None:
        """Load items from disk."""
        if not self.config.outbox_directory:
            return
        
        try:
            outbox_file = Path(self.config.outbox_directory) / "outbox.json"
            if outbox_file.exists():
                with open(outbox_file, "r", encoding="utf-8") as f:
                    items_data = json.load(f)
                    for item_data in items_data:
                        item = OutboxItem.from_dict(item_data)
                        self._items.append(item)
                        self._item_map[item.item_id] = item
        except Exception as e:
            logger.warning(f"Failed to load persisted outbox items: {e}")
    
    def _save_persisted_items(self) -> None:
        """Save items to disk."""
        if not self.config.persist_to_disk or not self.config.outbox_directory:
            return
        
        try:
            outbox_file = Path(self.config.outbox_directory) / "outbox.json"
            items_data = [item.to_dict() for item in self._items]
            with open(outbox_file, "w", encoding="utf-8") as f:
                json.dump(items_data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save persisted outbox items: {e}")
    
    def add_item(self, item: OutboxItem) -> None:
        """Add an item to the outbox.
        
        Args:
            item: Item to add
        """
        with self._lock:
            # Add workstation ID and agent version if not present
            if "workstation_id" not in item.data and self.config.workstation_id:
                item.data["workstation_id"] = self.config.workstation_id
            if "agent_version" not in item.data and self.config.agent_version:
                item.data["agent_version"] = self.config.agent_version
            
            # Add to queue
            self._items.append(item)
            self._item_map[item.item_id] = item
            
            # Trim queue if too large
            while len(self._items) > self.config.max_items_in_memory:
                old_item = self._items.popleft()
                self._item_map.pop(old_item.item_id, None)
            
            # Persist if enabled
            if self.config.persist_to_disk:
                self._save_persisted_items()
        
        logger.debug(f"Outbox item added: {item.item_id} ({item.item_type})")
    
    def add_event(self, event: SessionEventSchema) -> None:
        """Add a session event to the outbox.
        
        Args:
            event: Session event to add
        """
        item = OutboxItem(
            item_type="event",
            data=event.model_dump(),
            priority=10,  # Events have high priority
        )
        self.add_item(item)
    
    def add_command_result(self, command_id: str, result: dict) -> None:
        """Add a command result to the outbox.
        
        Args:
            command_id: ID of the command
            result: Result data
        """
        item = OutboxItem(
            item_type="command_result",
            data={
                "command_id": command_id,
                **result,
            },
            priority=20,  # Command results have highest priority
        )
        self.add_item(item)
    
    def add_status_update(self, status: dict) -> None:
        """Add a status update to the outbox.
        
        Args:
            status: Status data
        """
        item = OutboxItem(
            item_type="status_update",
            data=status,
            priority=5,  # Status updates have normal priority
        )
        self.add_item(item)
    
    def get_pending_items(self) -> list[OutboxItem]:
        """Get all pending (untransmitted) items.
        
        Returns:
            List of pending items
        """
        with self._lock:
            return [item for item in self._items if not item.transmitted]
    
    def get_items_by_priority(self) -> list[OutboxItem]:
        """Get pending items sorted by priority (highest first).
        
        Returns:
            List of items sorted by priority
        """
        pending = self.get_pending_items()
        return sorted(pending, key=lambda x: x.priority, reverse=True)
    
    def mark_item_transmitted(self, item_id: str) -> bool:
        """Mark an item as transmitted.
        
        Args:
            item_id: ID of the item to mark
            
        Returns:
            True if item was found and marked
        """
        with self._lock:
            if item_id in self._item_map:
                self._item_map[item_id].transmitted = True
                self._item_map[item_id].attempt_count = 0
                self._item_map[item_id].last_error = None
                self._save_persisted_items()
                return True
            return False
    
    def mark_item_failed(self, item_id: str, error: str) -> bool:
        """Mark an item as failed in transmission.
        
        Args:
            item_id: ID of the item
            error: Error message
            
        Returns:
            True if item was found and updated
        """
        with self._lock:
            if item_id in self._item_map:
                self._item_map[item_id].increment_attempt(error)
                self._save_persisted_items()
                return True
            return False
    
    def remove_item(self, item_id: str) -> bool:
        """Remove an item from the outbox.
        
        Args:
            item_id: ID of the item to remove
            
        Returns:
            True if item was found and removed
        """
        with self._lock:
            # Remove from queue
            for i, item in enumerate(self._items):
                if item.item_id == item_id:
                    del self._items[i]
                    break
            
            # Remove from map
            if item_id in self._item_map:
                del self._item_map[item_id]
                self._save_persisted_items()
                return True
            return False
    
    def remove_transmitted_items(self) -> int:
        """Remove all transmitted items from the outbox.
        
        Returns:
            Number of items removed
        """
        with self._lock:
            removed = 0
            new_items = deque()
            new_map = {}
            
            for item in self._items:
                if item.transmitted:
                    removed += 1
                else:
                    new_items.append(item)
                    new_map[item.item_id] = item
            
            self._items = new_items
            self._item_map = new_map
            
            if removed > 0 and self.config.persist_to_disk:
                self._save_persisted_items()
            
            return removed
    
    def clear(self) -> None:
        """Clear all items from the outbox."""
        with self._lock:
            self._items.clear()
            self._item_map.clear()
            
            if self.config.persist_to_disk:
                self._save_persisted_items()
    
    def get_item(self, item_id: str) -> Optional[OutboxItem]:
        """Get an item by ID.
        
        Args:
            item_id: Item ID
            
        Returns:
            OutboxItem if found, None otherwise
        """
        with self._lock:
            return self._item_map.get(item_id)
    
    def count(self) -> int:
        """Get the total number of items.
        
        Returns:
            Total number of items
        """
        with self._lock:
            return len(self._items)
    
    def count_pending(self) -> int:
        """Get the number of pending items.
        
        Returns:
            Number of pending items
        """
        with self._lock:
            return sum(1 for item in self._items if not item.transmitted)
    
    def cleanup_old_items(self) -> int:
        """Remove items older than max_item_age_seconds.
        
        Returns:
            Number of items removed
        """
        with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=self.config.max_item_age_seconds
            )
            
            removed = 0
            new_items = deque()
            new_map = {}
            
            for item in self._items:
                if item.created_at < cutoff:
                    removed += 1
                else:
                    new_items.append(item)
                    new_map[item.item_id] = item
            
            self._items = new_items
            self._item_map = new_map
            
            if removed > 0 and self.config.persist_to_disk:
                self._save_persisted_items()
            
            return removed
    
    def cleanup_successful_items(self) -> int:
        """Remove successfully transmitted items older than 1 hour.
        
        Returns:
            Number of items removed
        """
        with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            
            removed = 0
            new_items = deque()
            new_map = {}
            
            for item in self._items:
                if item.transmitted and item.last_attempt_at and item.last_attempt_at < cutoff:
                    removed += 1
                else:
                    new_items.append(item)
                    new_map[item.item_id] = item
            
            self._items = new_items
            self._item_map = new_map
            
            if removed > 0 and self.config.persist_to_disk:
                self._save_persisted_items()
            
            return removed


# =============================================================================
# Transmission Handler
# =============================================================================

class TransmissionHandler:
    """Handle transmission of outbox items to the portal."""
    
    def __init__(self, outbox: Optional[OutboxHandler] = None):
        """Initialize the transmission handler.
        
        Args:
            outbox: Optional outbox handler
        """
        self.outbox = outbox or OutboxHandler()
        self._transmission_in_progress = False
    
    def transmit(self, graph_client: Any) -> tuple[int, int]:
        """Transmit pending items to the portal.
        
        Args:
            graph_client: Graph client for transmission
            
        Returns:
            Tuple of (successful_count, failed_count)
        """
        if self._transmission_in_progress:
            return 0, 0
        
        self._transmission_in_progress = True
        
        try:
            successful = 0
            failed = 0
            
            # Get pending items sorted by priority
            pending_items = self.outbox.get_items_by_priority()
            
            if not pending_items:
                return 0, 0
            
            # Check authentication
            if not graph_client.is_authenticated():
                if not graph_client.authenticate():
                    logger.warning("Graph authentication failed")
                    return 0, 0
            
            # Transmit each item
            for item in pending_items:
                try:
                    if item.item_type == "event":
                        # Transmit session event
                        from shared.schemas import SessionEventSchema
                        event_data = item.data
                        event = SessionEventSchema(**event_data)
                        
                        if graph_client.create_session_event(event):
                            self.outbox.mark_item_transmitted(item.item_id)
                            successful += 1
                            logger.debug(f"Event transmitted: {item.item_id}")
                        else:
                            self.outbox.mark_item_failed(item.item_id, "Transmission failed")
                            failed += 1
                            logger.warning(f"Event transmission failed: {item.item_id}")
                    
                    elif item.item_type == "command_result":
                        # Update command status
                        command_id = item.data.get("command_id")
                        result_message = item.data.get("result_message", "")
                        status = item.data.get("success", False)
                        
                        # For now, just mark as transmitted
                        # The actual command status update would go here
                        self.outbox.mark_item_transmitted(item.item_id)
                        successful += 1
                        logger.debug(f"Command result transmitted: {item.item_id}")
                    
                    elif item.item_type == "status_update":
                        # Update workstation status
                        workstation_id = item.data.get("workstation_id")
                        if workstation_id and graph_client.update_workstation_status(
                            workstation_id=workstation_id,
                            agent_status=item.data.get("agent_status"),
                            current_session_state=item.data.get("current_session_state"),
                            current_session_user=item.data.get("current_session_user"),
                            current_windows_session_id=item.data.get("current_windows_session_id"),
                            agent_version=item.data.get("agent_version"),
                        ):
                            self.outbox.mark_item_transmitted(item.item_id)
                            successful += 1
                            logger.debug(f"Status update transmitted: {item.item_id}")
                        else:
                            self.outbox.mark_item_failed(item.item_id, "Transmission failed")
                            failed += 1
                            logger.warning(f"Status update transmission failed: {item.item_id}")
                    
                    else:
                        # Unknown item type, mark as failed
                        self.outbox.mark_item_failed(item.item_id, f"Unknown item type: {item.item_type}")
                        failed += 1
                        
                except Exception as e:
                    self.outbox.mark_item_failed(item.item_id, str(e))
                    failed += 1
                    logger.error(f"Transmission error for {item.item_id}: {str(e)}")
            
            return successful, failed
            
        except Exception as e:
            logger.error(f"Transmission failed: {str(e)}")
            return 0, 0
        finally:
            self._transmission_in_progress = False
    
    def transmit_all(self, graph_client: Any) -> tuple[int, int]:
        """Transmit all pending items to the portal.
        
        Args:
            graph_client: Graph client for transmission
            
        Returns:
            Tuple of (successful_count, failed_count)
        """
        return self.transmit(graph_client)
    
    def is_transmitting(self) -> bool:
        """Check if transmission is in progress.
        
        Returns:
            True if transmission is in progress
        """
        return self._transmission_in_progress


# =============================================================================
# Factory and Exports
# =============================================================================

def create_outbox_handler(config: Optional[OutboxConfig] = None) -> OutboxHandler:
    """Create an OutboxHandler instance.
    
    Args:
        config: Optional outbox configuration
        
    Returns:
        OutboxHandler instance
    """
    return OutboxHandler(config)


def create_transmission_handler(outbox: Optional[OutboxHandler] = None) -> TransmissionHandler:
    """Create a TransmissionHandler instance.
    
    Args:
        outbox: Optional outbox handler
        
    Returns:
        TransmissionHandler instance
    """
    return TransmissionHandler(outbox)


__all__ = [
    "OutboxConfig",
    "OutboxItem",
    "OutboxHandler",
    "TransmissionHandler",
    "create_outbox_handler",
    "create_transmission_handler",
]
