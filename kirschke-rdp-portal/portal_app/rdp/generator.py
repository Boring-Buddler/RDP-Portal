"""RDP file generator for Kirschke RDP Workstation Portal."""

import os
import re
import tempfile
import uuid
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from shared.schemas import RDPProfileSchema
from shared.validation import RDPProfileValidator, RDPValidationError


class RDPGenerationError(Exception):
    """Exception raised when RDP file generation fails."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self.message)


class RDPFileGenerator:
    """Generates valid .rdp files from workstation profiles.

    This class creates temporary RDP configuration files that can be
    used to launch mstsc.exe with validated parameters.
    """

    def __init__(self, temp_dir: str | None = None):
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

            # Create filename from the effective target, without unsafe path characters.
            target, _ = profile.resolve_connection_target()
            safe_target = re.sub(r"[^a-zA-Z0-9._-]", "_", target)
            filename = f"rdp_{safe_target.replace('.', '_')}_{uuid.uuid4().hex[:8]}.rdp"
            filepath = os.path.join(self.temp_dir, filename)

            # Generate content
            content = self._generate_content(profile)

            # Write file
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            # Track generated file
            self._generated_files.append(filepath)

            return filepath

        except Exception as e:
            raise RDPGenerationError(f"Failed to generate RDP file: {e}") from e

    def validate_profile(self, profile: RDPProfileSchema) -> None:
        """Validate a profile without writing a file.

        Public entry point for the preflight check, which must not generate or
        launch anything.  Raises RDPValidationError on the first problem.
        """
        self._validate_profile(profile)

    def _validate_profile(self, profile: RDPProfileSchema) -> None:
        """Validate the RDP profile."""
        # Check at the output boundary, also for profiles changed after validation.
        for name in ("hostname", "fqdn", "ip_address", "username_hint", "display_name", "gateway_hostname"):
            value = getattr(profile, name)
            if value and any(ord(char) < 32 or char in "\x7f\x85\u2028\u2029" for char in value):
                raise RDPValidationError("RDP values must not contain control characters", name)
        if profile.screen_mode not in {None, "fullscreen", "windowed"}:
            raise RDPValidationError("Invalid screen mode", "screen_mode")
        if profile.resolution:
            match = re.fullmatch(r"(\d+)\s*[x,]\s*(\d+)", profile.resolution.strip())
            if not match or not all(200 <= int(part) <= 8192 for part in match.groups()):
                raise RDPValidationError("Invalid resolution (200–8192 pixels)", "resolution")
        try:
            target, _ = profile.resolve_connection_target()
        except ValueError as exc:
            raise RDPValidationError(str(exc), "connection_target") from exc
        RDPProfileValidator.validate_hostname(target)

        # Validate gateway if present
        if profile.gateway_hostname:
            RDPProfileValidator.validate_gateway(profile.gateway_hostname)

        # Validate other fields
        if profile.display_name and len(profile.display_name) > 100:
            raise RDPValidationError("Display name too long", "display_name", profile.display_name)

    def _generate_content(self, profile: RDPProfileSchema) -> str:
        """Generate RDP file content from profile."""
        lines = []

        # Required: the selected IP, hostname or FQDN.
        target, _ = profile.resolve_connection_target()
        if ":" in target and not target.startswith("["):
            target = f"[{target}]"
        lines.append(f"full address:s:{target}")

        # Optional username, spelled the way the target's authentication needs it.
        # Passwords are deliberately left to Windows.
        username = profile.effective_rdp_username()
        if username:
            lines.append(f"username:s:{username}")

        # Microsoft Entra web authentication is unsupported for IP targets.
        lines.append(f"enablerdsaadauth:i:{1 if profile.effective_entra_sso_enabled() else 0}")

        # This is never enabled by default.  It is a deliberate, persisted exception
        # for one known machine after the user verified its address in the portal.
        # Level 2 warns and lets the user continue when the server identity cannot
        # be verified; level 0 would skip the check entirely and hide a
        # man-in-the-middle, so the weaker setting is deliberately not used.
        if profile.trust_unverified_server:
            lines.append("authentication level:i:2")

        # Gateway settings
        if profile.gateway_hostname:
            lines.append(f"gatewayhostname:s:{profile.gateway_hostname}")
            lines.append("gatewayusagemethod:i:1")  # Use gateway
            lines.append("gatewaycredentialssource:i:4")  # Smart card or user entry

        # Display settings
        if profile.screen_mode:
            if profile.screen_mode.lower() == "fullscreen":
                lines.append("screen mode id:i:2")
            elif profile.screen_mode.lower() == "windowed":
                lines.append("screen mode id:i:1")
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
        lines.append(f"drivestoredirect:s:{'*' if profile.redirect_drives else ''}")
        lines.append(f"audiomode:i:{0 if profile.redirect_audio else 2}")

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

        return "\n".join(header + lines)

    def _parse_resolution(self, resolution: str) -> tuple[int, int]:
        """Parse resolution string to width and height."""
        # Try common formats: "1920x1080", "1920 x 1080", "1920,1080"
        resolution = resolution.replace(" ", "").replace(",", "x")

        if "x" in resolution:
            parts = resolution.split("x")
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
        """Delete leftover .rdp files in the temp folder, including orphans.

        The generated files carry the target address and the user name, and they
        used to be removed only in the portal's closeEvent -- a crash or "End
        task" left them behind for good, because the previous implementation only
        looked at the list this process had built. Scanning the folder for the
        generator's own name pattern is what makes a restart clean them up.

        Args:
            older_than_hours: Delete files whose mtime is older than this.

        Returns:
            Number of files deleted
        """
        import time

        count = 0
        cutoff = time.time() - (older_than_hours * 3600)
        try:
            candidates = list(Path(self.temp_dir).glob("rdp_*.rdp"))
        except OSError:
            return 0
        for path in candidates:
            # Only files this generator could have written: rdp_<target>_<8 hex>.rdp
            if not re.fullmatch(r"rdp_.+_[0-9a-f]{8}\.rdp", path.name):
                continue
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                path.unlink()
                count += 1
            except OSError:
                continue
            with suppress(ValueError):
                self._generated_files.remove(str(path))
        return count


# No module-level generator here on purpose. There used to be one, reachable as
# generate_rdp_file()/cleanup_rdp_files(), which tracked its files separately from
# the launcher's generator. Since portal_app.rdp re-exported the launcher's
# cleanup_rdp_files, anything written through this path was never deleted.
# RDPSessionLauncher owns the one generator whose files get cleaned up.

__all__ = [
    "RDPGenerationError",
    "RDPFileGenerator",
]
