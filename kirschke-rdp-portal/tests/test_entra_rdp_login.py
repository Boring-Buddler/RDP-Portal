"""The Entra spelling that decides whether a remote logon is authorized at all.

An Entra-joined target authorizes the SID that arrives at logon.  Which SID that
is depends on how the .rdp file names the account: with the Entra web sign-in
Windows wants the plain UPN, without it the account has to be named through the
``AzureAD\\`` pseudo-domain.  Get it wrong and the target answers "the user
account is not authorized for remote login" even though the account is a member
of Remotedesktopbenutzer -- because a different identity was presented.
"""

import tempfile

from portal_app.models.workstation import Workstation
from portal_app.rdp.generator import RDPFileGenerator
from shared.enums import ConnectionTargetMode

BACKSLASH = chr(92)
UPN = "becker@prof-kirschke.de"
QUALIFIED = "AzureAD" + BACKSLASH + UPN
ENTRA_SESSION = {
    "session_id": 2,
    "full_username": "AzureAD" + BACKSLASH + "ChristianBecker",
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
        username_hint="KIRSCHKE" + BACKSLASH + "becker",
    )

    assert rdp_lines(workstation)["username"] == "KIRSCHKE" + BACKSLASH + "becker"


def test_a_non_entra_machine_keeps_the_account_exactly_as_configured():
    workstation = Workstation("W1", "NB05", "nb05", username_hint=UPN)

    lines = rdp_lines(workstation)

    assert lines["enablerdsaadauth"] == "0"
    assert lines["username"] == UPN


# --- detecting the misconfiguration behind the live failure ------------------


def test_entra_sessions_on_a_machine_not_marked_as_entra_are_flagged():
    """The exact live case: the account is in the group, Windows still refuses."""
    workstation = Workstation("W1", "NB05", "nb05", username_hint=UPN)
    workstation.agent_sessions = [ENTRA_SESSION]

    warning = workstation.entra_spelling_warning()

    assert warning is not None
    assert QUALIFIED in warning
    assert "nicht autorisiert" in warning


def test_no_warning_once_the_machine_is_marked_as_an_entra_target():
    workstation = Workstation(
        "W1", "NB05", "nb05", username_hint=UPN, entra_sso_enabled=True
    )
    workstation.agent_sessions = [ENTRA_SESSION]

    assert workstation.entra_spelling_warning() is None


def test_no_warning_for_an_account_that_already_names_its_domain():
    workstation = Workstation(
        "W1", "NB05", "nb05", username_hint="KIRSCHKE" + BACKSLASH + "becker"
    )
    workstation.agent_sessions = [ENTRA_SESSION]

    assert workstation.entra_spelling_warning() is None


def test_no_warning_when_the_machine_reports_no_entra_sessions():
    workstation = Workstation("W1", "NB05", "nb05", username_hint=UPN)
    workstation.agent_sessions = [
        dict(ENTRA_SESSION, full_username="NB05" + BACKSLASH + "local", sid="S-1-5-21-1-2-3-4")
    ]

    assert workstation.reports_entra_sessions() is False
    assert workstation.entra_spelling_warning() is None


def test_the_warning_follows_the_account_picked_for_this_machine():
    workstation = Workstation("W1", "NB05", "nb05", username_hint=QUALIFIED)
    workstation.agent_sessions = [ENTRA_SESSION]

    assert workstation.entra_spelling_warning() is None

    workstation.selected_login_account = UPN

    assert workstation.entra_spelling_warning() is not None
