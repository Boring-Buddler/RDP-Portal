"""Die Installationsfenster nennen die Version, die sie wirklich installieren.

Im Portal-Setup stand die Nummer fest verdrahtet im Quelltext und war irgendwann
drei Versionen alt -- sie behauptete "Portal 0.2.12 für diesen Benutzer
installieren", während 0.5.x im Paket lag. Dieselbe feste Nummer stand in der
Windows-Programmliste.

Die Nummer kommt jetzt an einer Stelle her: aus shared/version.py, beim Bauen in
das PowerShell-Skript eingesetzt und im Agent-Installer direkt importiert.
"""

import re
from pathlib import Path

from shared.version import AGENT_VERSION, PORTAL_VERSION

DEPLOYMENT = Path(__file__).resolve().parent.parent / "deployment"
INSTALL_PORTAL = DEPLOYMENT / "install_portal.ps1"
BUILD_PORTABLE = DEPLOYMENT / "build_portable.ps1"
AGENT_INSTALLER = DEPLOYMENT / "agent_installer.py"

#: Was im Quelltext steht, bevor der Build die echte Nummer einsetzt.
PLACEHOLDER = "0.0.0-dev"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- Portal-Setup -------------------------------------------------------------

def test_the_portal_setup_carries_no_hardcoded_version():
    """Genau so ist die Nummer drei Versionen lang stehen geblieben."""
    text = source(INSTALL_PORTAL).replace(PLACEHOLDER, "")
    found = re.findall(r"\b\d+\.\d+\.\d+\b", text)

    assert found == [], found


def test_the_setup_window_shows_the_version():
    text = source(INSTALL_PORTAL)

    assert "$form.Text" in text
    for line in text.splitlines():
        if line.strip().startswith(("$form.Text", "$label.Text")):
            assert "$portalVersion" in line, line


def test_the_build_replaces_the_placeholder():
    build = source(BUILD_PORTABLE)

    assert PLACEHOLDER in build
    assert "PORTAL_VERSION" in build
    assert "shared" in build and "version.py" in build


def test_the_placeholder_is_a_single_assignment():
    """Der Build ersetzt genau diese eine Zeile; zwei davon würden auseinanderlaufen."""
    assignments = [
        line for line in source(INSTALL_PORTAL).splitlines()
        if line.strip().startswith("$portalVersion =")
    ]

    assert len(assignments) == 1
    assert PLACEHOLDER in assignments[0]


# --- Agent-Setup --------------------------------------------------------------

def test_the_agent_setup_window_shows_the_version():
    text = source(AGENT_INSTALLER)

    assert 'self.root.title(f"Kirschke RDP-Agent {AGENT_VERSION} installieren")' in text
    assert 'f"RDP-Agent {AGENT_VERSION} auf diesem Ziel-PC einrichten"' in text


def test_the_agent_setup_takes_the_version_from_the_one_place():
    assert "from shared.version import AGENT_VERSION" in source(AGENT_INSTALLER)


# --- Die eine Quelle ----------------------------------------------------------

def test_both_versions_are_readable_and_shaped_like_versions():
    for version in (PORTAL_VERSION, AGENT_VERSION):
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), version


# --- Kodierung ----------------------------------------------------------------

def test_the_installer_scripts_carry_a_byte_order_mark():
    """Ohne BOM liest Windows PowerShell 5.1 die Datei als ANSI.

    Ein Gedankenstrich zerfaellt dann in drei Zeichen, von denen eines als
    Anfuehrungszeichen gelesen wird -- das Skript bricht mit "Die Zeichenfolge hat
    kein Abschlusszeichen" ab. Der Build schreibt die ausgelieferte Kopie deshalb
    mit BOM; die Quelldatei muss dasselbe tun, sonst laesst sie sich nicht direkt
    ausfuehren und der Unterschied faellt erst beim Kollegen auf.
    """
    for script in sorted(DEPLOYMENT.glob("*.ps1")):
        if script.read_bytes()[:3] != b"" + bytes([0xEF, 0xBB, 0xBF]) and any(
            ord(character) > 127 for character in source(script)
        ):
            raise AssertionError(f"{script.name} enthält Sonderzeichen ohne BOM")
