"""Package freshly built client and agent into one archive for a manual rollout.

Everything needed on a target machine goes into a single zip, so unpacking it is
enough to have the current version of every piece.  Both delivery forms are
included on purpose: the setup executables for the normal case, and the plain
program folders for machines where an application control policy refuses to run
an unsigned installer.

The staleness check is the point of the ``--allow-stale`` switch existing at all.
A build that silently predates the sources once cost an afternoon of debugging a
bug that had already been fixed, so packaging refuses to put such a build into an
archive that claims to be current.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.version import AGENT_VERSION, PORTAL_VERSION  # noqa: E402

#: Source trees whose newest change decides whether a build is still current.
SOURCE_ROOTS = ("portal_app", "shared", "workstation_agent")

#: Documentation copied into the archive, so the rollout carries its own manual.
DOCUMENTATION = "docs"


def newest_source_change(project: Path) -> tuple[float, Path | None]:
    """Return the most recent modification time across the Python sources."""
    newest, newest_path = 0.0, None
    for root in SOURCE_ROOTS:
        for path in (project / root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            stamp = path.stat().st_mtime
            if stamp > newest:
                newest, newest_path = stamp, path
    return newest, newest_path


def stale_artifacts(project: Path, artifacts: list[Path]) -> list[str]:
    """Name every built artifact that is older than the sources it was built from."""
    newest, newest_path = newest_source_change(project)
    if newest_path is None:
        return []
    stale = []
    for artifact in artifacts:
        if artifact.stat().st_mtime < newest:
            built = datetime.fromtimestamp(artifact.stat().st_mtime)
            stale.append(
                f"{artifact.relative_to(project).as_posix()} "
                f"(gebaut {built:%d.%m.%Y %H:%M}, aber "
                f"{newest_path.relative_to(project).as_posix()} ist neuer)"
            )
    return stale


def version_report(project: Path, entries: list[tuple[Path, str]]) -> str:
    """Build the human-readable manifest that ships inside the archive."""
    lines = [
        "Kirschke RDP-Portal - Paketinhalt",
        "=" * 44,
        "",
        f"Portal-Version : {PORTAL_VERSION}",
        f"Agent-Version  : {AGENT_VERSION}",
        f"Paket erstellt : {datetime.now():%d.%m.%Y %H:%M}",
        "",
        "Enthaltene Programmstaende",
        "-" * 44,
    ]
    for source, name in entries:
        built = datetime.fromtimestamp(source.stat().st_mtime)
        size = source.stat().st_size / (1024 * 1024)
        lines.append(f"{name:38} {built:%d.%m.%Y %H:%M}  {size:7.1f} MB")
    lines += [
        "",
        "Installation",
        "-" * 44,
        "1. Auf JEDER Zielmaschine: Kirschke-RDP-Agent-Setup.exe ausfuehren.",
        "   Der Agent muss zur Portal-Version passen; aeltere Agenten melden",
        "   keine Windows-SID, dann faellt das Portal auf Namensvergleich zurueck.",
        "2. Auf den Arbeitsplaetzen: Kirschke-RDP-Portal-Setup.exe ausfuehren.",
        "",
        "Falls eine Anwendungssteuerungsrichtlinie das Setup blockiert, lassen",
        "sich die Ordner Client\\ und Agent\\ direkt verwenden; im Ordner Agent\\",
        "startet Install-Agent.cmd die Einrichtung ohne Setup-EXE.",
        "",
        "Dokumentation\\ enthaelt die ausfuehrlichen Anleitungen.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Auch dann packen, wenn ein Build aelter als die Quellen ist.",
    )
    options = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    client = project / "dist/Kirschke-RDP-Portal"
    agent = project / "dist-agent/Kirschke-RDP-Agent"
    portal_setup = project / "dist/Kirschke-RDP-Portal-Setup.exe"
    agent_setup = project / "dist-agent/Kirschke-RDP-Agent-Setup.exe"
    required = [
        client / "Kirschke-RDP-Portal.exe",
        agent / "Kirschke-RDP-Agent.exe",
        portal_setup,
        agent_setup,
    ]
    missing = [path for path in required if not path.is_file()]
    if missing:
        names = ", ".join(path.relative_to(project).as_posix() for path in missing)
        raise SystemExit(
            f"Fehlende Build-Artefakte: {names}\n"
            "Zuerst deployment/build_portable.cmd und deployment/build_agent.cmd ausfuehren."
        )

    stale = stale_artifacts(project, required)
    if stale and not options.allow_stale:
        raise SystemExit(
            "Veraltete Build-Artefakte - das Paket wuerde nicht den aktuellen Stand "
            "enthalten:\n  " + "\n  ".join(stale)
            + "\n\nNeu bauen, oder --allow-stale erzwingen."
        )

    destination = project / "dist/Kirschke-RDP-Testbetrieb.zip"
    report = version_report(
        project,
        [
            (portal_setup, "Kirschke-RDP-Portal-Setup.exe"),
            (agent_setup, "Kirschke-RDP-Agent-Setup.exe"),
            (client / "Kirschke-RDP-Portal.exe", "Client/Kirschke-RDP-Portal.exe"),
            (agent / "Kirschke-RDP-Agent.exe", "Agent/Kirschke-RDP-Agent.exe"),
        ],
    )
    share_setup = (project / "deployment/setup_status_share.ps1").read_text(
        encoding="utf-8"
    ).encode("utf-8-sig")

    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("VERSIONEN.txt", report.encode("utf-8-sig"))
        archive.write(portal_setup, portal_setup.name)
        archive.write(agent_setup, agent_setup.name)
        for source, prefix in ((client, "Client"), (agent, "Agent")):
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(prefix) / path.relative_to(source))
        for document in sorted((project / DOCUMENTATION).glob("*.md")):
            archive.write(document, Path("Dokumentation") / document.name)
        archive.writestr(
            "Anleitung.txt",
            (project / "docs/testbetrieb-kurz.md").read_text(encoding="utf-8").encode("utf-8-sig"),
        )
        archive.writestr("Statusfreigabe-einrichten.ps1", share_setup)
        archive.write(project / "docs/code-review-testbetrieb.md", "Pruefbericht.md")
    (project / "dist/Statusfreigabe-einrichten.ps1").write_bytes(share_setup)

    with destination.open("rb") as package_file:
        digest = hashlib.file_digest(package_file, "sha256").hexdigest()
    destination.with_suffix(".zip.sha256").write_text(
        f"{digest}  {destination.name}\n", encoding="ascii"
    )
    size = destination.stat().st_size / (1024 * 1024)
    print(f"Testpaket: {destination} ({size:.1f} MB)")
    print(f"Portal {PORTAL_VERSION} · Agent {AGENT_VERSION}")
    if stale:
        print("WARNUNG: veraltete Artefakte wurden auf Wunsch eingepackt.")


if __name__ == "__main__":
    main()
