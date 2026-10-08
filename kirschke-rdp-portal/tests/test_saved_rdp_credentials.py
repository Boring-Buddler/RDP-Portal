"""Gespeicherte Windows-Anmeldedaten gegen das Konto aus "Anmelden als".

Hat Windows für ein RDP-Ziel Anmeldedaten gespeichert, meldet mstsc mit ihnen
an und übergeht das Konto aus der .rdp-Datei. Die Auswahl im Portal lief damit
ins Leere: Man wählte ein Konto und wurde unter einem anderen angemeldet.
"""

from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QMessageBox

from portal_app.services import rdp_diagnostics
from portal_app.services.rdp_diagnostics import credential_user_from_cmdkey
from portal_app.ui import main_window
from shared.schemas import RDPProfileSchema

SAVED = "PC07\\Kirschke"
CHOSEN = "PC07\\Becker"
ENTRA_UPN = "becker@prof-kirschke.de"
ENTRA_DOWN_LEVEL = "AzureAD\\" + ENTRA_UPN

GERMAN_LIST = f"""
Momentan gespeicherte Anmeldeinformationen:

    Ziel: Domain:target=TERMSRV/pc07
    Typ: Domänenkennwort
    Benutzer: {SAVED}
    Beständigkeit des lokalen Computers
"""

ENGLISH_LIST = f"""
Currently stored credentials:

    Target: Domain:target=TERMSRV/pc07
    Type: Domain Password
    User: {ENTRA_DOWN_LEVEL}
"""


def test_the_account_is_read_from_a_german_listing():
    assert credential_user_from_cmdkey(GERMAN_LIST, "pc07") == SAVED


def test_the_account_is_read_from_an_english_listing():
    assert credential_user_from_cmdkey(ENGLISH_LIST, "pc07") == ENTRA_DOWN_LEVEL


def test_an_entry_for_another_target_is_not_ours():
    assert credential_user_from_cmdkey(GERMAN_LIST, "pc08") is None


def test_no_entry_means_no_account():
    listing = "Momentan gespeicherte Anmeldeinformationen:\n\n* KEINE *\n"
    assert credential_user_from_cmdkey(listing, "pc07") is None


def profile(account: str | None) -> RDPProfileSchema:
    return RDPProfileSchema(hostname="pc07", display_name="PC07", username_hint=account)


@pytest.fixture
def dialog(qapp, monkeypatch):
    """Die Rückfrage, mit einem Klick auf den Knopf der gegebenen Rolle."""
    shown: list[QMessageBox] = []
    choice = {"role": None}

    def exec_(box):
        shown.append(box)
        return 0

    def clicked(box):
        for button in box.buttons():
            if box.buttonRole(button) == choice["role"]:
                return button
        return None

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    monkeypatch.setattr(QMessageBox, "clickedButton", clicked)
    clear = Mock(return_value=(True, "entfernt"))
    monkeypatch.setattr(rdp_diagnostics, "clear_saved_rdp_credentials", clear)

    def setup(saved: str | None, role):
        monkeypatch.setattr(rdp_diagnostics, "saved_rdp_credential_user", lambda target: saved)
        choice["role"] = role
        return shown, clear

    return setup


def test_a_matching_saved_account_starts_without_asking(dialog):
    shown, clear = dialog(SAVED, None)

    assert main_window._saved_credentials_allow_launch(None, profile("Kirschke"), "pc07")
    assert shown == []
    clear.assert_not_called()


def test_an_entra_account_in_both_spellings_is_the_same(dialog):
    shown, _clear = dialog(ENTRA_DOWN_LEVEL, None)

    assert main_window._saved_credentials_allow_launch(None, profile(ENTRA_UPN), "pc07")
    assert shown == []


def test_a_different_saved_account_is_removed_on_request(dialog):
    shown, clear = dialog(SAVED, QMessageBox.AcceptRole)

    assert main_window._saved_credentials_allow_launch(None, profile(CHOSEN), "pc07")
    assert len(shown) == 1
    assert SAVED in shown[0].text() and CHOSEN in shown[0].text()
    clear.assert_called_once_with("pc07")


def test_keeping_the_saved_account_starts_without_removing_it(dialog):
    _shown, clear = dialog(SAVED, QMessageBox.DestructiveRole)

    assert main_window._saved_credentials_allow_launch(None, profile(CHOSEN), "pc07")
    clear.assert_not_called()


def test_cancel_stops_the_start(dialog):
    _shown, clear = dialog(SAVED, QMessageBox.RejectRole)

    assert not main_window._saved_credentials_allow_launch(None, profile(CHOSEN), "pc07")
    clear.assert_not_called()


def test_a_failed_removal_stops_the_start(dialog, monkeypatch):
    """Sonst startete die Verbindung doch unter dem gespeicherten Konto."""
    _shown, clear = dialog(SAVED, QMessageBox.AcceptRole)
    clear.return_value = (False, "Zugriff verweigert")
    warning = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)

    assert not main_window._saved_credentials_allow_launch(None, profile(CHOSEN), "pc07")
    warning.assert_called_once()


def test_without_a_chosen_account_nothing_is_asked(dialog):
    """Ohne Kontonamen fragt Windows ohnehin; der gespeicherte Eintrag ist dann richtig."""
    shown, clear = dialog(SAVED, None)

    assert main_window._saved_credentials_allow_launch(None, profile(None), "pc07")
    assert shown == []
    clear.assert_not_called()


# --- Einträge für den ganzen Server -------------------------------------------
#
# Remote-Ettlingen: Der Freigabedialog hatte "Domain:target=192.168.2.66" mit
# 192.168.2.66\PortalLeser gespeichert. mstsc nahm das statt des gewählten
# Kontos, und jede Verbindung scheiterte mit "nicht zur Remoteanmeldung
# autorisiert" -- das Agent-Setup verbietet PortalLeser die Remoteanmeldung.

SERVER_LIST = """
Momentan gespeicherte Anmeldeinformationen:

    Ziel: Domain:target=TERMSRV/192.168.2.660
    Typ: Domänenkennwort
    Benutzer: Fremd
    Ziel: Domain:target=192.168.2.66
    Typ: Domänenkennwort
    Benutzer: 192.168.2.66\\PortalLeser
    Beständigkeit des lokalen Computers
"""


def test_a_server_entry_is_read_exactly():
    from portal_app.services.rdp_diagnostics import server_credential_user_from_cmdkey

    assert server_credential_user_from_cmdkey(SERVER_LIST, "192.168.2.66") == "192.168.2.66\\PortalLeser"
    assert server_credential_user_from_cmdkey(SERVER_LIST, "192.168.2.6") is None


def test_a_termsrv_entry_is_not_a_server_entry():
    from portal_app.services.rdp_diagnostics import server_credential_user_from_cmdkey

    assert server_credential_user_from_cmdkey(GERMAN_LIST, "pc07") is None


@pytest.fixture
def server_entry(dialog, monkeypatch):
    """Ein Server-Eintrag statt eines RDP-Eintrags, mit der gewählten Antwort."""
    clear_server = Mock(return_value=(True, "entfernt"))
    monkeypatch.setattr(rdp_diagnostics, "clear_saved_server_credentials", clear_server)

    def setup(saved: str | None, role):
        shown, clear = dialog(None, role)
        monkeypatch.setattr(rdp_diagnostics, "saved_server_credential_user", lambda target: saved)
        return shown, clear_server

    return setup


def test_the_reader_account_on_the_server_is_offered_for_removal_only(server_entry):
    shown, clear = server_entry("192.168.2.66\\PortalLeser", QMessageBox.AcceptRole)

    assert main_window._saved_credentials_allow_launch(None, profile(ENTRA_DOWN_LEVEL), "192.168.2.66")
    assert len(shown) == 1
    roles = {shown[0].buttonRole(button) for button in shown[0].buttons()}
    assert QMessageBox.DestructiveRole not in roles, "Behalten scheitert immer."
    clear.assert_called_once_with("192.168.2.66")


def test_the_reader_account_is_caught_even_without_a_chosen_account(server_entry):
    """Ohne Kontonamen nähme mstsc den Eintrag erst recht."""
    shown, clear = server_entry("192.168.2.66\\PortalLeser", QMessageBox.RejectRole)

    assert not main_window._saved_credentials_allow_launch(None, profile(None), "192.168.2.66")
    assert len(shown) == 1
    clear.assert_not_called()


def test_a_matching_server_entry_starts_without_asking(server_entry):
    shown, clear = server_entry(ENTRA_DOWN_LEVEL, None)

    assert main_window._saved_credentials_allow_launch(None, profile(ENTRA_UPN), "192.168.2.66")
    assert shown == []
    clear.assert_not_called()


def test_another_server_entry_may_be_kept(server_entry):
    shown, clear = server_entry(SAVED, QMessageBox.DestructiveRole)

    assert main_window._saved_credentials_allow_launch(None, profile(CHOSEN), "pc07")
    assert len(shown) == 1
    clear.assert_not_called()
