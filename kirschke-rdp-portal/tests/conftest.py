"""Keep the portable default inventory out of the real source/program folder."""

import pytest


@pytest.fixture(autouse=True)
def isolated_portal_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    monkeypatch.setattr(
        "shared.agent_paths.portal_program_directory", lambda: tmp_path / "portal"
    )


@pytest.fixture(autouse=True)
def no_saved_rdp_credentials(monkeypatch):
    """Den Verbindungsweg nicht von der Anmeldeverwaltung des Test-PCs abhängig machen."""
    monkeypatch.setattr(
        "portal_app.services.rdp_diagnostics.saved_rdp_credential_user", lambda target: None
    )
    monkeypatch.setattr(
        "portal_app.services.rdp_diagnostics.saved_server_credential_user", lambda target: None
    )
    monkeypatch.setattr(
        "portal_app.services.share_connection.stored_share_credentials", lambda server: None
    )
