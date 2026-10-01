"""Wer sich unter dem gemeinsamen Workstation-Konto aufgeschaltet hat.

Der Fall, für den es das gibt: Auf die Workstation verbindet sich jeder unter
demselben eigens angelegten Windows-Konto. Der Agent meldet die Sitzung unter
diesem Konto, jedes Portal vergleicht sie mit den Konten seines Benutzers,
findet dasselbe Konto -- und zeigte die Maschine allen als "von dir belegt".
"""

from datetime import UTC, datetime, timedelta

import pytest

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.session_claims import build_claim
from portal_app.ui.machine_actions import MachineState, describe_actions, machine_state
from shared.agent_snapshot import AgentSnapshot, validate_session_claims
from shared.enums import AgentStatus, SessionState
from workstation_agent.claim_store import CLAIM_MAX_AGE_SECONDS, SessionClaimStore

SHARED_ACCOUNT = "WORKSTATION\\Rechenknecht"


def person(upn: str, display: str) -> MockUser:
    """Ein Portal-Benutzer, der das gemeinsame Konto als eigenes führt.

    Genau das passiert im Betrieb von selbst: Beim ersten Verbinden merkt sich
    das Portal das benutzte Konto als eigenes -- bei allen dasselbe.
    """
    user = MockUser.create_user()
    user.upn = upn
    user.display_name = display
    user.windows_identity = "NB-" + display
    user.own_accounts = [SHARED_ACCOUNT]
    return user


def session(session_id: int = 3, login: str = "2026-09-16T08:00:00+00:00") -> dict:
    return {
        "session_id": session_id,
        "full_username": SHARED_ACCOUNT,
        "session_state": SessionState.CONNECTED.value,
        "login_time": login,
    }


def workstation(claims: list[dict] | None = None) -> Workstation:
    machine = Workstation(
        "WS-1",
        "Workstation",
        "WORKSTATION",
        agent_status=AgentStatus.ONLINE,
        current_session_state=SessionState.CONNECTED,
        current_session_user=SHARED_ACCOUNT,
        agent_sessions=[session()],
    )
    machine.agent_status_source = "live"
    machine.agent_session_claims = claims
    return machine


def claim_of(user: MockUser, session_id: int | None = 3) -> dict:
    record = build_claim(user, SHARED_ACCOUNT)
    record["session_id"] = session_id
    record["login_time"] = "2026-09-16T08:00:00+00:00" if session_id else None
    return record


# --- Ohne Meldung: der Zustand, der das Problem war ---------------------------


def test_without_a_claim_the_shared_account_looks_like_everybodys_own():
    """Der Ausgangszustand, dokumentiert -- und der Grund für den ganzen Kanal."""
    machine = workstation()

    for user in (person("a@x.de", "Becker"), person("b@x.de", "Kollege")):
        assert machine.owned_sessions(user.windows_accounts(), user.upn)
        assert machine_state(machine, user) is MachineState.OWN_IDLE


# --- Mit Meldung -------------------------------------------------------------


def test_a_foreign_claim_makes_the_shared_session_foreign():
    becker, kollege = person("a@x.de", "Becker"), person("b@x.de", "Kollege")
    machine = workstation([claim_of(becker)])

    assert not machine.owned_sessions(kollege.windows_accounts(), kollege.upn)
    assert machine_state(machine, kollege) is MachineState.OCCUPIED_OTHER


def test_your_own_claim_leaves_the_session_yours():
    becker = person("a@x.de", "Becker")
    machine = workstation([claim_of(becker)])

    assert machine.owned_sessions(becker.windows_accounts(), becker.upn)
    assert machine_state(machine, becker) is MachineState.OWN_IDLE


def test_the_card_names_the_person_not_the_shared_account():
    """Ohne Namen wäre die Meldung nur eine Sperre und keine Auskunft."""
    becker, kollege = person("a@x.de", "Becker"), person("b@x.de", "Kollege")
    machine = workstation([claim_of(becker)])

    assert machine.session_owner_display(session()) == "Becker"
    actions = describe_actions(machine, kollege)
    assert actions.state is MachineState.OCCUPIED_OTHER
    assert not actions.logoff_visible


def test_a_claim_never_hands_somebody_a_foreign_session():
    """Die Regel, an der der Abmeldeweg hängt: wegnehmen ja, geben nie.

    Der Agent kann nicht prüfen, wer eine Meldung abgesetzt hat. Dürfte eine
    Meldung Zuordnung *geben*, könnte eine erfundene eine fremde Sitzung als
    eigene ausweisen -- und ``owned_sessions`` entscheidet, wem das Portal die
    Abmeldung anbietet.
    """
    fremd = person("c@x.de", "Fremd")
    fremd.own_accounts = []  # Das gemeinsame Konto gehört dieser Person nicht.
    machine = workstation([claim_of(fremd)])

    assert not machine.owned_sessions(fremd.windows_accounts(), fremd.upn)
    assert not describe_actions(machine, fremd).logoff_visible


def test_without_a_upn_claims_are_ignored_entirely():
    """Wer seine eigene Kennung nicht nennt, kann nicht sinnvoll unterscheiden."""
    becker = person("a@x.de", "Becker")
    machine = workstation([claim_of(becker)])

    assert machine.owned_sessions(becker.windows_accounts())


# --- Bindung an die tatsächliche Sitzung -------------------------------------


def test_an_unbound_claim_still_matches_by_account():
    """Die Meldung entsteht beim mstsc-Start, die Windows-Sitzung erst danach."""
    becker = person("a@x.de", "Becker")
    machine = workstation([claim_of(becker, session_id=None)])

    assert machine.session_claim(session())["owner_upn"] == "a@x.de"


def test_a_bound_claim_does_not_match_a_different_session():
    """Eine neue Anmeldung desselben Kontos ist nicht mehr dieselbe Person."""
    becker = person("a@x.de", "Becker")
    machine = workstation([claim_of(becker)])

    later = session(session_id=7, login="2026-09-16T14:00:00+00:00")
    assert machine.session_claim(later) is None


# --- Der Speicher im Agenten -------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return SessionClaimStore(tmp_path / "claims.json")


def test_the_agent_binds_a_claim_to_the_session_it_finds(store):
    store.claim(build_claim(person("a@x.de", "Becker"), SHARED_ACCOUNT), "NB-Becker")

    bound = store.bind_and_expire([session()])

    assert bound[0]["session_id"] == 3
    assert bound[0]["login_time"] == "2026-09-16T08:00:00+00:00"
    assert bound[0]["client_name"] == "NB-Becker"


def test_a_claim_expires_when_the_session_ends(store):
    store.claim(build_claim(person("a@x.de", "Becker"), SHARED_ACCOUNT))
    store.bind_and_expire([session()])

    assert store.bind_and_expire([]) == []


def test_an_unbound_claim_expires_after_its_deadline(store):
    store.claim(build_claim(person("a@x.de", "Becker"), SHARED_ACCOUNT))
    later = datetime.now(UTC) + timedelta(seconds=CLAIM_MAX_AGE_SECONDS + 1)

    # Vorher bleibt sie: Zwischen mstsc-Start und fertiger Anmeldung liegen
    # bei einer Kennwort- oder Entra-Abfrage durchaus Minuten.
    assert store.bind_and_expire([], datetime.now(UTC))
    assert store.bind_and_expire([], later) == []


def test_one_claim_per_account_the_newest_wins(store):
    store.claim(build_claim(person("a@x.de", "Becker"), SHARED_ACCOUNT))
    store.claim(build_claim(person("b@x.de", "Kollege"), SHARED_ACCOUNT))

    current = store.current()
    assert len(current) == 1
    assert current[0]["owner_upn"] == "b@x.de"


def test_a_claim_survives_a_restart(tmp_path):
    path = tmp_path / "claims.json"
    SessionClaimStore(path).claim(build_claim(person("a@x.de", "Becker"), SHARED_ACCOUNT))

    assert SessionClaimStore(path).current()[0]["owner_upn"] == "a@x.de"


def test_a_damaged_store_never_stops_the_agent(tmp_path):
    path = tmp_path / "claims.json"
    path.write_text("{kein json", encoding="utf-8")

    assert SessionClaimStore(path).current() == []


# --- Übertragung -------------------------------------------------------------


def test_claims_travel_in_the_snapshot_and_survive_the_round_trip():
    becker = person("a@x.de", "Becker")
    snapshot = AgentSnapshot("A", "PC", "1.6.0", session_claims=[claim_of(becker)])

    returned = AgentSnapshot.from_dict(snapshot.to_dict())

    assert returned.session_claims[0]["owner_upn"] == "a@x.de"


def test_an_older_agent_reports_nothing_rather_than_nobody():
    """``None`` und ``[]`` müssen unterscheidbar bleiben -- wie bei den Buchungen."""
    data = AgentSnapshot("A", "PC", "1.5.0").to_dict()

    assert "session_claims" not in data
    assert AgentSnapshot.from_dict(data).session_claims is None


@pytest.mark.parametrize(
    "bad",
    [
        [{"owner_upn": "a@x.de"}],                      # ohne Konto
        [{"account": "WS\\x"}],                          # ohne Person
        [{"account": "WS\\x", "owner_upn": "a", "session_id": -1}],
        [{"account": "WS\\x", "owner_upn": "a", "owner_display": 5}],
        [{"account": "WS\\x", "owner_upn": "a" * 300}],
        "kein array",
    ],
)
def test_malformed_claims_are_refused(bad):
    """Die Meldungen kommen über eine Freigabe oder eine Pipe -- ungeprüfte Herkunft."""
    with pytest.raises(ValueError):
        validate_session_claims(bad)


def test_too_many_claims_are_refused():
    many = [{"account": f"WS\\u{index}", "owner_upn": "a@x.de"} for index in range(33)]

    with pytest.raises(ValueError):
        validate_session_claims(many)


# --- Jede Portal-Verbindung wird gemeldet ------------------------------------
#
# Weil das ausnahmslos geschieht, ist das Ausbleiben einer Meldung selbst eine
# Auskunft: Diese Sitzung kam vermutlich nicht über das Portal. Damit das trägt,
# darf eine Meldung nicht schon deshalb fehlen, weil der Agent im falschen
# Moment nicht erreichbar war.


class Pipe:
    """Ein Agent, der die ersten Versuche ablehnt und danach annimmt."""

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, target, claim, pipe_name=None, credentials=None):
        self.calls.append((target, claim))
        if self.failures > 0:
            self.failures -= 1
            raise OSError("Agent nicht erreichbar")
        return claim["account"]


@pytest.fixture
def reporter(monkeypatch):
    from portal_app.services import session_claims as module

    def build(failures: int = 0):
        pipe = Pipe(failures)
        monkeypatch.setattr(module, "push_session_claim", pipe)
        return module.SessionClaimReporter(), pipe

    return build


def reachable(claims=None) -> Workstation:
    machine = workstation(claims)
    machine.hostname = "WORKSTATION"
    return machine


def test_a_successful_report_leaves_nothing_pending(reporter):
    agent, pipe = reporter()
    machine = reachable()

    assert agent.report(machine, person("a@x.de", "Becker"), SHARED_ACCOUNT) == ""
    assert agent.pending == []
    assert len(pipe.calls) == 1


def test_a_failed_report_is_retried_on_the_next_status_run(reporter):
    """Sonst hieße eine verlorene Meldung hinterher "nicht über das Portal"."""
    agent, pipe = reporter(failures=2)
    machine = reachable()
    becker = person("a@x.de", "Becker")

    assert agent.report(machine, becker, SHARED_ACCOUNT)
    assert len(agent.pending) == 1

    agent.flush([machine], becker)
    assert len(agent.pending) == 1
    agent.flush([machine], becker)

    assert agent.pending == []
    assert len(pipe.calls) == 3


def test_a_claim_the_agent_already_reports_is_dropped(reporter):
    """Der bessere Beweis: Er gilt auch, wenn die Bestätigung verloren ging."""
    agent, pipe = reporter(failures=1)
    becker = person("a@x.de", "Becker")
    machine = reachable()
    agent.report(machine, becker, SHARED_ACCOUNT)

    machine.agent_session_claims = [claim_of(becker)]
    agent.flush([machine], becker)

    assert agent.pending == []
    assert len(pipe.calls) == 1  # Kein zweiter Versuch.


def test_someone_elses_claim_does_not_count_as_ours(reporter):
    """Die fremde Meldung erledigt die eigene nicht.

    Der Agent bleibt hier unerreichbar, damit ein gelungener Versuch den
    Eintrag nicht ohnehin abräumt: Bliebe er nur deshalb offen, prüfte der Test
    nichts.
    """
    agent, _ = reporter(failures=99)
    becker = person("a@x.de", "Becker")
    machine = reachable()
    agent.report(machine, becker, SHARED_ACCOUNT)

    machine.agent_session_claims = [claim_of(person("b@x.de", "Kollege"))]
    agent.flush([machine], becker)

    assert len(agent.pending) == 1


def test_retrying_continues_as_long_as_the_session_runs(reporter):
    """Dort sitzt jemand, und genau das soll sichtbar werden."""
    from portal_app.services.session_claims import UNCONFIRMED_MAX_AGE_SECONDS

    agent, pipe = reporter(failures=99)
    becker = person("a@x.de", "Becker")
    machine = reachable()
    agent.report(machine, becker, SHARED_ACCOUNT)
    agent.pending[0].created_at -= timedelta(seconds=UNCONFIRMED_MAX_AGE_SECONDS + 60)

    agent.flush([machine], becker)

    assert len(agent.pending) == 1


def test_a_connection_that_never_happened_is_given_up(reporter):
    """Ohne Sitzung läuft die Frist -- sonst liefe die Meldung endlos weiter."""
    from portal_app.services.session_claims import UNCONFIRMED_MAX_AGE_SECONDS

    agent, _ = reporter(failures=99)
    becker = person("a@x.de", "Becker")
    machine = reachable()
    machine.agent_sessions = []
    machine.current_session_state = SessionState.NONE
    machine.current_session_user = None
    agent.report(machine, becker, SHARED_ACCOUNT)
    agent.pending[0].created_at -= timedelta(seconds=UNCONFIRMED_MAX_AGE_SECONDS + 60)

    agent.flush([machine], becker)

    assert agent.pending == []


def test_a_deleted_machine_stops_being_retried(reporter):
    agent, _ = reporter(failures=99)
    becker = person("a@x.de", "Becker")
    agent.report(reachable(), becker, SHARED_ACCOUNT)

    agent.flush([], becker)

    assert agent.pending == []


def test_reporting_without_an_account_says_so_instead_of_pretending(reporter):
    agent, pipe = reporter()

    assert agent.report(reachable(), person("a@x.de", "Becker"), "")
    assert pipe.calls == []
    assert agent.pending == []


# --- Herkunft einer Sitzung --------------------------------------------------


def test_a_session_without_a_claim_is_marked_as_not_from_the_portal():
    machine = workstation(claims=[])

    assert machine.reports_session_claims()
    assert len(machine.unreported_sessions()) == 1


def test_a_reported_session_counts_as_coming_from_the_portal():
    machine = workstation([claim_of(person("a@x.de", "Becker"))])

    assert machine.unreported_sessions() == []


def test_an_older_agent_leaves_the_question_open():
    """``None`` heißt "weiß ich nicht" und darf nicht als Nein gelesen werden."""
    machine = workstation(claims=None)

    assert not machine.reports_session_claims()
    assert machine.unreported_sessions() == []


def test_the_card_line_names_the_person_and_the_origin(qtbot):
    """Der sichtbare Ertrag: Name statt gemeinsamem Konto, plus Herkunft."""
    from portal_app.ui.widgets.workstation_cards import WorkstationCard

    becker = person("a@x.de", "Becker")
    machine = workstation([claim_of(becker)])
    card = WorkstationCard(machine, person("b@x.de", "Kollege"))
    qtbot.addWidget(card)

    assert card.session_label.text() == "Belegt von Becker · über Portal"


def test_without_a_report_the_card_falls_back_to_the_account(qtbot):
    from portal_app.ui.widgets.workstation_cards import WorkstationCard

    machine = workstation(claims=[])
    card = WorkstationCard(machine, person("b@x.de", "Kollege"))
    qtbot.addWidget(card)

    assert card.session_label.text() == f"Belegt von {SHARED_ACCOUNT} · direkt verbunden"


def test_an_older_agent_gets_no_origin_claim_on_the_card(qtbot):
    """Offen lassen ist ehrlicher, als "direkt verbunden" zu behaupten."""
    from portal_app.ui.widgets.workstation_cards import WorkstationCard

    card = WorkstationCard(workstation(claims=None), person("b@x.de", "Kollege"))
    qtbot.addWidget(card)

    assert card.session_label.text() == f"Belegt von {SHARED_ACCOUNT}"


# --- Ein gemeinsames Konto, wechselnde Personen ------------------------------
#
# Der gemeldete Fehler: Nach dem Abmelden stand die Maschine als "belegt durch
# einen Kollegen" -- und schon davor, als noch gar niemand verbunden war. Eine
# einmal gebundene Meldung hatte sich an jede spätere Sitzung desselben Kontos
# gehängt. Auf einer Maschine, auf der sich alle unter demselben Windows-Konto
# anmelden, ist das nicht der Ausnahmefall, sondern der Normalfall.


def test_a_claim_does_not_latch_onto_the_next_persons_session(store):
    becker = person("a@x.de", "Becker")
    store.claim(build_claim(becker, SHARED_ACCOUNT))
    store.bind_and_expire([session(session_id=3, login="2026-09-17T08:00:00+00:00")])

    # Becker meldet sich ab, der Kollege meldet sich unter demselben Konto an.
    spaeter = [session(session_id=7, login="2026-09-17T16:00:00+00:00")]

    assert store.bind_and_expire(spaeter) == []


def test_a_recycled_session_number_is_not_the_same_session(store):
    """Windows vergibt Sitzungsnummern neu -- der Zeitpunkt entscheidet mit."""
    store.claim(build_claim(person("a@x.de", "Becker"), SHARED_ACCOUNT))
    store.bind_and_expire([session(session_id=3, login="2026-09-17T08:00:00+00:00")])

    gleiche_nummer = [session(session_id=3, login="2026-09-17T16:00:00+00:00")]

    assert store.bind_and_expire(gleiche_nummer) == []


def test_the_same_session_keeps_its_claim(store):
    """Eine laufende Sitzung darf ihre Meldung natürlich behalten."""
    store.claim(build_claim(person("a@x.de", "Becker"), SHARED_ACCOUNT))
    laufend = session(session_id=3, login="2026-09-17T08:00:00+00:00")
    store.bind_and_expire([laufend])

    kept = store.bind_and_expire([laufend])

    assert len(kept) == 1
    assert kept[0]["owner_upn"] == "a@x.de"


def test_the_new_person_gets_the_machine_after_a_handover(store):
    """Nach der Übergabe steht dort die Person, die wirklich davor sitzt."""
    store.claim(build_claim(person("a@x.de", "Becker"), SHARED_ACCOUNT))
    store.bind_and_expire([session(session_id=3, login="2026-09-17T08:00:00+00:00")])

    neue_sitzung = session(session_id=7, login="2026-09-17T16:00:00+00:00")
    store.claim(build_claim(person("b@x.de", "Kollege"), SHARED_ACCOUNT))
    kept = store.bind_and_expire([neue_sitzung])

    assert len(kept) == 1
    assert kept[0]["owner_display"] == "Kollege"
    assert kept[0]["session_id"] == 7
