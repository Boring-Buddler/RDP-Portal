"""Keep the portable default inventory out of the real source/program folder."""

import pytest


@pytest.fixture(autouse=True)
def isolated_portal_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    monkeypatch.setattr(
        "shared.agent_paths.portal_program_directory", lambda: tmp_path / "portal"
    )
