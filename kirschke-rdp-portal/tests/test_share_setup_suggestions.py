r"""Der Kontovorschlag im Fallback-Dialog muss zum Pfad passen.

``PortalLeser`` ist ein *lokales* Konto auf jedem Zielrechner. Für
``\\NB05\RDP-Status`` meldet sich nur ``NB05\PortalLeser`` dort an.

Der Fehler: Der Pfad kam aus dem gespeicherten Wert der Maschine, der
Kontovorschlag aber immer aus deren Namen. Wer für NB13KI einen Ordner auf NB05
hinterlegt hatte, bekam ``\\NB05\RDP-Status`` neben ``NB13KI\PortalLeser``
angeboten -- ein Paar, das nicht funktionieren kann.
"""

import pytest

from portal_app.ui.widgets.share_setup_dialog import ShareSetupDialog, account_on_server

BACKSLASH = "\\"
NB05_SHARE = BACKSLASH * 2 + "NB05" + BACKSLASH + "RDP-Status"
NB13_SHARE = BACKSLASH * 2 + "NB13KI" + BACKSLASH + "RDP-Status"
NB13_ACCOUNT = "NB13KI" + BACKSLASH + "PortalLeser"


@pytest.fixture
def dialog(qtbot):
    def build(current_path: str = "", **kwargs):
        widget = ShareSetupDialog(
            current_path,
            suggested_path=NB13_SHARE,
            suggested_username=NB13_ACCOUNT,
            workstation_name="NB13KI",
            **kwargs,
        )
        qtbot.addWidget(widget)
        return widget

    return build


# --- Die Ableitung selbst ----------------------------------------------------


def test_the_account_follows_the_server_in_the_path():
    assert account_on_server(NB05_SHARE, NB13_ACCOUNT) == "NB05" + BACKSLASH + "PortalLeser"


def test_an_ip_address_works_as_a_server_too():
    share = BACKSLASH * 2 + "192.168.2.10" + BACKSLASH + "RDP-Status"

    assert account_on_server(share, NB13_ACCOUNT) == "192.168.2.10" + BACKSLASH + "PortalLeser"


def test_a_renamed_reader_account_is_kept():
    """Wer sein Lesekonto anders genannt hat, tippt es nicht bei jedem Pfad neu."""
    custom = "NB13KI" + BACKSLASH + "MeinLeser"

    assert account_on_server(NB05_SHARE, custom) == "NB05" + BACKSLASH + "MeinLeser"


@pytest.mark.parametrize("path", ["", "C:/lokal", BACKSLASH * 2, "kein-pfad"])
def test_without_a_usable_server_the_suggestion_stands(path):
    assert account_on_server(path, NB13_ACCOUNT) == NB13_ACCOUNT


# --- Im Dialog ---------------------------------------------------------------


def test_a_stored_path_brings_its_own_account_along(dialog):
    """Der gemeldete Fehler: Pfad von NB05, Konto von NB13KI."""
    widget = dialog(NB05_SHARE)

    assert widget.path.text() == NB05_SHARE
    assert widget.username.text() == "NB05" + BACKSLASH + "PortalLeser"


def test_without_a_stored_path_the_machine_itself_is_suggested(dialog):
    widget = dialog()

    assert widget.path.text() == NB13_SHARE
    assert widget.username.text() == NB13_ACCOUNT


def test_editing_the_path_carries_the_account_along(dialog):
    widget = dialog()

    widget.path.setText(NB05_SHARE)

    assert widget.username.text() == "NB05" + BACKSLASH + "PortalLeser"


def test_a_hand_typed_account_is_never_overwritten(dialog):
    """Eine eingetippte Eingabe zu ändern wäre schlimmer als ein falscher Vorschlag."""
    widget = dialog()
    widget.username.setText("DOMAENE" + BACKSLASH + "sonderkonto")
    widget.username.textEdited.emit(widget.username.text())

    widget.path.setText(NB05_SHARE)

    assert widget.username.text() == "DOMAENE" + BACKSLASH + "sonderkonto"


# --- Hinweis auf einen fremden Server ----------------------------------------


def test_a_folder_on_another_machine_is_pointed_out(dialog):
    widget = dialog(NB05_SHARE)

    assert "NB05" in widget.server_note.text()
    assert "NB13KI" in widget.server_note.text()


def test_the_machines_own_folder_needs_no_note(dialog):
    widget = dialog(NB13_SHARE)

    assert widget.server_note.text() == ""


def test_the_note_does_not_call_it_an_error(dialog):
    """Mehrere Agenten dürfen sich eine Freigabe teilen -- das ist kein Fehler."""
    widget = dialog(NB05_SHARE)

    text = widget.server_note.text()
    assert "in Ordnung" in text
    assert "Fehler" not in text


def test_the_note_appears_and_disappears_with_the_path(dialog):
    widget = dialog()
    assert widget.server_note.text() == ""

    widget.path.setText(NB05_SHARE)
    assert widget.server_note.text()

    widget.path.setText(NB13_SHARE)
    assert widget.server_note.text() == ""
