import pytest
import pywintypes
import win32cred
import win32wnet
from PySide6.QtWidgets import QDialog

from portal_app.services import share_connection
from portal_app.ui.widgets.share_setup_dialog import ShareSetupDialog


@pytest.mark.parametrize("path", [r"C:\Status", r"\\?\C:\Status", r"\\.\pipe\x", r"\\host", r"\\host\share\..\other", r"\\*\share"])
def test_invalid_network_paths_are_rejected(path):
    with pytest.raises(ValueError):
        share_connection.parse_share_path(path)


def test_connection_checks_files_and_saves_only_to_windows(tmp_path, monkeypatch):
    (tmp_path / "NB05.json").write_text("{}")
    monkeypatch.setattr(share_connection, "Path", lambda value: tmp_path)
    connections, credentials = [], []
    monkeypatch.setattr(win32wnet, "WNetAddConnection2", lambda *a: connections.append(a))
    monkeypatch.setattr(win32cred, "CredWrite", lambda *a: credentials.append(a[0]))
    path, message = share_connection.connect_share(r"\\Remote-Ettlingen\RDP-Status", "PortalLeser", "test-secret", True)
    assert path == r"\\Remote-Ettlingen\RDP-Status"
    assert "1 JSON" in message
    assert connections[0][2] == r"Remote-Ettlingen\PortalLeser"
    assert credentials[0]["TargetName"] == "KirschkeRDPPortal:Freigabe:remote-ettlingen"
    assert credentials[0]["CredentialBlob"] == "test-secret"
    assert credentials[0]["Type"] == win32cred.CRED_TYPE_GENERIC
    assert [p.name for p in tmp_path.iterdir()] == ["NB05.json"]


def test_remembered_share_account_is_never_a_server_logon(monkeypatch):
    """Ein Eintrag für den ganzen Server lenkte Remotedesktop auf PortalLeser um.

    Windows nimmt ``Domain:target=<Server>`` für jede Anmeldung dort, auch für
    mstsc -- und PortalLeser darf sich nie per RDP anmelden. Gemerkt wird das
    Freigabekonto deshalb unter einem eigenen Namen, den Windows nie von selbst
    benutzt.
    """
    payload = share_connection.credential_payload("192.168.2.66", "PortalLeser", "x")

    assert payload["Type"] == win32cred.CRED_TYPE_GENERIC
    assert payload["TargetName"] != "192.168.2.66"
    assert not payload["TargetName"].upper().startswith("TERMSRV/")


def test_the_remembered_account_is_tried_for_its_server(monkeypatch):
    attempts = []
    monkeypatch.setattr("portal_app.services.reader_account.bundled_credentials", lambda: None)
    monkeypatch.setattr(share_connection, "stored_reader_credentials", lambda: None)
    monkeypatch.setattr(
        share_connection,
        "stored_share_credentials",
        lambda server: ("PortalLeser", "eigen") if server == "192.168.2.66" else None,
    )
    monkeypatch.setattr(
        share_connection,
        "ensure_share_connection",
        lambda path, username="", password="": attempts.append((username, password)) or (True, "ok"),
    )

    assert share_connection.connect_status_share(r"\\192.168.2.66\RDP-Protokoll")[0]
    assert attempts == [("PortalLeser", "eigen")]


def test_a_switched_off_server_costs_one_attempt_not_three(monkeypatch):
    """Nur eine abgelehnte Anmeldung ist ein Grund, das nächste Konto zu probieren."""
    attempts = []
    monkeypatch.setattr(
        "portal_app.services.reader_account.bundled_credentials", lambda: ("PortalLeser", "a")
    )
    monkeypatch.setattr(share_connection, "stored_reader_credentials", lambda: ("PortalLeser", "b"))
    monkeypatch.setattr(share_connection, "stored_share_credentials", lambda server: ("Inventar", "c"))

    def unreachable(path, username="", password=""):
        attempts.append(username)
        return False, r"\\NB99\RDP-Status: Windows-Fehler 53."

    monkeypatch.setattr(share_connection, "ensure_share_connection", unreachable)

    assert not share_connection.connect_status_share(r"\\NB99\RDP-Status")[0]
    assert attempts == ["PortalLeser"]


def test_a_refused_password_moves_on_to_the_next_account(monkeypatch):
    attempts = []
    monkeypatch.setattr(
        "portal_app.services.reader_account.bundled_credentials", lambda: ("PortalLeser", "alt")
    )
    monkeypatch.setattr(share_connection, "stored_reader_credentials", lambda: None)
    monkeypatch.setattr(share_connection, "stored_share_credentials", lambda server: ("Inventar", "neu"))

    def refuse_first(path, username="", password=""):
        attempts.append(username)
        if password == "alt":
            return False, r"\\NB05\RDP-Status: Windows-Fehler 1326."
        return True, "verbunden"

    monkeypatch.setattr(share_connection, "ensure_share_connection", refuse_first)

    assert share_connection.connect_status_share(r"\\NB05\RDP-Status")[0]
    assert attempts == ["PortalLeser", "Inventar"]


def _legacy_entry(target, user, comment=share_connection.LEGACY_SERVER_CREDENTIAL_COMMENT):
    return {
        "Type": win32cred.CRED_TYPE_DOMAIN_PASSWORD,
        "TargetName": target,
        "UserName": user,
        "Comment": comment,
    }


def test_only_the_portals_own_reader_entries_are_retired(monkeypatch):
    entries = [
        _legacy_entry("192.168.2.66", r"192.168.2.66\PortalLeser"),
        # Selbst gespeichert, nicht vom Portal: bleibt.
        _legacy_entry("PC12", r"PC12\PortalLeser", comment=None),
        # Vom Portal, aber ein anderes Konto: dessen Kennwort hätte niemand mehr.
        _legacy_entry("NAS", r"NAS\Inventar"),
        {"Type": win32cred.CRED_TYPE_GENERIC, "TargetName": "x", "UserName": "PortalLeser",
         "Comment": share_connection.LEGACY_SERVER_CREDENTIAL_COMMENT},
    ]
    deleted = []
    monkeypatch.setattr(share_connection, "load_reader_credentials", lambda: ("PortalLeser", "pw"))
    monkeypatch.setattr(win32cred, "CredEnumerate", lambda *a: entries)
    monkeypatch.setattr(win32cred, "CredDelete", lambda target, kind, flags: deleted.append((target, kind)))

    assert share_connection.retire_legacy_server_credentials() == ["192.168.2.66"]
    assert deleted == [("192.168.2.66", win32cred.CRED_TYPE_DOMAIN_PASSWORD)]


def test_nothing_is_retired_without_a_reader_account_to_replace_it(monkeypatch):
    monkeypatch.setattr(share_connection, "load_reader_credentials", lambda: None)
    monkeypatch.setattr(
        win32cred, "CredEnumerate", lambda *a: [_legacy_entry("192.168.2.66", r"192.168.2.66\PortalLeser")]
    )
    monkeypatch.setattr(win32cred, "CredDelete", lambda *a: pytest.fail("must not delete"))

    assert share_connection.retire_legacy_server_credentials() == []


def test_connection_without_remember_never_writes_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(share_connection, "Path", lambda value: tmp_path)
    monkeypatch.setattr(win32wnet, "WNetAddConnection2", lambda *a: None)
    def forbidden(*args):
        pytest.fail("Credentials must not be persisted")
    monkeypatch.setattr(win32cred, "CredWrite", forbidden)
    share_connection.connect_share(r"\\host\share", "reader", "secret", False)


def test_conflict_does_not_save_credentials_or_expose_password(monkeypatch):
    def conflict(*args):
        raise pywintypes.error(1219, "WNetAddConnection2", "test-secret")
    monkeypatch.setattr(win32wnet, "WNetAddConnection2", conflict)
    monkeypatch.setattr(win32cred, "CredWrite", lambda *a: pytest.fail("Must not save after failure"))
    with pytest.raises(ValueError, match="anderen Konto") as exc:
        share_connection.connect_share(r"\\host\share", "reader", "test-secret", True)
    assert "test-secret" not in str(exc.value)


def test_dialog_connects_in_background_and_clears_password(qtbot, monkeypatch):
    monkeypatch.setattr("portal_app.ui.widgets.share_setup_dialog.connect_share", lambda *a: (a[0], "OK"))
    dialog = ShareSetupDialog("")
    qtbot.addWidget(dialog)
    dialog.password.setText("test-secret")
    dialog.connect_button.click()
    assert dialog.password.text() == ""
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)
    assert dialog.connected_path == r"\\Remote-Ettlingen\RDP-Status"
    assert dialog.worker.arguments is None


def test_dialog_uses_machine_suggestion_instead_of_unrelated_legacy_path(qtbot):
    dialog = ShareSetupDialog(
        "",
        suggested_path=r"\\NB12KI\RDP-Status",
        suggested_username=r"NB12KI\PortalLeser",
        workstation_name="NB12KI",
    )
    qtbot.addWidget(dialog)
    assert dialog.path.text() == r"\\NB12KI\RDP-Status"
    assert dialog.username.text() == r"NB12KI\PortalLeser"


def test_unreadable_status_folder_does_not_store_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(share_connection, "Path", lambda value: tmp_path / "absent")
    monkeypatch.setattr(win32wnet, "WNetAddConnection2", lambda *a: None)
    monkeypatch.setattr(win32cred, "CredWrite", lambda *a: pytest.fail("Must not save after access failure"))
    with pytest.raises(ValueError, match="nicht lesbar"):
        share_connection.connect_share(r"\\host\share", "reader", "secret", True)


def test_credential_payload_passes_real_pywin32_marshalling_without_storing():
    payload = share_connection.credential_payload("rdp-portal-invalid-probe", "probe", "test-ä-secret")
    # Type 0 is invalid: Windows must reject this without storing anything.
    # A TypeError here would mean our Python argument shape is still wrong.
    payload["Type"] = 0
    with pytest.raises(pywintypes.error) as exc:
        win32cred.CredWrite(payload, 0)
    assert exc.value.winerror == 87


@pytest.mark.parametrize("error", [TypeError("test-secret"), pywintypes.error(1312, "CredWrite", "test-secret")])
def test_save_error_distinguishes_connected_share_and_hides_password(tmp_path, monkeypatch, error):
    monkeypatch.setattr(share_connection, "Path", lambda value: tmp_path)
    monkeypatch.setattr(win32wnet, "WNetAddConnection2", lambda *a: None)
    def fail(*args):
        raise error
    monkeypatch.setattr(win32cred, "CredWrite", fail)
    with pytest.raises(ValueError, match="Freigabe erreichbar") as exc:
        share_connection.connect_share(r"\\host\share", "reader", "test-secret", True)
    assert "test-secret" not in str(exc.value)


def test_pyinstaller_can_see_the_module_credread_loads_behind_its_back():
    """CredRead/CredEnumerate importieren win32timezone erst zur Laufzeit.

    PyInstaller packt nur, was es als Import im Quelltext findet. Ohne den
    ausdrücklichen Import fehlte das Modul in der EXE, und 0.9.4 brach beim
    Start mit "No module named 'win32timezone'" ab.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(share_connection))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "win32timezone" in imported


def test_a_failing_cleanup_never_stops_the_portal_from_starting(monkeypatch):
    from types import SimpleNamespace

    from portal_app.ui.main_window import MainWindow

    def broken():
        raise ModuleNotFoundError("No module named 'win32timezone'")

    def unreachable(path):
        raise ModuleNotFoundError("No module named 'win32timezone'")

    monkeypatch.setattr(share_connection, "retire_legacy_server_credentials", broken)
    monkeypatch.setattr(share_connection, "connect_status_share", unreachable)
    window = SimpleNamespace(
        store=SimpleNamespace(inventory_directory=r"\NAS\RDP-Portal", event_log_directory=None)
    )

    MainWindow._prepare_shared_folders(window)

    assert window._retired_credential_servers == ()
