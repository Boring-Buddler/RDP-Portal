"""Explicit Entra account spelling and evidence-based authentication hints.

These tests check generated settings, not effective Windows logon rights.
"""

import tempfile

from portal_app.models.workstation import Workstation
from portal_app.rdp.generator import RDPFileGenerator
from shared.enums import ConnectionTargetMode

BACKSLASH = chr(92)
UPN = "mustermann@example.com"
QUALIFIED = "AzureAD" + BACKSLASH + UPN
ENTRA_SESSION = {
    "session_id": 2,
    "full_username": "AzureAD" + BACKSLASH + "ErikaMustermann",
    "session_state": "connected",
    "login_time": "2026-09-14T06:00:00+00:00",
    "sid": "S-1-12-1-1-2-3-4",
}


def rdp_lines(workstation: Workstation) -> dict[str, str]:
    """Read one generated .rdp file as ``{setting: value}``, skipping the header."""
    generator = RDPFileGenerator(tempfile.mkdtemp())
    path = generator.generate(workstation.get_rdp_profile())
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    settings = {}
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[1] in ("s", "i") and not line.startswith("#"):
            settings[parts[0]] = parts[2]
    return settings


def test_entra_hostname_target_uses_the_web_sign_in_and_the_plain_upn():
    workstation = Workstation(
        "W1", "NB05", "nb05", entra_sso_enabled=True, username_hint=UPN
    )

    lines = rdp_lines(workstation)

    assert lines["enablerdsaadauth"] == "1"
    assert lines["username"] == UPN


def test_entra_ip_target_cannot_use_the_web_sign_in_so_the_name_is_qualified():
    """Windows offers no Entra web sign-in for an IP, so the UPN alone would fail."""
    workstation = Workstation(
        "W1",
        "NB05",
        "nb05",
        ip_address="192.168.2.68",
        connection_target_mode=ConnectionTargetMode.IP_ADDRESS,
        entra_sso_enabled=True,
        username_hint=UPN,
    )

    lines = rdp_lines(workstation)

    assert lines["enablerdsaadauth"] == "0"
    assert lines["username"] == QUALIFIED


def test_an_already_qualified_account_survives_both_directions():
    workstation = Workstation(
        "W1", "NB05", "nb05", entra_sso_enabled=True, username_hint=QUALIFIED
    )

    assert rdp_lines(workstation)["username"] == UPN  # web sign-in wants the UPN

    workstation.connection_target_mode = ConnectionTargetMode.IP_ADDRESS
    workstation.ip_address = "192.168.2.68"

    assert rdp_lines(workstation)["username"] == QUALIFIED


def test_a_domain_account_is_never_rewritten():
    workstation = Workstation(
        "W1",
        "NB05",
        "nb05",
        entra_sso_enabled=True,
        username_hint="KIRSCHKE" + BACKSLASH + "mustermann",
    )

    assert rdp_lines(workstation)["username"] == "KIRSCHKE" + BACKSLASH + "mustermann"


def test_a_non_entra_machine_keeps_the_account_exactly_as_configured():
    workstation = Workstation("W1", "NB05", "nb05", username_hint=UPN)

    lines = rdp_lines(workstation)

    assert lines["enablerdsaadauth"] == "0"
    assert lines["username"] == UPN


# --- the live failure: plain UPN refused, same account fine over normal RDP --
#
# Remote-Ettlingen, IP target, no web sign-in: the portal passed
# "becker@prof-kirschke.de", Windows answered "nicht zur Remoteanmeldung
# autorisiert", and the same person got in over normal RDP. Before 0.9.1 this
# never showed, because Windows silently used saved credentials instead.


def test_entra_sessions_on_the_machine_qualify_a_plain_upn():
    workstation = Workstation("W1", "NB05", "nb05", username_hint=UPN)
    workstation.agent_sessions = [ENTRA_SESSION]

    assert rdp_lines(workstation)["username"] == QUALIFIED


def test_an_idle_entra_machine_is_recognised_from_agent_history():
    workstation = Workstation("W1", "NB05", "nb05", username_hint=UPN)
    workstation.agent_session_history = [dict(ENTRA_SESSION, event="Nicht mehr gemeldet")]

    assert rdp_lines(workstation)["username"] == QUALIFIED


def test_an_entra_portal_user_qualifies_a_plain_upn_without_machine_evidence():
    """A fresh or silent agent reports nothing -- the user's own logon still tells."""
    workstation = Workstation("W1", "NB05", "nb05", username_hint=UPN)

    profile = workstation.get_rdp_profile(entra_user=True)

    assert profile.effective_rdp_username() == QUALIFIED


def test_an_account_that_names_its_domain_is_left_alone():
    workstation = Workstation(
        "W1", "NB05", "nb05", username_hint="NB05" + BACKSLASH + "Codex"
    )
    workstation.agent_sessions = [ENTRA_SESSION]

    assert rdp_lines(workstation)["username"] == "NB05" + BACKSLASH + "Codex"


def test_without_any_entra_evidence_the_account_stays_as_configured():
    workstation = Workstation("W1", "NB05", "nb05", username_hint=UPN)
    workstation.agent_sessions = [
        dict(ENTRA_SESSION, full_username="NB05" + BACKSLASH + "local", sid="S-1-5-21-1-2-3-4")
    ]

    assert workstation.reports_entra_sessions() is False
    assert rdp_lines(workstation)["username"] == UPN


def test_the_choice_from_the_dropdown_is_what_gets_qualified():
    workstation = Workstation("W1", "NB05", "nb05", username_hint="NB05" + BACKSLASH + "Codex")
    workstation.agent_sessions = [ENTRA_SESSION]
    workstation.selected_login_account = UPN

    assert rdp_lines(workstation)["username"] == QUALIFIED
