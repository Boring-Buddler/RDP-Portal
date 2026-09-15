"""Self-contained installer for the current user's portal application."""
import ctypes
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        script, payload = base / "Install-Portal.ps1", base / "payload"
        if not script.is_file() or not (payload / "Kirschke-RDP-Portal.exe").is_file():
            raise FileNotFoundError("Portal-Setup ist unvollständig.")
        if "--check" in sys.argv:
            return 0
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        # -ExecutionPolicy Bypass gilt nur fuer diesen einen Prozess und aendert
        # die Systemrichtlinie nicht. Ohne das scheitert das Setup auf jedem PC,
        # dessen Richtlinie das Laden von Skripten verbietet -- mit einer Meldung
        # ueber about_Execution_Policies, die wie ein Rechteproblem aussieht und
        # auch als Administrator unveraendert wiederkommt.
        args = [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA",
                "-File", str(script), "-SourceDirectory", str(payload)]
        if "--uninstall" in sys.argv:
            args.append("-Uninstall")
        result = subprocess.run(args, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))
        return 0
    except (OSError, RuntimeError) as exc:
        if "--check" not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None, str(exc), "Portal-Setup", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
