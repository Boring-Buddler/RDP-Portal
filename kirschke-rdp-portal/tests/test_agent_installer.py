import json
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
        "_status_directory_acl",
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
