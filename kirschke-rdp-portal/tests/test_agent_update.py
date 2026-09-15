"""Ein Agent-Update darf nicht stillschweigend ueberschreiben, was schon eingerichtet ist."""

import json

import pytest

from deployment.agent_installer import InstallerWindow


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Tut so, als sei hier bereits ein Agent eingerichtet."""
    config = tmp_path / "agent-config.json"

    def fake_paths():
        from types import SimpleNamespace
        return SimpleNamespace(install=tmp_path, data=tmp_path, config=config)

    monkeypatch.setattr("deployment.agent_installer.setup_paths", fake_paths)
    return config


def test_an_existing_machine_id_is_offered_again_instead_of_the_hostname(configured, monkeypatch):
    """Der Fehler, der eine als WS-005 registrierte Maschine auf NB05 zurueckgesetzt hat."""
    configured.write_text(json.dumps({"workstation_id": "WS-005", "poll_interval": 60,
                                      "status_directory": r"D:\status"}), encoding="utf-8")
    monkeypatch.setenv("COMPUTERNAME", "NB05")

    existing = InstallerWindow._existing_configuration()

    assert existing["workstation_id"] == "WS-005"
    assert InstallerWindow._interval_label(existing["poll_interval"]) == "60 Sekunden"


def test_a_fresh_machine_still_gets_the_hostname(configured):
    assert InstallerWindow._existing_configuration() == {}


def test_a_damaged_configuration_does_not_break_the_installer(configured):
    configured.write_text("{kein json", encoding="utf-8")

    assert InstallerWindow._existing_configuration() == {}


def test_a_configuration_that_is_not_an_object_is_ignored(configured):
    configured.write_text("[1, 2, 3]", encoding="utf-8")

    assert InstallerWindow._existing_configuration() == {}


@pytest.mark.parametrize(
    ("stored", "label"),
    [(30, "30 Sekunden (empfohlen)"), (60, "60 Sekunden"), (15, "15 Sekunden"),
     (None, "30 Sekunden (empfohlen)"), ("60", "30 Sekunden (empfohlen)"),
     (999, "30 Sekunden (empfohlen)")],
)
def test_the_interval_dropdown_falls_back_to_the_recommendation(stored, label):
    assert InstallerWindow._interval_label(stored) == label
