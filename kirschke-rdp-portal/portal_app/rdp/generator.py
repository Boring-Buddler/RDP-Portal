"""RDP file generator for Kirschke RDP Workstation Portal."""

import os
import tempfile
import uuid
from datetime import datetime
from typing import Optional
from pathlib import Path

from shared.schemas import RDPProfileSchema
from shared.validation import RDPProfileValidator, RDPValidationError


class RDPGenerationError(Exception):
    """Exception raised when RDP file generation fails."""
    
    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)


class RDPFileGenerator:
    """Generates valid .rdp files from workstation profiles.
    
    This class creates temporary RDP configuration files that can be
    used to launch mstsc.exe with validated parameters.
    """
    
    def __init__(self, temp_dir: Optional[str] = None):
        """Initialize the generator.
        
        Args:
            temp_dir: Directory for temporary files. If None, uses system temp.
        """
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self._generated_files: list[str] = []
    
    def generate(self, profile: RDPProfileSchema) -> str:
        """Generate an RDP file from a profile.
        
        Args:
            profile: The validated RDP profile
            
        Returns:
            Path to the generated .rdp file
            
        Raises:
            RDPGenerationError: If generation fails
        """
        try:
            # Validate the profile
            self._validate_profile(profile)
            
            # Create filename
            filename = f"rdp_{profile.hostname.replace('.', '_')}_{uuid.uuid4().hex[:8]}.rdp"
            filepath = os.path.join(self.temp_dir, filename)
            
            # Generate content
            content = self._generate_content(profile)
            
            # Write file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Track generated file
            self._generated_files.append(filepath)
            
            return filepath
            
        except Exception as e:
            raise RDPGenerationError(f"Failed to generate RDP file: {e}") from e
    
    def _validate_profile(self, profile: RDPProfileSchema) -> None:
        """Validate the RDP profile."""
        # Validate hostname
        RDPProfileValidator.validate_hostname(profile.hostname)
        
        # Validate gateway if present
        if profile.gateway_hostname:
            RDPProfileValidator.validate_gateway(profile.gateway_hostname)
        
        # Validate other fields
        if profile.display_name and len(profile.display_name) > 100:
            raise RDPValidationError("Display name too long", "display_name", profile.display_name)
    
    def _generate_content(self, profile: RDPProfileSchema) -> str:
        """Generate RDP file content from profile."""
        lines = []
        
        # Required: full address (hostname or FQDN)
        if profile.fqdn:
            lines.append(f"full address:s:{profile.fqdn}")
        else:
            lines.append(f"full address:s:{profile.hostname}")
        
        # Optional: username hint (as comment, not actual username)
        if profile.username_hint:
            # We store this as a comment since actual username should be entered by user
            # or handled by Entra SSO
            lines.append(f"#username hint:s:{profile.username_hint}")
        
        # Entra SSO
        if profile.entra_sso_enabled:
            lines.append("enablerdsaadauth:i:1")
        
        # Gateway settings
        if profile.gateway_hostname:
            lines.append(f"gatewayhostname:s:{profile.gateway_hostname}")
            lines.append("gatewayusemethod:i:1")  # Use gateway
            lines.append("gatewaycredentialssource:i:4")  # Smart card or user entry
        
        # Display settings
        if profile.screen_mode:
            if profile.screen_mode.lower() == "fullscreen":
                lines.append("winposstr:s:0,1,0,0,0,0")  # Fullscreen
            elif profile.screen_mode.lower() == "windowed":
                # Use resolution if available
                if profile.resolution:
                    width, height = self._parse_resolution(profile.resolution)
                    lines.append(f"desktopwidth:i:{width}")
                    lines.append(f"desktopheight:i:{height}")
        
        if profile.use_all_monitors:
            lines.append("use multimon:i:1")
        
        # Redirection settings
        lines.append(f"redirectclipboard:i:{1 if profile.redirect_clipboard else 0}")
        lines.append(f"redirectprinters:i:{1 if profile.redirect_printers else 0}")
        lines.append(f"redirectdrives:i:{1 if profile.redirect_drives else 0}")
        lines.append(f"redirectaudio:i:{1 if profile.redirect_audio else 0}")
        
        # Performance settings (optimize for remote)
        lines.append("compress:i:1")
        lines.append("bitmapcachepersistenable:i:1")
        
        # Connection quality
        lines.append("connection type:i:7")  # Detect quality automatically
        lines.append("networkautodetect:i:1")
        
        # Disable visual effects for better performance
        lines.append("disable wallpaper:i:1")
        lines.append("allow font smoothing:i:1")
        lines.append("allow desktop composition:i:1")
        lines.append("disable full window drag:i:1")
        lines.append("disable menu anims:i:1")
        lines.append("disable themes:i:0")  # Keep themes for better UI
        
        # Session settings
        lines.append("session bpp:i:32")  # 32-bit color
        
        # Add header
        header = [
            "# Kirschke RDP Workstation Portal",
            f"# Generated: {datetime.now().isoformat()}",
            f"# Workstation: {profile.display_name}",
            "",
        ]
        
        return '\n'.join(header + lines)
    
    def _parse_resolution(self, resolution: str) -> tuple[int, int]:
        """Parse resolution string to width and height."""
        # Try common formats: "1920x1080", "1920 x 1080", "1920,1080"
        resolution = resolution.replace(' ', '').replace(',', 'x')
        
        if 'x' in resolution:
            parts = resolution.split('x')
            try:
                width = int(parts[0])
                height = int(parts[1]) if len(parts) > 1 else 768
                return width, height
            except ValueError:
                pass
        
        # Default to 1024x768
        return 1024, 768
    
    def cleanup(self) -> int:
        """Clean up generated temporary files.
        
        Returns:
            Number of files deleted
        """
        count = 0
        for filepath in self._generated_files[:]:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    count += 1
                self._generated_files.remove(filepath)
            except OSError:
                pass
        return count
    
    def cleanup_old(self, older_than_hours: int = 24) -> int:
        """Clean up old temporary files.
        
        Args:
            older_than_hours: Delete files older than this many hours
            
        Returns:
            Number of files deleted
        """
        import time
        
        count = 0
        cutoff = time.time() - (older_than_hours * 3600)
        
        for filepath in self._generated_files[:]:
            try:
                if os.path.exists(filepath):
                    file_mtime = os.path.getmtime(filepath)
                    if file_mtime < cutoff:
                        os.remove(filepath)
                        self._generated_files.remove(filepath)
                        count += 1
            except OSError:
                pass
        
        return count


# Global generator instance
_generator = RDPFileGenerator()


def generate_rdp_file(profile: RDPProfileSchema) -> str:
    """Generate an RDP file from a profile (convenience function)."""
    return _generator.generate(profile)


def cleanup_rdp_files() -> int:
    """Clean up generated RDP files (convenience function)."""
    return _generator.cleanup()


__all__ = [
    "RDPGenerationError",
    "RDPFileGenerator",
    "generate_rdp_file",
    "cleanup_rdp_files",
]
