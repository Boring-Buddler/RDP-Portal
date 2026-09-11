"""Self-contained GUI setup launcher with an embedded portable agent payload."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path


def bundle_paths(root: Path | None = None) -> tuple[Path, Path]:
    base = root or Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    script, payload = base / "Install-Agent.ps1", base / "payload"
    if not script.is_file() or not (payload / "Kirschke-RDP-Agent.exe").is_file():
        raise FileNotFoundError("Das Setup enthält keine vollständigen Agent-Dateien. Bitte das vollständige Setup neu erstellen.")
    return script, payload


def installer_command(script: Path, payload: Path, uninstall: bool = False) -> list[str]:
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    command = [str(powershell), "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
               "-File", str(script), "-SourceDirectory", str(payload)]
    if uninstall:
        command.append("-Uninstall")
    return command


def main() -> int:
    try:
        script, payload = bundle_paths()
        # Used by the build validation. Does not install, start or register anything.
        if "--check" in sys.argv:
            return 0
        result = subprocess.run(
            installer_command(script, payload, "--uninstall" in sys.argv),
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False,
        )
        if result.returncode:
            log_directory = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KirschkeRDPAgent"
            log_directory.mkdir(parents=True, exist_ok=True)
            log_file = log_directory / "setup-error.log"
            log_file.write_bytes(result.stdout + b"\n" + result.stderr)
            raise RuntimeError(f"Die Installation wurde nicht abgeschlossen.\nDetails: {log_file}")
        return 0
    except (OSError, RuntimeError) as exc:
        if "--check" not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None, str(exc), "Kirschke RDP-Agent – Setup", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
