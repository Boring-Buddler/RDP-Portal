"""Guards for findings S4, S5 and S6.

S4: agent snapshots come over SMB from another machine and were read without any
    size, count or length ceiling.
S5: the per-machine trust exception disabled server authentication outright.
S6: generated .rdp files name the target and the user and survived a crash.
"""

import json
import time

import pytest

from portal_app.models.workstation import Workstation
from portal_app.rdp.generator import RDPFileGenerator
from shared.agent_snapshot import (
    MAX_IDENTIFIER_LENGTH,
    MAX_SESSIONS,
    MAX_SNAPSHOT_BYTES,
    MAX_SNAPSHOT_FILES,
    AgentSnapshot,
    scan_agent_snapshots,
    write_agent_snapshot,
)


def _valid_payload(**overrides) -> dict:
    payload = {
        "version": 1,
        "workstation_id": "WS-1",
        "hostname": "WS-1",
        "agent_version": "1.3.0",
        "observed_at_utc": "2026-09-11T10:00:00+00:00",
        "agent_status": "online",
        "current_session_state": "none",
        "rdp_sessions": [],
        "session_history": [],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# S4: bounded untrusted input
# --------------------------------------------------------------------------


def test_a_valid_snapshot_still_parses() -> None:
    assert AgentSnapshot.from_dict(_valid_payload()).workstation_id == "WS-1"


@pytest.mark.parametrize("field", ["workstation_id", "hostname"])
def test_overlong_identifier_is_rejected(field: str) -> None:
    payload = _valid_payload(**{field: "A" * (MAX_IDENTIFIER_LENGTH + 1)})
    with pytest.raises(ValueError, match="too long"):
        AgentSnapshot.from_dict(payload)


def test_overlong_session_user_is_rejected() -> None:
    payload = _valid_payload(current_session_user="U" * (MAX_IDENTIFIER_LENGTH + 1))
    with pytest.raises(ValueError, match="too long"):
        AgentSnapshot.from_dict(payload)


def test_identifier_at_the_limit_is_accepted() -> None:
    payload = _valid_payload(hostname="H" * MAX_IDENTIFIER_LENGTH)
    assert len(AgentSnapshot.from_dict(payload).hostname) == MAX_IDENTIFIER_LENGTH


def test_too_many_sessions_are_rejected() -> None:
    sessions = [{"session_id": index + 1, "username": "u"} for index in range(MAX_SESSIONS + 1)]
    with pytest.raises(ValueError, match="Too many RDP sessions"):
        AgentSnapshot.from_dict(_valid_payload(rdp_sessions=sessions))


def test_sessions_at_the_limit_are_accepted() -> None:
    sessions = [{"session_id": index + 1, "username": "u"} for index in range(MAX_SESSIONS)]
    assert len(AgentSnapshot.from_dict(_valid_payload(rdp_sessions=sessions)).rdp_sessions) == MAX_SESSIONS


def test_overlong_session_field_is_rejected() -> None:
    sessions = [{"session_id": 2, "full_username": "X" * (MAX_IDENTIFIER_LENGTH + 1)}]
    with pytest.raises(ValueError, match="too long"):
        AgentSnapshot.from_dict(_valid_payload(rdp_sessions=sessions))


def test_session_history_is_capped(tmp_path) -> None:
    history = [{"n": index} for index in range(1000)]
    snapshot = AgentSnapshot.from_dict(_valid_payload(session_history=history))
    assert len(snapshot.session_history) == 200
    assert snapshot.session_history[-1] == {"n": 999}


def test_an_oversized_file_is_reported_not_parsed(tmp_path) -> None:
    directory = tmp_path / "status"
    directory.mkdir()
    payload = _valid_payload(description="x" * (MAX_SNAPSHOT_BYTES + 1000))
    (directory / "WS-1.json").write_text(json.dumps(payload), encoding="utf-8")

    files, _ = scan_agent_snapshots(directory)

    assert len(files) == 1
    assert files[0].snapshot is None
    assert files[0].error is not None
    assert "kB" in files[0].error


def test_scanning_stops_at_the_file_ceiling(tmp_path) -> None:
    directory = tmp_path / "status"
    directory.mkdir()
    for index in range(MAX_SNAPSHOT_FILES + 25):
        (directory / f"WS-{index:04d}.json").write_text(
            json.dumps(_valid_payload(workstation_id=f"WS-{index:04d}", hostname=f"H{index}")),
            encoding="utf-8",
        )

    files, other_names = scan_agent_snapshots(directory)

    assert len(files) == MAX_SNAPSHOT_FILES
    assert any("nicht mehr gelesen" in name for name in other_names)


def test_a_normal_folder_is_unaffected_by_the_ceiling(tmp_path) -> None:
    directory = tmp_path / "status"
    directory.mkdir()
    write_agent_snapshot(AgentSnapshot("WS-1", "WS-1", "1.3.0"), directory)
    write_agent_snapshot(AgentSnapshot("WS-2", "WS-2", "1.3.0"), directory)
    files, other_names = scan_agent_snapshots(directory)
    assert len(files) == 2
    assert all(result.snapshot is not None for result in files)
    assert not any("nicht mehr gelesen" in name for name in other_names)


# --------------------------------------------------------------------------
# S5: weaken the check, do not switch it off
# --------------------------------------------------------------------------


def test_trusted_machine_warns_instead_of_skipping_server_authentication(tmp_path) -> None:
    machine = Workstation(
        workstation_id="WS-TRUST",
        display_name="Geprüfte Maschine",
        hostname="PC-TRUST",
        trust_unverified_server=True,
    )
    content = open(
        RDPFileGenerator(str(tmp_path)).generate(machine.get_rdp_profile()), encoding="utf-8"
    ).read()
    assert "authentication level:i:2" in content
    assert "authentication level:i:0" not in content


def test_untrusted_machine_keeps_the_windows_default(tmp_path) -> None:
    machine = Workstation(
        workstation_id="WS-PLAIN", display_name="Normale Maschine", hostname="PC-PLAIN"
    )
    content = open(
        RDPFileGenerator(str(tmp_path)).generate(machine.get_rdp_profile()), encoding="utf-8"
    ).read()
    assert "authentication level" not in content


# --------------------------------------------------------------------------
# S6: orphaned .rdp files
# --------------------------------------------------------------------------


def test_cleanup_old_removes_orphans_this_process_never_tracked(tmp_path) -> None:
    """After a crash the new process has an empty list; the folder still has files."""
    orphan = tmp_path / "rdp_PC-OLD_deadbeef.rdp"
    orphan.write_text("full address:s:PC-OLD\nusername:s:KIRSCHKE\\becker\n", encoding="utf-8")
    old = time.time() - 48 * 3600
    import os

    os.utime(orphan, (old, old))

    generator = RDPFileGenerator(str(tmp_path))
    assert generator._generated_files == []
    assert generator.cleanup_old(older_than_hours=24) == 1
    assert not orphan.exists()


def test_cleanup_old_keeps_recent_files(tmp_path) -> None:
    recent = tmp_path / "rdp_PC-NEW_cafe1234.rdp"
    recent.write_text("full address:s:PC-NEW\n", encoding="utf-8")
    assert RDPFileGenerator(str(tmp_path)).cleanup_old(older_than_hours=24) == 0
    assert recent.exists()


def test_cleanup_old_ignores_unrelated_files(tmp_path) -> None:
    """Only the generator's own rdp_<target>_<8 hex>.rdp pattern may be deleted."""
    import os

    old = time.time() - 48 * 3600
    keep = [
        tmp_path / "important.rdp",
        tmp_path / "rdp_manual.rdp",
        tmp_path / "rdp_PC_notahex.rdp",
        tmp_path / "rdp_PC_deadbeef.txt",
    ]
    for path in keep:
        path.write_text("x", encoding="utf-8")
        os.utime(path, (old, old))

    assert RDPFileGenerator(str(tmp_path)).cleanup_old(older_than_hours=24) == 0
    assert all(path.exists() for path in keep)


def test_cleanup_old_survives_a_missing_folder(tmp_path) -> None:
    assert RDPFileGenerator(str(tmp_path / "does-not-exist")).cleanup_old() == 0
