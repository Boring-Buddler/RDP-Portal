"""Kirschke RDP Workstation Portal - Main Application Package."""

from portal_app import auth, graph, models, rdp, services, ui


def main() -> None:
    """Start the portal without importing the application during package loading."""
    from portal_app.app import main as run_app

    run_app()


__all__ = ["main", "models", "auth", "graph", "rdp", "services", "ui"]
