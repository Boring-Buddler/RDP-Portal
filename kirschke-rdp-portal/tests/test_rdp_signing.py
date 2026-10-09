"""Signierte .rdp-Dateien: signieren, wenn eingerichtet -- und nie den Start verhindern."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from portal_app.models.workstation import Workstation
from portal_app.rdp import signing
from portal_app.rdp.generator import RDPFileGenerator
from portal_app.rdp.launcher import RDPSessionLauncher

THUMBPRINT = "165F69F04012E250EF3E1864D43FE9E19DDB6D67"  # SHA-1, wie rdpsign ihn will
CONTENT = "full address:s:Remote-Ettlingen\nscreen mode id:i:1\n"


@pytest.fixture
def rdp_file(tmp_path: Path) -> Path:
    path = tmp_path / "verbindung.rdp"
    path.write_text(CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def rdpsign(monkeypatch):
    monkeypatch.setattr(signing, "system32_tool", lambda name: rf"C:\Windows\System32\{name}")


def fake_rdpsign(returncode: int = 0, *, sign: bool = True) -> Mock:
    """Wie rdpsign: haengt bei Erfolg signscope und signature an die Datei an."""
    def run(command, **kwargs):
        if sign and returncode == 0:
            path = Path(command[-1])
            text = path.read_text(encoding="utf-16")
            path.write_text(text + "signscope:s:Full Address\nsignature:s:AAAA\n", encoding="utf-16")
        return subprocess.CompletedProcess(command, returncode, b"", b"")
    return Mock(side_effect=run)


def test_without_a_thumbprint_nothing_is_signed(rdp_file, rdpsign, monkeypatch):
    run = Mock()
    monkeypatch.setattr(signing.subprocess, "run", run)

    assert signing.sign_rdp_file(rdp_file) is False

    run.assert_not_called()
    assert rdp_file.read_text(encoding="utf-8") == CONTENT


def test_a_configured_thumbprint_signs_with_an_absolute_rdpsign(rdp_file, rdpsign, monkeypatch):
    run = fake_rdpsign()
    monkeypatch.setattr(signing.subprocess, "run", run)

    assert signing.sign_rdp_file(rdp_file, THUMBPRINT.lower()) is True

    command = run.call_args.args[0]
    assert command == [r"C:\Windows\System32\rdpsign.exe", "/sha256", THUMBPRINT, "/q", str(rdp_file)]
    assert run.call_args.kwargs["shell"] is False
    assert run.call_args.kwargs["timeout"] == signing.SIGN_TIMEOUT_SECONDS
    signed = rdp_file.read_bytes()
    assert signed[:2] == b"\xff\xfe"  # UTF-16LE, wie .rdp-Dateien ueblich
    text = signed.decode("utf-16")
    assert "full address:s:Remote-Ettlingen" in text and "signature:s:" in text


@pytest.mark.parametrize("failure", [
    fake_rdpsign(returncode=1),
    fake_rdpsign(returncode=0, sign=False),
    Mock(side_effect=subprocess.TimeoutExpired("rdpsign", 5)),
    Mock(side_effect=OSError("Zugriff verweigert")),
])
def test_a_failed_signature_restores_the_original_file(rdp_file, rdpsign, monkeypatch, caplog, failure):
    monkeypatch.setattr(signing.subprocess, "run", failure)

    assert signing.sign_rdp_file(rdp_file, THUMBPRINT) is False

    assert rdp_file.read_text(encoding="utf-8") == CONTENT
    assert "nicht signiert" in caplog.text


def test_a_missing_rdpsign_skips_the_signature(rdp_file, monkeypatch):
    def missing(name):
        raise FileNotFoundError(name)
    run = Mock()
    monkeypatch.setattr(signing, "system32_tool", missing)
    monkeypatch.setattr(signing.subprocess, "run", run)

    assert signing.sign_rdp_file(rdp_file, THUMBPRINT) is False
    run.assert_not_called()


@pytest.mark.parametrize("value", [None, "", "zu-kurz", "AB" * 19, 42, "G" * 40])
def test_only_a_sha1_thumbprint_counts(value):
    assert signing.normalise_thumbprint(value) is None


def test_a_sha256_value_from_0_9_9_is_rejected_with_a_hint(caplog):
    """rdpsign /sha256 sucht mit dem SHA-1-Wert; mit SHA-256 kam 0x80092004."""
    assert signing.normalise_thumbprint("F7D04811C1A4D171AF0F57DB059012E1D1A5AED3572996D08E3E0648DF0C42F5") is None
    assert "Install-RdpSigning.ps1 erneut" in caplog.text


def test_spaces_and_case_are_normalised():
    spaced = " ".join(THUMBPRINT[i:i + 2].lower() for i in range(0, 40, 2))
    assert signing.normalise_thumbprint(spaced) == THUMBPRINT


@pytest.mark.parametrize("signed", [True, False])
def test_the_launcher_starts_mstsc_whether_or_not_signing_worked(tmp_path, monkeypatch, signed):
    launcher = RDPSessionLauncher(RDPFileGenerator(str(tmp_path)))
    sign = Mock(return_value=signed)
    popen = Mock(return_value=Mock(pid=4711))
    monkeypatch.setattr("portal_app.rdp.launcher.sign_rdp_file", sign)
    monkeypatch.setattr(launcher, "_find_mstsc", lambda: r"C:\Windows\System32\mstsc.exe")
    monkeypatch.setattr("portal_app.rdp.launcher.subprocess.Popen", popen)
    profile = Workstation("WS-002", "Remote-Ettlingen", "Remote-Ettlingen").get_rdp_profile()

    success, _ = launcher.launch(profile, "WS-002", "Remote-Ettlingen")

    assert success
    rdp_file = sign.call_args.args[0]
    assert popen.call_args.args[0] == [r"C:\Windows\System32\mstsc.exe", rdp_file]
