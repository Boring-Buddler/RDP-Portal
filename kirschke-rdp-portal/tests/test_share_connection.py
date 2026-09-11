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
    assert credentials[0]["TargetName"] == "Remote-Ettlingen"
    assert credentials[0]["CredentialBlob"] == "test-secret"
    assert credentials[0]["Type"] == win32cred.CRED_TYPE_DOMAIN_PASSWORD
    assert [p.name for p in tmp_path.iterdir()] == ["NB05.json"]


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
