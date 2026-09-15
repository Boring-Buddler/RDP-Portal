"""Farben und Buttons: ein Zustand je Maschine, in einer Tabelle festgehalten.

Diese Regeln gelten fuer Kartenraster und Detailseite gleichermassen.  Der Sinn
der Tests hier ist, dass kein Zustand ohne Primaerbutton erreichbar ist, dass
Farbe und Button nie auseinanderlaufen, und dass "Abmelden" nur dort aktiv ist,
wo der Agent die Abmeldung auch annimmt.
"""

import pytest

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.ui.design import Colors
from portal_app.ui.machine_actions import (
    ACTIONABLE_STATES,
    SORT_ORDER,
    STATE_BUTTONS,
    STATE_COLORS,
    STATE_EMPHASIS,
    MachineActions,
    MachineState,
    css_color,
    describe_actions,
    legend_entries,
    logoff_candidates,
    state_color,
)
from portal_app.ui.widgets.status_legend import StatusLegend
from shared.enums import AgentStatus, ManualFlagType, SessionState
from shared.identity import IdentityMatch

BACKSLASH = chr(92)
MY_NAME = "AzureAD" + BACKSLASH + "ChristianBecker"
MY_SID = "S-1-12-1-1-2-3-4"
OTHER_NAME = "AzureAD" + BACKSLASH + "SomeoneElse"


def user(*, sid: str | None = MY_SID) -> MockUser:
    person = MockUser.create_user()
    person.windows_identity = MY_NAME
    person.windows_sid = sid
    person.rdp_username = None
    person.rdp_domain = None
    return person


def session(
    *,
    name: str = MY_NAME,
    state: str = "connected",
    console: bool = False,
    sid: str | None = MY_SID,
    login_time: str | None = "2026-09-14T06:00:00+00:00",
) -> dict:
    return {
        "session_id": 2,
        "full_username": name,
        "session_state": state,
        "login_time": login_time,
        "is_console_session": console,
        "sid": sid,
    }


def machine(*, sessions: list[dict] | None = None, **kwargs) -> Workstation:
    """Eine erreichbare Maschine mit lebendem Agenten -- Standard heisst also frei."""
    sessions = sessions or []
    kwargs.setdefault("agent_status", AgentStatus.ONLINE)
    workstation = Workstation("W1", "NB05", "nb05", agent_sessions=sessions, **kwargs)
    workstation.agent_status_source = "live"
    if sessions:
        workstation.current_session_state = SessionState(sessions[0]["session_state"])
        workstation.current_session_user = sessions[0]["full_username"]
    return workstation


def actions(workstation: Workstation, **kwargs) -> MachineActions:
    return describe_actions(workstation, user(), **kwargs)


# --- die Farbtabelle ---------------------------------------------------------

#: Die vereinbarte Zuordnung, damit eine Farbaenderung auffaellt statt durchzurutschen.
EXPECTED_COLORS = {
    MachineState.DISABLED: Colors.text_muted,
    MachineState.UNKNOWN: Colors.text_muted,
    MachineState.BLOCKED: Colors.error,
    MachineState.AVAILABLE: Colors.success,
    MachineState.OCCUPIED_SELF: Colors.info,
    # Belegt und reserviert teilen sich Violett: die Frage "kann ich sie benutzen"
    # wird in beiden Faellen gleich beantwortet.
    MachineState.OCCUPIED_OTHER: Colors.taken,
    MachineState.RESERVED: Colors.taken,
    MachineState.OWN_IDLE: Colors.attention,
}


def test_every_state_has_exactly_the_agreed_colour() -> None:
    assert STATE_COLORS == EXPECTED_COLORS


def test_the_signal_colours_stay_distinguishable() -> None:
    """Grau, gruen, blau, orange, violett und rot nie derselbe Wert."""
    signals = [
        Colors.text_muted,
        Colors.success,
        Colors.info,
        Colors.attention,
        Colors.taken,
        Colors.error,
    ]
    assert len({color.name() for color in signals}) == len(signals)


def same_hue(drawn, base) -> bool:
    """Gleiche Farbe, unabhaengig von der Betonung.

    Der gezeichnete Akzent traegt die Betonung als Alpha, ist also nie dasselbe
    QColor-Objekt wie der Palettenwert -- verglichen wird deshalb der Farbwert.
    """
    return drawn.rgb() == base.rgb()


def hue_distance(first, second) -> int:
    """Kuerzester Abstand zweier Farbtoene auf dem Farbkreis, in Grad."""
    delta = abs(first.hue() - second.hue()) % 360
    return min(delta, 360 - delta)


def test_taken_keeps_a_real_distance_from_the_warm_tones() -> None:
    """Bernstein und Braun wurden beide verworfen, weil sie neben Orange verschwammen.

    Ungleiche Farbwerte reichen dafuer nicht -- entscheidend ist der Farbton, denn
    genau daran hat man die beiden Rahmen im Betrieb nicht auseinandergehalten.
    """
    for warm in (Colors.attention, Colors.warning):
        assert hue_distance(Colors.taken, warm) >= 90, warm.name()


def test_your_session_stays_apart_from_somebody_elses() -> None:
    """Die wichtigste Unterscheidung im Raster: benutzt du sie, oder jemand anderes.

    Violett sitzt bewusst in der Mitte der einzigen echten Luecke auf dem Farbkreis
    (Blau 208 Grad bis Rot 360 Grad) und haelt damit zu beiden Nachbarn etwa 75
    Grad Abstand, wo ein tieferes Violett nur 54 Grad zu Blau hatte.
    """
    assert hue_distance(Colors.info, Colors.taken) >= 60
    assert hue_distance(Colors.error, Colors.taken) >= 60


# --- Betonung ----------------------------------------------------------------


def test_what_you_can_act_on_is_drawn_at_full_strength() -> None:
    """Gewicht folgt der Handlungsfaehigkeit, nicht der Wichtigkeit des Zustands."""
    for state in ACTIONABLE_STATES - {MachineState.UNKNOWN}:
        assert STATE_EMPHASIS[state].width == 4, state
        assert STATE_EMPHASIS[state].alpha == 1.0, state


def test_what_you_cannot_use_steps_back() -> None:
    for state in (
        MachineState.OCCUPIED_OTHER,
        MachineState.RESERVED,
        MachineState.BLOCKED,
        MachineState.DISABLED,
    ):
        assert STATE_EMPHASIS[state].width == 2, state
        assert STATE_EMPHASIS[state].alpha < 1.0, state


def test_every_state_has_an_emphasis() -> None:
    for state in MachineState:
        assert state in STATE_EMPHASIS, state
        assert STATE_EMPHASIS[state].width in (2, 4), state


def test_the_drawn_accent_carries_the_emphasis_as_alpha() -> None:
    """QColor.name() wuerde das Alpha lautlos verschlucken -- deshalb css_color."""
    quiet = state_color(MachineState.OCCUPIED_OTHER)
    loud = state_color(MachineState.AVAILABLE)

    assert quiet.alpha() < 255
    assert loud.alpha() == 255
    assert f", {quiet.alpha()})" in css_color(quiet)
    assert css_color(loud).startswith("rgba(")


# --- Legende -----------------------------------------------------------------


def test_the_legend_explains_every_colour_that_can_appear() -> None:
    """Jede Farbe, die eine Karte annehmen kann, muss in der Legende stehen."""
    explained = {color.name() for color, _ in legend_entries()}
    shown = {color.name() for color in STATE_COLORS.values()}

    assert shown == explained


def test_the_legend_has_no_duplicate_colours_and_no_empty_labels() -> None:
    entries = legend_entries()

    assert len({color.name() for color, _ in entries}) == len(entries)
    assert all(label.strip() for _, label in entries)


def test_the_legend_markup_carries_each_colour_and_label() -> None:
    markup = StatusLegend.markup()

    for color, label in legend_entries():
        assert color.name() in markup
        assert label in markup


# --- Zustand je Maschine -----------------------------------------------------


@pytest.mark.parametrize(
    ("label", "workstation", "options", "expected"),
    [
        ("frei", machine(), {}, MachineState.AVAILABLE),
        (
            "eigene Reservierung faerbt nicht",
            machine(reservation_message="Für dich reserviert bis 17:00"),
            {},
            MachineState.AVAILABLE,
        ),
        (
            "fremde Reservierung, niemand angemeldet",
            machine(
                reservation_block_reason="Reserviert für Kollege",
                reservation_message="Reserviert für Kollege",
            ),
            {},
            MachineState.RESERVED,
        ),
        (
            "Agent offline",
            machine(agent_status=AgentStatus.OFFLINE),
            {},
            MachineState.UNKNOWN,
        ),
        (
            "eigene Sitzung, Fenster offen",
            machine(sessions=[session()]),
            {"window_open": True},
            MachineState.OCCUPIED_SELF,
        ),
        (
            "eigene Sitzung, Fenster zu",
            machine(sessions=[session()]),
            {},
            MachineState.OWN_IDLE,
        ),
        (
            "eigene Sitzung getrennt",
            machine(sessions=[session(state="disconnected")]),
            {},
            MachineState.OWN_IDLE,
        ),
        (
            "eigene Konsolensitzung",
            machine(sessions=[session(console=True)]),
            {},
            MachineState.OWN_IDLE,
        ),
        (
            "Kollege angemeldet",
            machine(sessions=[session(name=OTHER_NAME, sid=None)]),
            {},
            MachineState.OCCUPIED_OTHER,
        ),
        (
            "Wartung",
            machine(manual_flag_type=ManualFlagType.MAINTENANCE),
            {},
            MachineState.BLOCKED,
        ),
        (
            "gesperrt",
            machine(manual_flag_type=ManualFlagType.BLOCKED),
            {},
            MachineState.BLOCKED,
        ),
        (
            "Berechnung laeuft (abgeschaffte Kategorie, alte Daten)",
            machine(manual_flag_type=ManualFlagType.CALCULATION_RUNNING),
            {},
            MachineState.OCCUPIED_OTHER,
        ),
        ("deaktiviert", machine(enabled=False), {}, MachineState.DISABLED),
    ],
)
def test_state_per_machine(label, workstation, options, expected) -> None:
    assert actions(workstation, **options).state is expected, label


def test_a_console_session_stays_orange_even_with_a_portal_window() -> None:
    """Eine Konsolensitzung hat nie ein Portal-Fenster; sie belegt das Geraet."""
    result = actions(machine(sessions=[session(console=True)]), window_open=True)

    assert result.state is MachineState.OWN_IDLE


def test_a_manual_flag_beats_a_session_but_not_a_disabled_machine() -> None:
    flagged = machine(sessions=[session()], manual_flag_type=ManualFlagType.MAINTENANCE)
    assert actions(flagged).state is MachineState.BLOCKED

    flagged.enabled = False
    assert actions(flagged).state is MachineState.DISABLED


def test_a_session_beats_a_foreign_reservation() -> None:
    """Violett gilt nur, solange noch niemand angemeldet ist."""
    workstation = machine(sessions=[session(name=OTHER_NAME, sid=None)])
    workstation.reservation_block_reason = "Reserviert für Kollege"

    assert actions(workstation).state is MachineState.OCCUPIED_OTHER


# --- Buttons -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "text", "enabled"),
    [
        (MachineState.UNKNOWN, "Verbinden (Status ungeprüft)", True),
        (MachineState.AVAILABLE, "Verbinden", True),
        (MachineState.OCCUPIED_SELF, "Sitzung öffnen …", True),
        (MachineState.OWN_IDLE, "Sitzung öffnen", True),
        (MachineState.OCCUPIED_OTHER, "Maschine besetzt", False),
        (MachineState.RESERVED, "Maschine besetzt", False),
        (MachineState.DISABLED, "Deaktiviert", False),
    ],
)
def test_button_text_and_enablement_per_state(state, text, enabled) -> None:
    assert STATE_BUTTONS[state] == text
    assert (state in ACTIONABLE_STATES) is enabled


def test_a_flagged_machine_repeats_the_flag_verbatim_on_the_button() -> None:
    workstation = machine(manual_flag_type=ManualFlagType.MAINTENANCE)

    result = actions(workstation)

    assert result.primary_text == workstation.get_status_display() == "Wartung"
    assert not result.primary_enabled


def test_every_state_is_complete_and_offers_one_primary_button() -> None:
    """Die Regression, fuer die dieses Modul existiert: kein Zustand ohne Ausweg."""
    for state in MachineState:
        assert state in STATE_COLORS, state
        assert state in STATE_BUTTONS, state
        assert state in SORT_ORDER, state

    for workstation in [
        machine(),
        machine(enabled=False),
        machine(sessions=[session()]),
        machine(sessions=[session(state="disconnected")]),
        machine(sessions=[session(console=True)]),
        machine(sessions=[session(name=OTHER_NAME, sid=None)]),
        machine(reservation_block_reason="Fremd", reservation_message="Fremd"),
        machine(manual_flag_type=ManualFlagType.BLOCKED),
        machine(manual_flag_type=ManualFlagType.CALCULATION_RUNNING),
        machine(agent_status=AgentStatus.OFFLINE),
    ]:
        for window_open in (False, True):
            result = describe_actions(workstation, user(), window_open=window_open)
            assert result.primary_text
            assert same_hue(result.color, STATE_COLORS[result.state])


# --- Abmelden ----------------------------------------------------------------


def test_logoff_is_offered_for_an_own_rdp_session() -> None:
    result = actions(machine(sessions=[session(state="disconnected")]))

    assert result.logoff_visible
    assert result.logoff_enabled


def test_a_console_session_stays_clickable_and_explains_the_detour() -> None:
    """Der Agent lehnt sie direkt ab, aber das Portal kennt zwei Umwege dorthin.

    Frueher war der Button deaktiviert -- dann liess sich weder die Uebernahme noch
    die administrative Abmeldung von hier aus anstossen.
    """
    result = actions(machine(sessions=[session(console=True)]))

    assert result.logoff_visible
    assert result.logoff_enabled
    assert result.owns_console_session
    assert "Konsolensitzung" in result.logoff_tooltip
    assert "übernehmen" in result.logoff_tooltip
    assert "administrativ" in result.logoff_tooltip.lower()


def test_logoff_is_hidden_for_a_foreign_session() -> None:
    assert not actions(machine(sessions=[session(name=OTHER_NAME, sid=None)])).logoff_visible


def test_a_foreign_reservation_withdraws_the_logoff() -> None:
    workstation = machine(sessions=[session()])
    workstation.reservation_block_reason = "Fremd reserviert"

    assert not actions(workstation).logoff_visible


def test_a_manual_flag_does_not_take_away_your_own_session() -> None:
    workstation = machine(sessions=[session()], manual_flag_type=ManualFlagType.CALCULATION_RUNNING)

    result = actions(workstation)

    assert result.logoff_visible
    assert result.logoff_enabled


def test_a_session_without_a_login_time_cannot_be_named_precisely() -> None:
    result = actions(machine(sessions=[session(login_time=None)]))

    assert result.logoff_visible
    assert not result.logoff_enabled
    assert "Anmeldezeitpunkt" in result.logoff_tooltip


@pytest.mark.parametrize("session_id", [0, -1, None, "2", True])
def test_only_a_real_session_number_counts_as_addressable(session_id) -> None:
    """bool ist eine int-Unterklasse und darf hier trotzdem nicht durchgehen."""
    assert logoff_candidates([dict(session(), session_id=session_id)]) == []


# --- Zuordnung ---------------------------------------------------------------


def test_ownership_by_sid_is_reported_as_proof() -> None:
    result = actions(machine(sessions=[session()]))

    assert result.ownership is IdentityMatch.BY_SID
    assert result.ownership.is_proof


def test_ownership_by_name_alone_is_marked_unverified() -> None:
    """Ein aelterer Agent meldet keine SID; die Sitzung wird trotzdem gezeigt."""
    result = describe_actions(machine(sessions=[session(sid=None)]), user(sid=None))

    assert result.ownership is IdentityMatch.BY_NAME_UNVERIFIED
    assert result.logoff_enabled
    assert "SID" in result.logoff_tooltip


def test_a_matching_name_with_a_different_sid_is_not_your_session() -> None:
    result = actions(machine(sessions=[session(sid="S-1-12-1-9-9-9-9")]))

    assert result.ownership is IdentityMatch.NO
    assert not result.logoff_visible
    assert result.state is MachineState.OCCUPIED_OTHER


# --- Weitere eigene Konten ---------------------------------------------------


def claiming_user(account: str) -> MockUser:
    person = user()
    person.own_accounts = [account]
    return person


def test_a_foreign_looking_session_becomes_yours_once_the_account_is_claimed() -> None:
    """Der Fall, der den Benutzer aus seiner eigenen Maschine ausgesperrt hat."""
    local_account = "NB12KI" + BACKSLASH + "Codex"
    workstation = machine(sessions=[session(name=local_account, sid=None)])

    locked_out = describe_actions(workstation, user())
    assert locked_out.state is MachineState.OCCUPIED_OTHER
    assert not locked_out.primary_enabled

    claimed = describe_actions(workstation, claiming_user(local_account))
    assert claimed.state is MachineState.OWN_IDLE
    assert claimed.primary_enabled
    assert claimed.logoff_visible


def test_a_claimed_account_is_a_name_match_and_says_so() -> None:
    """Eine Zuordnung ist eine Behauptung, kein Beweis -- das muss sichtbar bleiben."""
    local_account = "NB12KI" + BACKSLASH + "Codex"
    workstation = machine(sessions=[session(name=local_account, sid=None)])

    result = describe_actions(workstation, claiming_user(local_account))

    assert result.ownership is IdentityMatch.BY_NAME_UNVERIFIED
    assert not result.ownership.is_proof


def test_claiming_an_unrelated_account_changes_nothing() -> None:
    workstation = machine(sessions=[session(name=OTHER_NAME, sid=None)])

    result = describe_actions(workstation, claiming_user("NB12KI" + BACKSLASH + "Codex"))

    assert result.state is MachineState.OCCUPIED_OTHER
    assert not result.logoff_visible


def test_the_occupied_tooltip_points_at_the_setting_that_fixes_it() -> None:
    result = actions(machine(sessions=[session(name=OTHER_NAME, sid=None)]))

    assert "Weitere eigene" in result.primary_tooltip


def test_claim_account_is_idempotent_and_rejects_junk() -> None:
    person = user()

    assert person.claim_account("NB12KI" + BACKSLASH + "Codex") is True
    assert person.claim_account("nb12ki" + BACKSLASH + "codex") is False
    assert person.claim_account(person.windows_identity) is False
    assert person.claim_account("") is False
    assert person.claim_account(None) is False
    # validate_login_account lehnt Steuerzeichen und unmoegliche Formen ab.
    assert person.claim_account("zwei" + BACKSLASH + "back" + BACKSLASH + "slashes") is False
    assert person.own_accounts == ["NB12KI" + BACKSLASH + "Codex"]


# --- Abgeschaffte Kategorie "Berechnung laeuft" ------------------------------


def test_no_state_is_called_calculating_any_more() -> None:
    """Die Kategorie ist gestrichen; Reservierungen sagen dasselbe besser."""
    assert not any(state.name == "CALCULATING" for state in MachineState)
    assert all("Berechnung" not in label for _, label in legend_entries())


def test_an_old_stored_calculation_flag_is_shown_as_taken() -> None:
    """Gespeicherte Staende duerfen davon nicht kaputtgehen."""
    workstation = machine(manual_flag_type=ManualFlagType.CALCULATION_RUNNING)

    result = actions(workstation)

    assert result.state is MachineState.OCCUPIED_OTHER
    assert same_hue(result.color, Colors.taken)
    assert not result.primary_enabled


def test_flagging_is_administrative_only() -> None:
    """Normale Benutzer konnten frueher "Berechnung laeuft" setzen -- jetzt nicht mehr."""
    workstation = machine()

    for flag in ManualFlagType:
        assert workstation.can_set_flag(flag, is_admin=False) is False
        assert workstation.can_set_flag(flag, is_admin=True) is True


def test_taken_covers_both_a_foreign_session_and_a_foreign_reservation() -> None:
    occupied = actions(machine(sessions=[session(name=OTHER_NAME, sid=None)]))
    reserved = actions(machine(reservation_block_reason="x", reservation_message="x"))

    assert same_hue(occupied.color, Colors.taken)
    assert same_hue(reserved.color, Colors.taken)
    assert occupied.primary_text == reserved.primary_text == "Maschine besetzt"


def test_your_own_session_is_blue_and_a_foreign_one_is_violet() -> None:
    """Der Unterschied, auf den es beim Blick aufs Dashboard ankommt."""
    mine = actions(machine(sessions=[session()]), window_open=True)
    theirs = actions(machine(sessions=[session(name=OTHER_NAME, sid=None)]))

    assert same_hue(mine.color, Colors.info)
    assert same_hue(theirs.color, Colors.taken)
    assert mine.color.name() != theirs.color.name()
