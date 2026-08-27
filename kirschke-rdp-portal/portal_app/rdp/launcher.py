"""RDP session launcher for Kirschke RDP Workstation Portal."""

import os
import sys
import subprocess
import logging
from typing import Optional
from pathlib import Path

from shared.schemas import RDPProfileSchema
from portal_app.rdp.generator import RDPFileGenerator, RDPGenerationError


logger = logging.getLogger(__name__)


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
    
    def launch(self, profile: RDPProfileSchema) -> tuple[bool, str]:
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
            return self._launch_mstsc(rdp_file)
            
        except RDPGenerationError as e:
            logger.error(f"RDP generation failed: {e}")
            return False, f"RDP-Datei konnte nicht erstellt werden: {e.message}"
        except Exception as e:
            logger.error(f"RDP launch failed: {e}")
            return False, f"RDP-Start fehlgeschlagen: {e}"
    
    def _launch_mstsc(self, rdp_file: str) -> tuple[bool, str]:
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
            
            # Detach from parent process
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.kernel32.CloseHandle(process._handle)
            
            logger.info(f"Launched mstsc.exe with RDP file: {rdp_file}")
            return True, f"RDP-Verbindung zu {Path(rdp_file).name} gestartet"
            
        except OSError as e:
            logger.error(f"Failed to start mstsc.exe: {e}")
            return False, f"mstsc.exe konnte nicht gestartet werden: {e}"
        except Exception as e:
            logger.error(f"Unexpected error launching mstsc.exe: {e}")
            return False, f"Fehler beim Starten von mstsc.exe: {e}"
    
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


def launch_rdp_session(profile: RDPProfileSchema) -> tuple[bool, str]:
    """Launch an RDP session (convenience function)."""
    return _launcher.launch(profile)


def test_rdp_file(rdp_file: str) -> tuple[bool, str]:
    """Test an RDP file (convenience function)."""
    return _launcher.test_rdp_file(rdp_file)


__all__ = [
    "RDPSessionLauncher",
    "launch_rdp_session",
    "test_rdp_file",
]
