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


@pytest.fixture(autouse=True)
def no_rdp_signing_certificate(monkeypatch):
    """Ein eingerichtetes Signaturzertifikat des Test-PCs darf keinen Test signieren lassen."""
    monkeypatch.setattr("portal_app.rdp.signing.configured_thumbprint", lambda: None)


@pytest.fixture(autouse=True)
def no_start_inventory(request, monkeypatch):
    """Ein Fenster aus einem Test startet ohne die mitgelieferten echten Maschinen.

    Sonst kämen sie zu jedem vorbereiteten Stand einmal dazu, wie bei einem
    Update. Tests des Startinventars markieren sich mit ``start_inventory``.
    """
    if request.node.get_closest_marker("start_inventory") is None:
        monkeypatch.setattr("portal_app.ui.main_window.load_start_inventory", lambda: [])
