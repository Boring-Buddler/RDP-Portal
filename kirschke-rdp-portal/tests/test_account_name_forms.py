"""Zwei Unicode-Schreibweisen desselben Namens, und die Auswahl, die nicht springt.

Windows liefert ``HendrikSchälikeAdmin`` in zwei Formen, die identisch aussehen
und es nicht sind: mit vorkomponiertem ``ä`` (U+00E4) und mit einfachem ``a``
plus kombinierendem Trema (U+0308). Welche ankommt, hängt davon ab, aus welcher
Schicht die Zeichenkette stammt.

Ohne Normalisierung konnte jemand sein eigenes Konto genau so eintragen, wie es
angezeigt wird, die Bestätigung "bereits eingetragen" bekommen -- und die eigene
Maschine blieb trotzdem als fremd belegt markiert.
"""

import unicodedata

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.ui.widgets.login_account_selector import LoginAccountSelector
from shared.identity import IdentityMatch, WindowsIdentity
from shared.login_accounts import validate_login_account

BACKSLASH = chr(92)
PRECOMPOSED = "AzureAD" + BACKSLASH + "HendrikSch" + chr(0xE4) + "likeAdmin"
DECOMPOSED = unicodedata.normalize("NFD", PRECOMPOSED)


def session(name):
    return {
        "session_id": 2,
        "full_username": name,
        "session_state": "connected",
        "login_time": "2026-09-15T07:56:54+00:00",
        "sid": "S-1-12-1-26",
    }


def test_the_two_spellings_really_are_different_strings():
    """Ohne das wäre der Rest dieser Datei sinnlos."""
    assert PRECOMPOSED != DECOMPOSED
    assert PRECOMPOSED.casefold() != DECOMPOSED.casefold()


def test_either_spelling_recognises_the_other():
    for claimed in (PRECOMPOSED, DECOMPOSED):
        for reported in (PRECOMPOSED, DECOMPOSED):
            match = WindowsIdentity.from_names(down_level=claimed).matches(
                WindowsIdentity.from_session(session(reported))
            )
            assert match is IdentityMatch.BY_NAME_UNVERIFIED, (claimed, reported)


def test_a_stored_account_name_is_normalised():
    assert validate_login_account(DECOMPOSED) == PRECOMPOSED


def test_the_session_counts_as_your_own_in_either_spelling():
    ws = Workstation("WS-2", "PC07", "PC07")
    ws.agent_sessions = [session(DECOMPOSED)]
    user = MockUser.create_user()
    user.own_accounts = [PRECOMPOSED]

    assert len(ws.owned_sessions(user.windows_accounts())) == 1


def test_a_sid_still_decides_when_both_sides_have_one():
    """Die Normalisierung betrifft nur Namen, nie die Form, die Windows prüft."""
    mine = WindowsIdentity.from_names(down_level=PRECOMPOSED, sid="S-1-12-1-1")
    theirs = WindowsIdentity.from_session(session(PRECOMPOSED))

    assert mine.matches(theirs) is IdentityMatch.NO


# --- Auswahl bleibt stehen ----------------------------------------------------

def test_a_stored_choice_survives_a_refresh(qtbot):
    """Sie stand nur in der Liste, solange sie gerade gemeldet wurde."""
    ws = Workstation("WS-2", "PC07", "PC07")
    ws.selected_login_account = "schaelike-adm@prof-kirschke.de"
    user = MockUser.create_user()
    selector = LoginAccountSelector(ws, user)
    qtbot.addWidget(selector)

    assert selector.combo.currentData() == "schaelike-adm@prof-kirschke.de"


def test_a_machine_without_a_choice_shows_the_default(qtbot):
    ws = Workstation("WS-2", "PC07", "PC07")
    selector = LoginAccountSelector(ws, MockUser.create_user())
    qtbot.addWidget(selector)

    assert selector.combo.currentData() == ""
    assert selector.combo.currentText().startswith("Standard")


def test_a_listed_choice_is_not_offered_twice(qtbot):
    ws = Workstation("WS-2", "PC07", "PC07", login_accounts=["BUERO" + BACKSLASH + "planung"])
    ws.selected_login_account = "BUERO" + BACKSLASH + "planung"
    selector = LoginAccountSelector(ws, MockUser.create_user())
    qtbot.addWidget(selector)

    entries = [
        selector.combo.itemData(index) for index in range(selector.combo.count())
    ]

    assert entries.count("BUERO" + BACKSLASH + "planung") == 1
