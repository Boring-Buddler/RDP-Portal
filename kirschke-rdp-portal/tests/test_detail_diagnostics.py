"""Was die Detailseite zeigen muss, damit eine abgelehnte Abmeldung erklaerbar ist.

Beides war unsichtbar und beides entscheidet ueber die Abmeldung: die Agent-Version
(aeltere melden weder SID noch Konsolenkennzeichen) und die Art der Sitzung samt
gemeldetem RDP-Client (genau das vergleicht die Besitzpruefung des Agenten).
"""

from portal_app.models.workstation import Workstation
from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget as Detail
from shared.version import AGENT_VERSION

BACKSLASH = chr(92)
BASE = {"session_id": 2, "domain": "AzureAD", "username": "ChristianBecker",
        "session_state": "connected", "login_time": "2026-09-14T10:50:33+00:00"}


def test_a_console_session_is_named_as_such():
    line = Detail._session_line({**BASE, "is_console_session": True})

    assert "Konsole am Gerät" in line
    assert "AzureAD" + BACKSLASH + "ChristianBecker" in line
    assert "Verbunden" in line


def test_an_rdp_session_names_the_client_the_agent_compares_against():
    line = Detail._session_line(
        {**BASE, "is_console_session": False, "client_name": "NB12KI", "client_address": "192.168.2.74"}
    )

    assert "RDP von NB12KI" in line
    assert "192.168.2.74" in line


def test_an_rdp_session_without_a_client_says_so():
    """Ohne gemeldeten Client kann die Besitzpruefung nichts vergleichen."""
    line = Detail._session_line({**BASE, "is_console_session": False})

    assert "Client nicht gemeldet" in line


def test_an_old_agent_that_reports_no_kind_is_called_out():
    line = Detail._session_line(BASE)

    assert "Art unbekannt" in line


def test_a_current_agent_version_is_shown_plainly():
    ws = Workstation("W1", "NB05", "nb05", agent_version=AGENT_VERSION)

    assert Detail._agent_version_text(ws) == AGENT_VERSION


def test_an_outdated_agent_explains_what_it_costs():
    ws = Workstation("W1", "NB05", "nb05", agent_version="1.3.0")

    text = Detail._agent_version_text(ws)

    assert "veraltet" in text
    assert AGENT_VERSION in text
    assert "SID" in text and "Konsolensitzungen" in text


def test_a_missing_agent_version_is_not_mistaken_for_a_current_one():
    assert "veraltet" in Detail._agent_version_text(Workstation("W1", "NB05", "nb05"))


def test_a_newer_agent_is_not_flagged():
    ws = Workstation("W1", "NB05", "nb05", agent_version="99.0.0")

    assert Detail._agent_version_text(ws) == "99.0.0"
