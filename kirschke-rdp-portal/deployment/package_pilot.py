"""Package freshly built client and agent setup for a manual pilot rollout."""

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    client = project / "dist/Kirschke-RDP-Portal"
    setup = project / "dist-agent/Kirschke-RDP-Agent-Setup.exe"
    guide = project / "docs/testbetrieb-kurz.md"
    if not (client / "Kirschke-RDP-Portal.exe").is_file() or not setup.is_file():
        raise SystemExit("Zuerst deployment/build_portable.cmd und deployment/build_agent.cmd ausführen.")
    destination = project / "dist/Kirschke-RDP-Testbetrieb.zip"
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(client.rglob("*")):
            if path.is_file():
                archive.write(path, Path("Client") / path.relative_to(client))
        archive.write(setup, setup.name)
        portal_setup = project / "dist/Kirschke-RDP-Portal-Setup.exe"
        archive.write(portal_setup, portal_setup.name)
        archive.writestr("Anleitung.txt", guide.read_text(encoding="utf-8").encode("utf-8-sig"))
        share_setup = (project / "deployment/setup_status_share.ps1").read_text(encoding="utf-8").encode("utf-8-sig")
        archive.writestr("Statusfreigabe-einrichten.ps1", share_setup)
        (project / "dist/Statusfreigabe-einrichten.ps1").write_bytes(share_setup)
        archive.write(project / "docs/code-review-testbetrieb.md", "Pruefbericht.md")
    with destination.open("rb") as package_file:
        digest = hashlib.file_digest(package_file, "sha256").hexdigest()
    destination.with_suffix(".zip.sha256").write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    print(f"Testpaket: {destination}")


if __name__ == "__main__":
    main()
