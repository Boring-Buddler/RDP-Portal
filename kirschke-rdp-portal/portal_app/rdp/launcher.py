"""RDP session launcher for Kirschke RDP Workstation Portal."""

import os
import subprocess
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from pathlib import Path

from shared.schemas import RDPProfileSchema
from portal_app.rdp.generator import RDPFileGenerator, RDPGenerationError


logger = logging.getLogger(__name__)


@dataclass
class TrackedRDPSession:
    """A local mstsc process started by the portal."""

    pid: int
    workstation_id: str
    display_name: str
    target: str
    started_at: datetime
    rdp_file: str
    process: subprocess.Popen = field(repr=False)
    return_code: int | None = None


class RDPSessionLauncher:
    """Launches RDP sessions using mstsc.exe.
    
    This class handles the secure launching of mstsc.exe with
    generated RDP configuration files.
    """
    
    def __init__(self, rdp_generator: Optional[RDPFileGenerator] = None):
        """Initialize the launcher.
        
        Args:
            rdp_generator: Optional RDP file generator. If None, creates one.
        """
        self.generator = rdp_generator or RDPFileGenerator()
        self._active_sessions: dict[int, TrackedRDPSession] = {}
        self._finished_sessions: list[TrackedRDPSession] = []
    
    def launch(
        self,
        profile: RDPProfileSchema,
        workstation_id: str | None = None,
        display_name: str | None = None,
    ) -> tuple[bool, str]:
        """Launch an RDP session.
        
        Args:
            profile: The RDP profile to use
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Generate RDP file
            rdp_file = self.generator.generate(profile)
            
            # Launch mstsc.exe
            return self._launch_mstsc(rdp_file, profile, workstation_id, display_name)
            
        except RDPGenerationError as e:
            logger.error(f"RDP generation failed: {e}")
            return False, f"RDP-Datei konnte nicht erstellt werden: {e.message}"
        except Exception as e:
            logger.error(f"RDP launch failed: {e}")
            return False, f"RDP-Start fehlgeschlagen: {e}"
    
    def _launch_mstsc(
        self,
        rdp_file: str,
        profile: RDPProfileSchema,
        workstation_id: str | None,
        display_name: str | None,
    ) -> tuple[bool, str]:
        """Launch mstsc.exe with the generated file.
        
        Args:
            rdp_file: Path to the .rdp file
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Check if mstsc.exe exists
            mstsc_path = self._find_mstsc()
            if not mstsc_path:
                return False, "mstsc.exe nicht gefunden"
            
            # Build command
            # Use subprocess.Popen with argument list to prevent injection
            command = [mstsc_path, rdp_file]
            
            # Start process
            process = subprocess.Popen(
                command,
                shell=False,
                stdin=None,
                stdout=None,
                stderr=None,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            )
            
            target, _ = profile.resolve_connection_target()
            tracked = TrackedRDPSession(
                pid=process.pid,
                workstation_id=workstation_id or target,
                display_name=display_name or profile.display_name,
                target=target,
                started_at=datetime.now(),
                rdp_file=rdp_file,
                process=process,
            )
            self._active_sessions[process.pid] = tracked
            
            logger.info(f"Launched mstsc.exe with RDP file: {rdp_file}")
            return True, f"RDP-Verbindung zu {Path(rdp_file).name} gestartet"
            
        except OSError as e:
            logger.error(f"Failed to start mstsc.exe: {e}")
            return False, f"mstsc.exe konnte nicht gestartet werden: {e}"
        except Exception as e:
            logger.error(f"Unexpected error launching mstsc.exe: {e}")
            return False, f"Fehler beim Starten von mstsc.exe: {e}"

    def get_active_sessions(self) -> list[TrackedRDPSession]:
        """Return processes that still have a running local RDP window."""
        for pid, session in list(self._active_sessions.items()):
            return_code = session.process.poll()
            if return_code is None:
                continue
            session.return_code = return_code
            self._finished_sessions.append(session)
            del self._active_sessions[pid]
        return list(self._active_sessions.values())

    def has_active_session(self, workstation_id: str) -> bool:
        return any(
            session.workstation_id == workstation_id
            for session in self.get_active_sessions()
        )

    def consume_finished_sessions(self) -> list[TrackedRDPSession]:
        self.get_active_sessions()
        finished = self._finished_sessions[:]
        self._finished_sessions.clear()
        return finished

    def disconnect_session(
        self,
        workstation_id: str,
        timeout_seconds: float = 2.0,
    ) -> tuple[int, list[str]]:
        """Close tracked mstsc processes for one workstation only."""
        self.get_active_sessions()
        matches = [
            (pid, session)
            for pid, session in self._active_sessions.items()
            if session.workstation_id == workstation_id
        ]
        return self._disconnect_sessions(matches, timeout_seconds)

    def _disconnect_sessions(
        self,
        sessions: list[tuple[int, TrackedRDPSession]],
        timeout_seconds: float,
    ) -> tuple[int, list[str]]:
        disconnected = 0
        failures: list[str] = []
        for pid, session in sessions:
            try:
                session.process.terminate()
                try:
                    session.process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    session.process.kill()
                    session.process.wait(timeout=timeout_seconds)
                session.return_code = session.process.poll()
                self._finished_sessions.append(session)
                del self._active_sessions[pid]
                disconnected += 1
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("Could not close RDP process %s: %s", pid, exc)
                failures.append(session.display_name)
        return disconnected, failures
    
    def _find_mstsc(self) -> Optional[str]:
        """Find the path to mstsc.exe.
        
        Returns:
            Path to mstsc.exe or None if not found
        """
        # Common locations for mstsc.exe
        locations = [
            # System32 (most common)
            os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "mstsc.exe"),
            # SysWOW64 (on 64-bit systems)
            os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "SysWOW64", "mstsc.exe"),
            # Direct in Windows directory
            os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "mstsc.exe"),
        ]
        
        for location in locations:
            if os.path.exists(location):
                return location
        
        # Try to find it in PATH
        try:
            import shutil
            return shutil.which("mstsc.exe")
        except ImportError:
            pass
        
        return None
    
    def test_rdp_file(self, rdp_file: str) -> tuple[bool, str]:
        """Test if an RDP file can be opened.
        
        This method validates the RDP file by attempting to parse it.
        
        Args:
            rdp_file: Path to the .rdp file
            
        Returns:
            Tuple of (is_valid: bool, message: str)
        """
        try:
            with open(rdp_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for required fields
            if "full address:s:" not in content:
                return False, "Fehlende Angabe 'full address'"
            
            # Check for forbidden patterns
            from shared.validation import FORBIDDEN_RDP_PATTERNS
            import re
            
            for pattern in FORBIDDEN_RDP_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    return False, f"RDP-Datei enthalt verbotene Muster: {pattern}"
            
            return True, "RDP-Datei ist gueltig"
            
        except Exception as e:
            return False, f"RDP-Datei kann nicht gelesen werden: {e}"


# Global launcher instance
_launcher = RDPSessionLauncher()


def launch_rdp_session(
    profile: RDPProfileSchema,
    workstation_id: str | None = None,
    display_name: str | None = None,
) -> tuple[bool, str]:
    """Launch an RDP session (convenience function)."""
    return _launcher.launch(profile, workstation_id, display_name)


def get_active_rdp_sessions() -> list[TrackedRDPSession]:
    return _launcher.get_active_sessions()


def has_active_rdp_session(workstation_id: str) -> bool:
    return _launcher.has_active_session(workstation_id)


def consume_finished_rdp_sessions() -> list[TrackedRDPSession]:
    return _launcher.consume_finished_sessions()


def disconnect_rdp_session(
    workstation_id: str,
    timeout_seconds: float = 2.0,
) -> tuple[int, list[str]]:
    """Close RDP clients started for one workstation."""
    return _launcher.disconnect_session(workstation_id, timeout_seconds)


def test_rdp_file(rdp_file: str) -> tuple[bool, str]:
    """Test an RDP file (convenience function)."""
    return _launcher.test_rdp_file(rdp_file)


def cleanup_rdp_files() -> int:
    """Remove temporary RDP files created by the shared launcher."""
    return _launcher.generator.cleanup()


__all__ = [
    "RDPSessionLauncher",
    "launch_rdp_session",
    "test_rdp_file",
    "cleanup_rdp_files",
    "TrackedRDPSession",
    "get_active_rdp_sessions",
    "has_active_rdp_session",
    "consume_finished_rdp_sessions",
    "disconnect_rdp_session",
]
