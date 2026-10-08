import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import win32com.client
import win32security

from deployment import agent_installer


def test_native_installer_writes_config_and_registers_system_task(tmp_path, monkeypatch):
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / agent_installer.AGENT_EXE).write_bytes(b"agent")
    status = tmp_path / "status"
    paths = agent_installer.SetupPaths(
        tmp_path / "program-files" / agent_installer.INSTALL_FOLDER,
        tmp_path / "program-data" / agent_installer.INSTALL_FOLDER,
        tmp_path / "program-data" / agent_installer.INSTALL_FOLDER / "agent-config.json",
    )
    registered = {}
    monkeypatch.setattr(agent_installer, "is_administrator", lambda: True)
    monkeypatch.setattr(agent_installer, "setup_paths", lambda: paths)
    monkeypatch.setattr(agent_installer, "_delete_task", lambda: False)
    monkeypatch.setattr(
        agent_installer, "_secure_data_directory", lambda directory: directory.mkdir(parents=True)
    )
    monkeypatch.setattr(agent_installer, "_copy_setup_executable", lambda destination: None)
    monkeypatch.setattr(agent_installer, "_write_uninstall_registration", lambda selected: None)
    monkeypatch.setattr(
        agent_installer,
        "_register_task",
        lambda executable, config, workstation_id: registered.update(
            executable=executable, config=config, workstation_id=workstation_id
        ),
    )

    result = agent_installer.install_agent(
        payload, "WS-004", str(status), 30, configure_share=False, launch_now=False
    )

    assert result == paths
    config = json.loads(paths.config.read_text(encoding="utf-8"))
    assert config["workstation_id"] == "WS-004"
    # Read from the one place versions are defined, so a release bump does not
    # have to be repeated here -- that is what shared.version exists to prevent.
    from shared.version import AGENT_VERSION

    assert config["agent_version"] == AGENT_VERSION
    assert config["live_status_reader"] == "PortalLeser"
    assert registered == {
        "executable": paths.install / agent_installer.AGENT_EXE,
        "config": paths.config,
        "workstation_id": "WS-004",
    }


def test_native_task_is_system_startup_task_without_powershell():
    xml = agent_installer._task_xml(
        Path(r"C:\Program Files\KirschkeRDPAgent\Kirschke-RDP-Agent.exe"),
        Path(r"C:\ProgramData\KirschkeRDPAgent\agent-config.json"),
        "WS-004",
    )

    assert "<UserId>S-1-5-18</UserId>" in xml
    assert "<BootTrigger>" in xml
    assert "Kirschke-RDP-Agent.exe" in xml
    assert "powershell" not in xml.casefold()


def test_native_task_xml_is_accepted_by_windows_task_scheduler():
    service = win32com.client.Dispatch("Schedule.Service")
    service.Connect()
    definition = service.NewTask(0)
    definition.XmlText = agent_installer._task_xml(
        Path(r"C:\Program Files\KirschkeRDPAgent\Kirschke-RDP-Agent.exe"),
        Path(r"C:\ProgramData\KirschkeRDPAgent\agent-config.json"),
        "WS-004",
    )

    assert definition.Principal.UserId == "SYSTEM"
    assert definition.Actions.Item(1).Path.endswith(agent_installer.AGENT_EXE)


def test_native_uninstall_removes_only_exact_agent_directory(tmp_path, monkeypatch):
    paths = agent_installer.SetupPaths(
        tmp_path / agent_installer.INSTALL_FOLDER,
        tmp_path / "data" / agent_installer.INSTALL_FOLDER,
        tmp_path / "data" / agent_installer.INSTALL_FOLDER / "agent-config.json",
    )
    paths.install.mkdir(parents=True)
    paths.data.mkdir(parents=True)
    (paths.install / agent_installer.AGENT_EXE).write_bytes(b"agent")
    paths.config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(agent_installer, "is_administrator", lambda: True)
    monkeypatch.setattr(agent_installer, "setup_paths", lambda: paths)
    monkeypatch.setattr(agent_installer, "_delete_task", lambda: True)
    monkeypatch.setattr(agent_installer, "_delete_uninstall_registration", lambda: None)

    assert agent_installer.uninstall_agent() is True
    assert not paths.install.exists()
    assert not paths.config.exists()
    assert paths.data.exists()


def test_status_share_creates_reader_and_read_only_share(tmp_path, monkeypatch):
    status = tmp_path / "agenten-status"
    credential = "-".join(("Test", "only", "Password", "123!"))
    calls = {}
    monkeypatch.setattr(agent_installer, "_assert_local_share_path", lambda path: None)
    monkeypatch.setattr(agent_installer, "_local_user_exists", lambda name: False)
    monkeypatch.setattr(agent_installer, "_share_info", lambda name: None)
    monkeypatch.setattr(
        agent_installer.win32security, "GetNamedSecurityInfo", lambda *args: object()
    )
    monkeypatch.setattr(
        agent_installer.win32net,
        "NetUserAdd",
        lambda server, level, info: calls.update(user=info),
    )
    monkeypatch.setattr(
        agent_installer.win32security,
        "LookupAccountName",
        lambda server, name: ("reader-sid", None, None),
    )
    monkeypatch.setattr(
        agent_installer,
        "_share_directory_acl",
        lambda path, sid: calls.update(directory_acl=(path, sid)),
    )
    monkeypatch.setattr(
        agent_installer,
        "_share_security_descriptor",
        lambda sid: "share-security",
    )
    monkeypatch.setattr(
        agent_installer.win32net,
        "NetShareAdd",
        lambda server, level, info: calls.update(share=(level, info)),
    )
    monkeypatch.setattr(
        agent_installer.win32security, "LsaOpenPolicy", lambda server, access: "policy"
    )
    monkeypatch.setattr(
        agent_installer.win32security,
        "LsaAddAccountRights",
        lambda policy, sid, rights: calls.update(denied_rights=(sid, tuple(rights))),
    )
    monkeypatch.setattr(
        agent_installer.win32security, "LsaClose", lambda policy: calls.update(policy_closed=True)
    )

    account, created = agent_installer.ensure_status_share(
        status, credential, credential
    )

    assert created is True
    assert account.endswith(r"\PortalLeser")
    assert calls["user"]["name"] == "PortalLeser"
    assert calls["user"]["password"] == credential
    assert calls["user"]["flags"] & agent_installer.win32netcon.UF_DONT_EXPIRE_PASSWD
    assert calls["directory_acl"] == (status, "reader-sid")
    assert calls["share"][0] == 502
    assert calls["share"][1]["netname"] == "RDP-Status"
    assert calls["share"][1]["security_descriptor"] == "share-security"
    # The share account must not be able to sign in; it only needs SMB access.
    denied_sid, denied_rights = calls["denied_rights"]
    assert denied_sid == "reader-sid"
    assert set(denied_rights) == {
        "SeDenyInteractiveLogonRight",
        "SeDenyRemoteInteractiveLogonRight",
        "SeDenyBatchLogonRight",
        "SeDenyServiceLogonRight",
    }
    assert calls["policy_closed"] is True


def test_status_share_reuses_complete_existing_setup_without_password(tmp_path, monkeypatch):
    status = tmp_path / "agenten-status"
    monkeypatch.setattr(agent_installer, "_assert_local_share_path", lambda path: None)
    monkeypatch.setattr(agent_installer, "_local_user_exists", lambda name: True)
    monkeypatch.setattr(agent_installer, "_share_info", lambda name: {"path": str(status)})

    account, created = agent_installer.ensure_status_share(status, "", "")

    assert created is False
    assert account.endswith(r"\PortalLeser")


def test_status_share_rejects_partial_existing_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_installer, "_assert_local_share_path", lambda path: None)
    monkeypatch.setattr(agent_installer, "_local_user_exists", lambda name: True)
    monkeypatch.setattr(agent_installer, "_share_info", lambda name: None)

    with pytest.raises(RuntimeError, match="teilweise vorhanden"):
        agent_installer.ensure_status_share(tmp_path / "status", "", "")


def test_status_share_requires_matching_new_password(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_installer, "_assert_local_share_path", lambda path: None)
    monkeypatch.setattr(agent_installer, "_local_user_exists", lambda name: False)
    monkeypatch.setattr(agent_installer, "_share_info", lambda name: None)

    with pytest.raises(ValueError, match="stimmen nicht überein"):
        agent_installer.ensure_status_share(tmp_path / "status", "one", "two")


def test_share_acl_gives_reader_no_write_access():
    reader_sid = win32security.ConvertStringSidToSid("S-1-5-21-1-2-3-1001")
    descriptor = agent_installer._share_security_descriptor(reader_sid)
    acl = descriptor.GetSecurityDescriptorDacl()
    reader_aces = [
        acl.GetAce(index)
        for index in range(acl.GetAceCount())
        if acl.GetAce(index)[2] == reader_sid
    ]

    assert len(reader_aces) == 1
    assert reader_aces[0][1] & agent_installer.ntsecuritycon.FILE_GENERIC_READ
    assert not reader_aces[0][1] & agent_installer.ntsecuritycon.FILE_WRITE_DATA


# --- Freigabe für das gemeinsame Protokoll -----------------------------------
#
# Anlass: Installiert jeder das Portal über sein Setup, liegt der gemeinsame
# Stand in seinem eigenen Profil, und jeder führt sein eigenes Inventar. Das
# Ereignisprotokoll ist der Teil, den man trotzdem zusammen sehen will -- dafür
# braucht es genau einen Ordner, in den alle Portale schreiben dürfen.


def _patch_share_calls(monkeypatch, calls, *, user_exists, share):
    monkeypatch.setattr(agent_installer, "_assert_local_share_path", lambda path: None)
    monkeypatch.setattr(agent_installer, "_local_user_exists", lambda name: user_exists)
    monkeypatch.setattr(agent_installer, "_share_info", lambda name: share)
    monkeypatch.setattr(
        agent_installer.win32security, "GetNamedSecurityInfo", lambda *args: object()
    )
    monkeypatch.setattr(
        agent_installer.win32net,
        "NetUserAdd",
        lambda server, level, info: calls.update(user=info),
    )
    monkeypatch.setattr(
        agent_installer.win32security,
        "LookupAccountName",
        lambda server, name: ("reader-sid", None, None),
    )
    monkeypatch.setattr(
        agent_installer,
        "_share_directory_acl",
        lambda path, sid, **kwargs: calls.update(directory_acl=(path, sid, kwargs)),
    )
    monkeypatch.setattr(
        agent_installer,
        "_share_security_descriptor",
        lambda sid, **kwargs: calls.update(descriptor=kwargs) or "share-security",
    )
    monkeypatch.setattr(
        agent_installer.win32net,
        "NetShareAdd",
        lambda server, level, info: calls.update(share=(level, info)),
    )
    monkeypatch.setattr(
        agent_installer.win32security, "LsaOpenPolicy", lambda server, access: "policy"
    )
    monkeypatch.setattr(
        agent_installer.win32security,
        "LsaAddAccountRights",
        lambda policy, sid, rights: calls.update(denied_rights=(sid, tuple(rights))),
    )
    monkeypatch.setattr(agent_installer.win32security, "LsaClose", lambda policy: None)


def test_log_share_is_writable_for_the_reader(tmp_path, monkeypatch):
    calls = {}
    _patch_share_calls(monkeypatch, calls, user_exists=False, share=None)
    credential = "-".join(("Test", "only", "Password", "123!"))

    account, unc, created = agent_installer.ensure_log_share(
        tmp_path / "protokoll", credential, credential
    )

    assert created is True
    assert account.endswith(r"\PortalLeser")
    assert unc.endswith(r"\RDP-Protokoll")
    assert calls["directory_acl"][2] == {"writable": True}
    assert calls["descriptor"] == {"writable": True}
    assert calls["share"][1]["netname"] == "RDP-Protokoll"


def test_the_status_share_stays_read_only(tmp_path, monkeypatch):
    """Schreibrecht gilt nur für den Protokollordner, nicht für den Statusordner."""
    calls = {}
    _patch_share_calls(monkeypatch, calls, user_exists=False, share=None)
    credential = "-".join(("Test", "only", "Password", "123!"))

    agent_installer.ensure_status_share(tmp_path / "status", credential, credential)

    assert calls["directory_acl"][2] == {}
    assert calls["descriptor"] == {}


def test_log_share_reuses_an_existing_reader_without_a_password(tmp_path, monkeypatch):
    """Der Normalfall: Die Maschine ist selbst Zielrechner und hat das Konto schon."""
    calls = {}
    _patch_share_calls(monkeypatch, calls, user_exists=True, share=None)

    account, _, created = agent_installer.ensure_log_share(tmp_path / "protokoll", "", "")

    assert created is True
    assert account.endswith(r"\PortalLeser")
    assert "user" not in calls  # Kein zweites Konto angelegt.
    assert "denied_rights" not in calls  # Und an einem bestehenden nichts verändert.


def test_log_share_reuses_the_same_folder_without_touching_anything(tmp_path, monkeypatch):
    calls = {}
    protokoll = tmp_path / "protokoll"
    _patch_share_calls(monkeypatch, calls, user_exists=True, share={"path": str(protokoll)})

    _, _, created = agent_installer.ensure_log_share(protokoll, "", "")

    assert created is False
    assert calls == {}


def test_log_share_refuses_a_share_pointing_elsewhere(tmp_path, monkeypatch):
    calls = {}
    _patch_share_calls(monkeypatch, calls, user_exists=True, share={"path": r"C:\woanders"})

    with pytest.raises(RuntimeError, match="zeigt auf"):
        agent_installer.ensure_log_share(tmp_path / "protokoll", "", "")


def test_log_share_needs_a_password_for_a_new_account(tmp_path, monkeypatch):
    calls = {}
    _patch_share_calls(monkeypatch, calls, user_exists=False, share=None)

    with pytest.raises(ValueError, match="Kennwort"):
        agent_installer.ensure_log_share(tmp_path / "protokoll", "", "")


def test_log_share_acl_grants_write_and_delete():
    """Ohne DELETE scheitert die Rotation, die die gekürzte Datei über die alte schiebt."""
    reader_sid = win32security.ConvertStringSidToSid("S-1-5-21-1-2-3-1001")

    descriptor = agent_installer._share_security_descriptor(reader_sid, writable=True)

    acl = descriptor.GetSecurityDescriptorDacl()
    reader_aces = [
        acl.GetAce(index)
        for index in range(acl.GetAceCount())
        if acl.GetAce(index)[2] == reader_sid
    ]
    assert len(reader_aces) == 1
    mask = reader_aces[0][1]
    assert mask & agent_installer.ntsecuritycon.FILE_WRITE_DATA
    assert mask & agent_installer.ntsecuritycon.FILE_GENERIC_READ
    assert mask & agent_installer.ntsecuritycon.DELETE


# --- Fenster des Setups ------------------------------------------------------


@pytest.fixture(scope="module")
def installer_window():
    """Genau ein Fenster für alle Prüfungen.

    Tk verträgt es in einem Prozess schlecht, mehrfach erzeugt und wieder
    zerstört zu werden; der zweite Aufbau scheitert mit einer Meldung über eine
    angeblich kaputte Installation.
    """
    from pathlib import Path as _Path

    window = agent_installer.InstallerWindow(_Path("."))
    window.root.deiconify()
    window.root.update()
    yield window
    window.root.destroy()


def _install_button_reachable(window) -> bool:
    button = window.install_button
    bottom = button.winfo_rooty() - window.root.winfo_rooty() + button.winfo_height()
    return bool(button.winfo_ismapped()) and bottom <= window.root.winfo_height()


def test_the_window_fits_its_own_content(installer_window):
    """Ein festes Maß hielt nur, bis ein Kasten dazukam -- dann war der Knopf weg."""
    assert installer_window.root.winfo_height() >= installer_window.root.winfo_reqheight()
    assert _install_button_reachable(installer_window)


def test_the_window_can_be_resized(installer_window):
    """Wäre es das nicht, käme man an einen abgeschnittenen Knopf gar nicht heran."""
    assert installer_window.root.resizable() == (True, True)


@pytest.mark.parametrize("height", [560, 420])
def test_the_install_button_survives_a_smaller_window(installer_window, height):
    """Die Knopfzeile hängt am Fenster, nicht am Inhalt.

    Deshalb bleibt sie erreichbar, auch wenn der Inhalt nicht mehr ganz
    hineinpasst -- etwa auf einem kleinen Bildschirm oder bei großer
    Windows-Schrift.
    """
    root = installer_window.root
    original = (root.winfo_width(), root.winfo_height())
    root.minsize(1, 1)
    root.geometry(f"664x{height}")
    root.update()
    try:
        assert _install_button_reachable(installer_window)
    finally:
        root.geometry(f"{original[0]}x{original[1]}")
        root.update()


def test_the_log_share_fields_follow_their_checkbox(installer_window):
    installer_window.configure_log_share.set(False)
    installer_window._toggle_log_fields()
    assert str(installer_window.log_directory_entry.cget("state")) == "disabled"

    installer_window.configure_log_share.set(True)
    installer_window._toggle_log_fields()
    assert str(installer_window.log_directory_entry.cget("state")) == "normal"


# --- Zwischenstand während der Einrichtung -----------------------------------


def test_the_progress_line_names_step_and_total():
    progress = agent_installer.SetupProgress(8)

    assert progress.step("Dateien kopieren …") == "Schritt 1/8: Dateien kopieren …"
    assert progress.step("Aufgabe anlegen …") == "Schritt 2/8: Aufgabe anlegen …"


def test_a_countdown_stays_on_the_same_step():
    """Das Warten auf den Agenten ist ein Schritt, kein Dutzend."""
    progress = agent_installer.SetupProgress(3)
    progress.step("Agent starten …")

    assert progress.detail("noch 19 s") == "Schritt 1/3: noch 19 s"
    assert progress.detail("noch 18 s") == "Schritt 1/3: noch 18 s"


def test_every_step_is_reported_outwards():
    seen = []
    progress = agent_installer.SetupProgress(2, seen.append)

    progress.step("eins")
    progress.detail("eins, noch etwas")

    assert seen == ["Schritt 1/2: eins", "Schritt 1/2: eins, noch etwas"]


@pytest.mark.parametrize(
    ("configure_share", "launch_now", "expected"),
    [(True, True, 8), (False, True, 7), (True, False, 7), (False, False, 6)],
)
def test_the_step_count_matches_what_is_actually_done(configure_share, launch_now, expected):
    """Sonst stünde am Ende 7/8 und man wartete auf einen Schritt, der nie kommt."""
    assert (
        agent_installer.install_step_count(
            configure_share=configure_share, launch_now=launch_now
        )
        == expected
    )


def test_the_counter_never_runs_past_its_total():
    progress = agent_installer.SetupProgress(2)
    for _ in range(5):
        progress.step("weiter")

    assert progress.line() == "Schritt 2/2: weiter"


def _write_snapshot(directory, **overrides):
    snapshot = {
        "workstation_id": "WS-002",
        "hostname": "Remote-Ettlingen",
        "agent_status": "online",
        "observed_at_utc": datetime.now(UTC).isoformat(),
    }
    snapshot.update(overrides)
    (directory / "WS-002.json").write_text(json.dumps(snapshot), encoding="utf-8")


@pytest.fixture
def long_host_name(monkeypatch):
    """Ein Rechnername über 15 Zeichen: NetBIOS kürzt ihn, DNS nicht."""
    monkeypatch.setenv("COMPUTERNAME", "REMOTE-ETTLINGE")
    monkeypatch.setattr(agent_installer.socket, "gethostname", lambda: "Remote-Ettlingen")
    monkeypatch.setattr(agent_installer, "SNAPSHOT_TIMEOUT_SECONDS", 0.6)
    monkeypatch.setattr(agent_installer.time, "sleep", lambda seconds: None)


def test_a_long_host_name_is_not_mistaken_for_another_machine(tmp_path, long_host_name):
    """Der Agent meldet den DNS-Namen, %COMPUTERNAME% ist auf 15 Zeichen gekürzt."""
    started_at = datetime.now(UTC)
    _write_snapshot(tmp_path)

    agent_installer._confirm_snapshot(tmp_path, "WS-002", started_at)


def test_the_failure_names_what_did_not_match(tmp_path, long_host_name):
    started_at = datetime.now(UTC)
    _write_snapshot(tmp_path, hostname="NB12KI")

    with pytest.raises(RuntimeError, match="vom Rechner 'NB12KI'"):
        agent_installer._confirm_snapshot(tmp_path, "WS-002", started_at)


def test_shared_paths_use_the_name_the_network_resolves(long_host_name):
    assert agent_installer._network_host_name() == "Remote-Ettlingen"


def test_the_waiting_step_counts_down(tmp_path, monkeypatch):
    """Der Schritt, an dem das Fenster wie eingefroren aussah."""
    seen = []
    progress = agent_installer.SetupProgress(1, seen.append)
    progress.step("Agent starten …")  # Das tut install_agent unmittelbar davor.
    seen.clear()
    monkeypatch.setattr(agent_installer, "SNAPSHOT_TIMEOUT_SECONDS", 0.6)
    monkeypatch.setattr(agent_installer.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="keinen aktuellen Online-Status"):
        agent_installer._confirm_snapshot(
            tmp_path, "WS-001", datetime.now(UTC), progress
        )

    assert seen, "Ohne Meldung sieht das Warten wie ein Absturz aus."
    assert all("Schritt 1/1" in line for line in seen)
    assert "noch" in seen[0]


def test_the_result_note_exists_before_any_install_runs(installer_window):
    """Der Fehler, der ein fertiges Setup wie ein hängendes aussehen ließ.

    ``log_share_note`` wurde erst im Arbeitsthread gesetzt -- und nur, wenn die
    Protokollfreigabe angekreuzt war. Sonst lief die Erfolgsmeldung in einen
    AttributeError, mitten im Tk-Callback: kein Dialog, keine Fehlermeldung, nur
    ein Fenster mit gesperrten Knöpfen.
    """
    assert installer_window.log_share_note == ""
    assert installer_window.progress_messages.qsize() == 0
