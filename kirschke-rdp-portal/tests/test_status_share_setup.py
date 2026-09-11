from pathlib import Path
import subprocess


def test_status_share_setup_with_mocked_windows_accounts(tmp_path):
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(project / "tests/check_status_share.ps1"), "-Project", str(project), "-TestRoot", str(tmp_path)],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
