"""Validation utilities for Kirschke RDP Workstation Portal."""

import re
from typing import Optional
import uuid
import sys
import platform


class RDPValidationError(Exception):
    def __init__(self, message: str, field: Optional[str] = None, value: Optional[str] = None):
        self.message = message
        self.field = field
        self.value = value
        super().__init__(self.message)


ALLOWED_RDP_OPTIONS = {
    "desktopwidth", "desktopheight", "winposstr",
    "full address", "compress", "keyboardhook",
    "audiocapturemode", "videoplaybackmode", "connection type",
    "networkautodetect", "redirectclipboard", "redirectposdevices",
    "redirectprinters", "redirectcomports", "redirectsmartcards",
    "redirectdrives", "drivestoredirect", "audiomode",
    "redirectaudio", "use multimon", "selectedmonitors",
    "username", "domain", "alternate shell",
    "shell working directory", "gatewayhostname",
    "gatewayusemethod", "gatewaycredentialssource",
    "gatewayprofileusemethod", "promptcredentialonce",
    "enablerdsaadauth", "session bpp", "compresslevel",
    "bitmapcachepersistenable", "disable wallpaper",
    "allow font smoothing", "allow desktop composition",
    "disable full window drag", "disable menu anims",
    "disable themes",
}

FORBIDDEN_RDP_PATTERNS = [
    "password", "cmd", "powershell", "executable",
    "|", ";", "&&", "$", "`", ">", "<",
]

MAX_HOSTNAME_LENGTH = 256
MAX_UPN_LENGTH = 256
MAX_REASON_LENGTH = 500
COMMAND_EXPIRY_MINUTES = 5
AGENT_POLL_INTERVAL_SECONDS = 30
SESSION_SYNC_INTERVAL_SECONDS = 60
ALLOWED_RDP_FILE_EXTENSION = ".rdp"


class RDPProfileValidator:
    @staticmethod
    def validate_hostname(hostname: str) -> str:
        if not hostname:
            raise RDPValidationError("Hostname cannot be empty", "hostname", hostname)
        if len(hostname) > MAX_HOSTNAME_LENGTH:
            raise RDPValidationError("Hostname too long", "hostname", hostname)
        forbidden_chars = [";", "|", "&", "`", "$", ">", "<", "\\", "/"]
        if any(char in hostname for char in forbidden_chars):
            raise RDPValidationError("Hostname contains forbidden characters", "hostname", hostname)
        for pattern in FORBIDDEN_RDP_PATTERNS:
            if pattern.lower() in hostname.lower():
                raise RDPValidationError("Hostname matches forbidden pattern", "hostname", hostname)
        hostname_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$"
        fqdn_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
        ip_pattern = r"^(\d{1,3}\.){3}\d{1,3}$"
        if not (re.match(hostname_pattern, hostname) or re.match(fqdn_pattern, hostname) or re.match(ip_pattern, hostname)):
            raise RDPValidationError("Hostname has invalid format", "hostname", hostname)
        return hostname
    
    @staticmethod
    def validate_gateway(gateway: Optional[str]) -> Optional[str]:
        if gateway is None:
            return None
        return RDPProfileValidator.validate_hostname(gateway)
    
    @staticmethod
    def validate_option_name(name: str) -> str:
        if not name:
            raise RDPValidationError("Option name cannot be empty", "option_name", name)
        if len(name) > 100:
            raise RDPValidationError("Option name too long", "option_name", name)
        if name not in ALLOWED_RDP_OPTIONS:
            raise RDPValidationError("Option not in allowlist", "option_name", name)
        return name
    
    @staticmethod
    def validate_rdp_content(content: str) -> str:
        if not content:
            raise RDPValidationError("RDP content cannot be empty", "content")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                raise RDPValidationError(f"Invalid RDP line: {line}", "content")
            option_with_type, value = line.split(":", 1)
            option_name = option_with_type.split(":")[0].strip()
            RDPProfileValidator.validate_option_name(option_name)
        return content


def validate_entra_id(entra_id: str) -> str:
    if not entra_id:
        raise ValueError("Entra ID cannot be empty")
    guid_pattern = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    if not re.match(guid_pattern, entra_id):
        raise ValueError(f"Invalid Entra ID format: {entra_id}")
    return entra_id


def validate_upn(upn: str) -> str:
    if not upn:
        raise ValueError("UPN cannot be empty")
    if len(upn) > MAX_UPN_LENGTH:
        raise ValueError("UPN too long")
    upn_pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    if not re.match(upn_pattern, upn):
        raise ValueError(f"Invalid UPN format: {upn}")
    return upn


def validate_reason(reason: str, max_length: int = MAX_REASON_LENGTH) -> str:
    if not reason:
        raise ValueError("Reason cannot be empty")
    if len(reason) > max_length:
        raise ValueError(f"Reason too long (max {max_length} chars)")
    if chr(10) in reason or chr(13) in reason:
        raise ValueError("Reason cannot contain newlines")
    return reason.strip()


def validate_environment() -> dict:
    info = {"python_version": sys.version, "python_version_info": sys.version_info, "platform": platform.system(), "platform_version": platform.version()}
    if sys.version_info < (3, 12):
        raise EnvironmentError("Python 3.12+ required")
    if platform.system() != "Windows":
        raise EnvironmentError("This application requires Windows")
    return info


def generate_test_hostname() -> str:
    return "workstation-01.kirschke.local"


def generate_test_fqdn() -> str:
    return "workstation-01.buero.prof-kirschke.de"


def generate_test_entra_id() -> str:
    return str(uuid.uuid4())


def generate_test_upn() -> str:
    return "user@prof-kirschke.de"


def generate_test_reason() -> str:
    return "Berechnung fur Projekt XYZ"


__all__ = [
    "RDPValidationError", "ALLOWED_RDP_OPTIONS", "FORBIDDEN_RDP_PATTERNS",
    "MAX_HOSTNAME_LENGTH", "MAX_UPN_LENGTH", "MAX_REASON_LENGTH",
    "COMMAND_EXPIRY_MINUTES", "AGENT_POLL_INTERVAL_SECONDS",
    "SESSION_SYNC_INTERVAL_SECONDS", "ALLOWED_RDP_FILE_EXTENSION",
    "RDPProfileValidator", "validate_entra_id", "validate_upn",
    "validate_reason", "validate_environment",
    "generate_test_hostname", "generate_test_fqdn",
    "generate_test_entra_id", "generate_test_upn", "generate_test_reason",
]
