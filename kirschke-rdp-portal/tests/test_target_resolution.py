"""Die automatische Zielwahl überspringt, was sich nicht auflösen lässt.

Über zwei Standorte hinweg ist der kurze Windows-Name der Regelfall des
Scheiterns: NetBIOS und LLMNR sind link-lokal, ein Router leitet sie nicht
weiter. Vorher nahm das Portal trotzdem den Namen und mstsc meldete "kann den
Computer PC07 nicht finden", während die daneben stehende IP funktioniert hätte.
"""

import pytest

from portal_app.models.workstation import Workstation
from portal_app.rdp.generator import RDPFileGenerator
from shared import name_resolution
from shared.enums import ConnectionTargetMode


@pytest.fixture(autouse=True)
def _fresh_cache():
    name_resolution.clear_cache()
    yield
    name_resolution.clear_cache()


def machine(**kwargs):
    return Workstation("WS-1", "PC07", kwargs.pop("hostname", "PC07"), **kwargs)


def only(*names):
    """Ein Resolver, der genau die genannten Bezeichner kennt."""
    known = {name.casefold() for name in names}
    return lambda value: value.casefold() in known


# --- Auflösbarkeit -----------------------------------------------------------

def test_an_ip_address_needs_no_lookup(monkeypatch):
    monkeypatch.setattr(
        name_resolution, "_lookup", lambda name: pytest.fail("darf nicht nachschlagen")
    )

    assert name_resolution.resolvable("192.168.20.210") is True
    assert name_resolution.resolvable("fe80::1%20") is True


def test_nothing_is_not_resolvable():
    assert name_resolution.resolvable("") is False
    assert name_resolution.resolvable(None) is False


def test_an_answer_is_only_fetched_once(monkeypatch):
    calls = []
    monkeypatch.setattr(name_resolution, "_lookup", lambda name: calls.append(name) or True)

    assert name_resolution.resolvable("PC07") is True
    assert name_resolution.resolvable("pc07") is True

    assert calls == ["PC07"]


def test_a_remembered_answer_is_used(monkeypatch):
    monkeypatch.setattr(
        name_resolution, "_lookup", lambda name: pytest.fail("darf nicht nachschlagen")
    )
    name_resolution.remember("PC07", False)

    assert name_resolution.resolvable("PC07") is False


# --- Zielwahl ----------------------------------------------------------------

def test_the_unresolvable_name_is_skipped_for_the_ip():
    profile = machine(ip_address="192.168.20.210").get_rdp_profile()

    target, mode = profile.resolve_connection_target(only("192.168.20.210"))

    assert (target, mode) == ("192.168.20.210", ConnectionTargetMode.IP_ADDRESS)


def test_a_resolvable_name_still_wins_over_the_ip():
    """Der Name bleibt die erste Wahl -- Kerberos und Single Sign-on brauchen ihn."""
    profile = machine(ip_address="192.168.20.210").get_rdp_profile()

    target, mode = profile.resolve_connection_target(only("PC07", "192.168.20.210"))

    assert (target, mode) == ("PC07", ConnectionTargetMode.HOSTNAME)


def test_the_fqdn_stays_ahead_of_the_short_name():
    ws = machine(ip_address="192.168.20.210", fqdn="pc07.kirschke.local")

    target, mode = ws.get_rdp_profile().resolve_connection_target(
        only("pc07.kirschke.local", "PC07")
    )

    assert (target, mode) == ("pc07.kirschke.local", ConnectionTargetMode.FQDN)


def test_the_launch_profile_carries_the_target_the_card_shows(monkeypatch):
    r"""Am anderen Standort zeigt die Karte die IP -- und genau die steht in der Datei.

    Vorher entschied der Start ohne Nachfrage, nahm den Namen und mstsc fand den
    Computer nicht. Mit der IP entfällt das Webkonto, und das Entra-Konto
    braucht die Schreibweise AzureAD\name.
    """
    monkeypatch.setattr(name_resolution, "resolvable", only("192.168.20.210"))
    ws = machine(ip_address="192.168.20.210", entra_sso_enabled=True,
                 username_hint="becker@prof-kirschke.de")
    assert ws.get_connection_target()[0] == "192.168.20.210"

    content = RDPFileGenerator()._generate_content(ws.get_launch_profile())

    assert "full address:s:192.168.20.210" in content
    assert "enablerdsaadauth:i:0" in content
    assert r"username:s:AzureAD\becker@prof-kirschke.de" in content


def test_the_launch_profile_keeps_a_resolvable_name(monkeypatch):
    monkeypatch.setattr(name_resolution, "resolvable", only("PC07", "192.168.20.210"))
    ws = machine(ip_address="192.168.20.210", entra_sso_enabled=True,
                 username_hint="becker@prof-kirschke.de")

    content = RDPFileGenerator()._generate_content(ws.get_launch_profile())

    assert "full address:s:PC07" in content
    assert "enablerdsaadauth:i:1" in content
    assert "username:s:becker@prof-kirschke.de" in content


def test_nothing_resolvable_falls_back_to_the_old_order():
    """Nie schlechter als vorher: dann meldet Windows den Fehler mit eigenen Worten."""
    profile = machine(ip_address="192.168.20.210").get_rdp_profile()

    target, mode = profile.resolve_connection_target(only())

    assert (target, mode) == ("PC07", ConnectionTargetMode.HOSTNAME)


def test_an_explicit_choice_is_never_overruled():
    ws = machine(
        ip_address="192.168.20.210",
        connection_target_mode=ConnectionTargetMode.HOSTNAME,
    )

    target, mode = ws.get_rdp_profile().resolve_connection_target(only("192.168.20.210"))

    assert (target, mode) == ("PC07", ConnectionTargetMode.HOSTNAME)


def test_a_single_candidate_is_decided_without_asking():
    """Sonst kostete jede Kartenaktualisierung eine Abfrage ohne jeden Nutzen."""
    profile = machine().get_rdp_profile()

    def refuse(_value):
        pytest.fail("darf nicht gefragt werden")

    assert profile.resolve_connection_target(refuse)[0] == "PC07"


def test_without_a_resolver_the_order_alone_decides():
    profile = machine(ip_address="192.168.20.210").get_rdp_profile()

    assert profile.resolve_connection_target()[0] == "PC07"


# --- Agentkanal --------------------------------------------------------------

def test_an_unresolvable_share_name_falls_through_to_the_rdp_target(monkeypatch):
    """Sonst kostet ein Freigabename den Livestatus einer erreichbaren Maschine."""
    monkeypatch.setattr(name_resolution, "_lookup", lambda name: False)
    ws = machine(ip_address="192.168.20.210")
    ws.agent_fallback_directory = r"\\PC07\RDP-Status"
    ws.agent_fallback_is_explicit = True

    assert ws.get_agent_status_target() == "192.168.20.210"


def test_a_resolvable_share_name_is_kept(monkeypatch):
    monkeypatch.setattr(name_resolution, "_lookup", lambda name: True)
    ws = machine(ip_address="192.168.20.210")
    ws.agent_fallback_directory = r"\\PC07\RDP-Status"
    ws.agent_fallback_is_explicit = True

    assert ws.get_agent_status_target() == "PC07"


def test_a_share_written_with_the_ip_needs_no_lookup(monkeypatch):
    monkeypatch.setattr(
        name_resolution, "_lookup", lambda name: pytest.fail("darf nicht nachschlagen")
    )
    ws = machine(ip_address="192.168.20.210")
    ws.agent_fallback_directory = "\\\\192.168.20.210\\RDP-Status"
    ws.agent_fallback_is_explicit = True

    assert ws.get_agent_status_target() == "192.168.20.210"


# --- Der Servername für einen UNC-Pfad ----------------------------------------


def test_a_dns_name_is_shortened_for_the_unc_path():
    r"""Die Freigabe des Agenten heißt \PC07\RDP-Status, nicht \PC07.firma.de\..."""
    assert name_resolution.unc_server_name("PC07.kirschke.local") == "PC07"
    assert name_resolution.unc_server_name("PC07") == "PC07"


def test_an_ip_address_survives_the_unc_path_intact():
    r"""Der Bug: Aus 192.168.2.10 wurde \192\RDP-Status und Windows-Fehler 67.

    Die Kürzung auf das erste Label ist für einen DNS-Namen richtig und für eine
    IP-Adresse zerstörend. Der Verbindungsassistent meldete daraufhin "nicht
    eingerichtet" für eine Maschine, die über ihre IP erreichbar war.
    """
    assert name_resolution.unc_server_name("192.168.2.10") == "192.168.2.10"
    assert name_resolution.unc_server_name("10.0.0.1") == "10.0.0.1"


def test_an_empty_identifier_yields_no_server_name():
    assert name_resolution.unc_server_name("") == ""
    assert name_resolution.unc_server_name(None) == ""
    assert name_resolution.unc_server_name("   ") == ""
