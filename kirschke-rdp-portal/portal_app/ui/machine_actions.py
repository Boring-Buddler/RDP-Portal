"""One decision about what a machine looks like and which buttons it offers.

Colour and buttons used to be decided in three places -- the card's accent, the
card's action row, and the detail page -- with three copies of the same
conditions.  They drifted: the card hid its primary button entirely while an own
session was connected, which left a machine you were signed into with no way back
onto it, and every view had its own idea of which colour meant "busy".

There is exactly one state per machine, it decides both the colour and the
buttons, and it is computed here so the views cannot disagree.  Nothing here is a
permission: enablement mirrors what the connect handler and the agent will
actually allow, so a button never promises something the next step refuses.

The colours, in the order they are decided:

======================  ==========  ======================================
Zustand                 Farbe       Bedeutung
======================  ==========  ======================================
DISABLED                grau        im Portal deaktiviert
BLOCKED                 rot         Wartung oder gesperrt
UNKNOWN                 grau        Agent meldet keinen aktuellen Status
OWN_IDLE                orange      deine Sitzung laeuft ohne offenes Fenster
OCCUPIED_SELF           blau        deine Sitzung, Fenster offen
OCCUPIED_OTHER          violett     jemand anderes ist angemeldet
RESERVED                violett     fremde Reservierung, niemand angemeldet
AVAILABLE               gruen       frei -- auch bei eigener Reservierung
======================  ==========  ======================================
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtGui import QColor

from portal_app.models.user import User
from portal_app.models.workstation import Workstation
from portal_app.ui.design import Colors
from shared.enums import AgentStatus, ManualFlagType
from shared.identity import IdentityMatch
from shared.session_identity import is_console_session

#: Why a session the agent reports as local needs a detour before it can be ended.
CONSOLE_LOGOFF_HINT = (
    "Das ist eine lokale Konsolensitzung am Gerät selbst. Windows kann dem Agenten "
    "für sie keinen anfragenden Rechner bestätigen, deshalb lässt er die normale "
    "Abmeldung nicht zu."
)

#: Why the ownership label is a hint rather than a statement of fact.
UNVERIFIED_OWNER_HINT = (
    "Zuordnung über den Kontonamen, nicht über die Windows-SID. Der Agent meldet "
    "für diese Sitzung keine SID; die Abmeldung prüft die Berechtigung trotzdem "
    "eigenständig."
)


class MachineState(Enum):
    """The one state a machine is in, deciding both its colour and its buttons."""

    DISABLED = "disabled"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    OWN_IDLE = "own_idle"
    OCCUPIED_SELF = "occupied_self"
    OCCUPIED_OTHER = "occupied_other"
    RESERVED = "reserved"
    AVAILABLE = "available"


STATE_COLORS: dict[MachineState, QColor] = {
    MachineState.DISABLED: Colors.text_muted,
    MachineState.BLOCKED: Colors.error,
    MachineState.UNKNOWN: Colors.text_muted,
    MachineState.OWN_IDLE: Colors.attention,
    MachineState.OCCUPIED_SELF: Colors.info,
    MachineState.OCCUPIED_OTHER: Colors.taken,
    MachineState.RESERVED: Colors.taken,
    MachineState.AVAILABLE: Colors.success,
}

#: Button text per state.  ``None`` means the machine's own status wording is used,
#: so a flag reads verbatim on the button instead of being paraphrased.
STATE_BUTTONS: dict[MachineState, str | None] = {
    MachineState.DISABLED: "Deaktiviert",
    MachineState.BLOCKED: None,
    MachineState.UNKNOWN: "Verbinden (Status ungeprüft)",
    MachineState.OWN_IDLE: "Sitzung öffnen",
    MachineState.OCCUPIED_SELF: "Sitzung öffnen …",
    MachineState.OCCUPIED_OTHER: "Maschine besetzt",
    MachineState.RESERVED: "Maschine besetzt",
    MachineState.AVAILABLE: "Verbinden",
}

#: States whose primary button actually starts something.  Everything else only
#: explains why the machine cannot be used right now.
ACTIONABLE_STATES = frozenset(
    {
        MachineState.UNKNOWN,
        MachineState.AVAILABLE,
        MachineState.OWN_IDLE,
        MachineState.OCCUPIED_SELF,
    }
)


@dataclass(frozen=True)
class Emphasis:
    """How loudly one state is drawn: border width, and how opaque the accent is.

    Dimming happens through alpha rather than a darker or paler shade, because the
    portal runs in a light and a dark theme and alpha recedes towards whatever is
    actually behind the card.  Desaturating would have done the opposite on the
    dark theme: it moves a colour towards grey, which is *lighter* there.
    """

    width: int
    alpha: float = 1.0


#: Weight follows what you can do with a machine, so the grid reads by emphasis
#: before it reads by hue: free, yours, and the one you are quietly blocking are
#: drawn at full strength; everything you cannot act on steps back.  That also
#: gives a second, colour-independent signal for anyone who separates hues poorly.
STATE_EMPHASIS: dict[MachineState, Emphasis] = {
    MachineState.AVAILABLE: Emphasis(4),
    MachineState.OWN_IDLE: Emphasis(4),
    MachineState.OCCUPIED_SELF: Emphasis(4),
    MachineState.OCCUPIED_OTHER: Emphasis(2, 0.70),
    MachineState.RESERVED: Emphasis(2, 0.70),
    MachineState.BLOCKED: Emphasis(2, 0.70),
    MachineState.UNKNOWN: Emphasis(2, 0.70),
    MachineState.DISABLED: Emphasis(2, 0.70),
}

STATE_TOOLTIPS: dict[MachineState, str] = {
    MachineState.UNKNOWN: (
        "Der Agent hat keinen aktuellen Status gemeldet. Die Verbindung wird "
        "trotzdem aufgebaut; Windows entscheidet über die Anmeldung."
    ),
    MachineState.OWN_IDLE: (
        "Deine Sitzung läuft auf dieser Maschine, ohne dass ein Portal-Fenster "
        "offen ist — du belegst sie also möglicherweise unbemerkt."
    ),
    MachineState.OCCUPIED_SELF: (
        "Deine Sitzung läuft und ein vom Portal gestartetes RDP-Fenster ist offen."
    ),
    MachineState.OCCUPIED_OTHER: (
        "Eine andere Person ist an dieser Maschine angemeldet. Gehört dir das "
        "gemeldete Konto selbst, trage es unter Einstellungen → Weitere eigene "
        "Windows-Konten ein; die Sitzung gilt dann als deine."
    ),
}

#: The colour key shown under the machine grid.  Derived from the state table, so
#: a recoloured state cannot leave the legend explaining something untrue.  States
#: that share a colour share one entry: violet covers "signed in by somebody else"
#: and "booked by somebody else" alike, and grey covers unknown and disabled.
LEGEND: tuple[tuple[MachineState, str], ...] = (
    (MachineState.AVAILABLE, "Frei"),
    (MachineState.OCCUPIED_SELF, "Von dir belegt"),
    (MachineState.OWN_IDLE, "Deine Sitzung ohne offenes Fenster"),
    (MachineState.OCCUPIED_OTHER, "Von jemand anderem belegt oder reserviert"),
    (MachineState.BLOCKED, "Wartung oder gesperrt"),
    (MachineState.UNKNOWN, "Keine Verbindung"),
)


def legend_entries() -> list[tuple[QColor, str]]:
    """The colour key as colour/label pairs, in display order.

    Deliberately the full accent, not the emphasised one: the key names a colour,
    and an eight pixel dot at seventy percent would be the one thing on the page
    that is hard to see.
    """
    return [(STATE_COLORS[state], label) for state, label in LEGEND]


#: Dashboard order: free first, then what needs your attention, then the rest.
SORT_ORDER: dict[MachineState, int] = {
    MachineState.AVAILABLE: 0,
    MachineState.OWN_IDLE: 1,
    MachineState.OCCUPIED_SELF: 2,
    MachineState.OCCUPIED_OTHER: 3,
    MachineState.RESERVED: 4,
    MachineState.BLOCKED: 5,
    MachineState.UNKNOWN: 6,
    MachineState.DISABLED: 6,
}


def logoff_candidates(sessions: list[dict]) -> list[dict]:
    """Sessions identified precisely enough to ask the agent to end exactly them.

    Session ID and login time together are what makes a request unambiguous: a
    recycled ID alone would let a reused number end somebody else's session.
    """
    return [
        item
        for item in sessions
        if type(item.get("session_id")) is int
        and item["session_id"] > 0
        and item.get("login_time")
    ]


def machine_state(
    workstation: Workstation,
    user: User,
    *,
    window_open: bool = False,
) -> MachineState:
    """Decide the one state of ``workstation`` for ``user``, most specific first.

    A manual flag wins over everything but a machine switched off in the portal,
    because somebody set it deliberately and that must stay visible.  Reachability
    is read from the agent rather than from ping: an agent that answers proves the
    machine is reachable, while a ping only proves something answers ICMP.
    """
    if not workstation.enabled:
        return MachineState.DISABLED
    if workstation.manual_flag_type in (ManualFlagType.BLOCKED, ManualFlagType.MAINTENANCE):
        return MachineState.BLOCKED
    if workstation.manual_flag_type == ManualFlagType.CALCULATION_RUNNING:
        # Retired category. Nothing offers it any more, but stored states may still
        # carry it, and it still blocks can_connect -- so it is shown as taken
        # rather than as a colour of its own. Reservations replaced it.
        return MachineState.OCCUPIED_OTHER
    if workstation.agent_status != AgentStatus.ONLINE or workstation.agent_status_source == "none":
        return MachineState.UNKNOWN
    own = workstation.owned_sessions(user.windows_accounts())
    if own:
        # A console session never has a portal window, and it is the case where
        # you are holding the machine most visibly -- so it is always OWN_IDLE.
        if not window_open or any(is_console_session(item) for item in own):
            return MachineState.OWN_IDLE
        return MachineState.OCCUPIED_SELF
    if workstation.has_active_session():
        return MachineState.OCCUPIED_OTHER
    if workstation.reservation_block_reason:
        # Own reservations deliberately do not colour the card: they are a note,
        # not a blocker, and the machine is free for you to use.
        return MachineState.RESERVED
    return MachineState.AVAILABLE


def state_color(state: MachineState) -> QColor:
    """The card accent for one state, carrying that state's emphasis as alpha."""
    color = QColor(STATE_COLORS[state])
    color.setAlphaF(STATE_EMPHASIS[state].alpha)
    return color


def state_border_width(state: MachineState) -> int:
    """How thick the card border is drawn for one state."""
    return STATE_EMPHASIS[state].width


def css_color(color: QColor) -> str:
    """A Qt-stylesheet colour that keeps the alpha channel.

    ``QColor.name()`` drops alpha silently, which would have thrown the emphasis
    away at exactly the point where it is applied.
    """
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


@dataclass(frozen=True)
class MachineActions:
    """What one machine shows one user right now."""

    state: MachineState
    color: QColor
    primary_text: str
    primary_enabled: bool
    primary_tooltip: str
    logoff_visible: bool
    logoff_enabled: bool
    logoff_tooltip: str
    ownership: IdentityMatch
    own_sessions: list[dict]

    @property
    def owns_console_session(self) -> bool:
        """Whether the own session is local, which the normal logoff cannot end."""
        return any(is_console_session(item) for item in self.own_sessions)


def describe_actions(
    workstation: Workstation,
    user: User,
    *,
    window_open: bool = False,
) -> MachineActions:
    """Decide state, colour and buttons for ``workstation`` as ``user`` sees it.

    ``window_open`` says whether this portal already started an RDP client for the
    machine.  It is what separates "you are working on it" from "your session is
    quietly holding it".
    """
    accounts = user.windows_accounts()
    own = workstation.owned_sessions(accounts)
    ownership = workstation.owned_session_match(accounts)
    state = machine_state(workstation, user, window_open=window_open)

    # Logoff follows ownership alone.  A manual flag says the machine is busy, not
    # that the session stopped being yours; a foreign reservation does.
    candidates = logoff_candidates(own)
    console_only = bool(own) and all(is_console_session(item) for item in own)
    logoff_visible = bool(own) and not workstation.reservation_block_reason
    # A console session stays clickable: the agent still refuses it directly, but
    # the portal can offer the takeover that removes the obstacle, and the
    # administrative route. A disabled button could offer neither.
    logoff_enabled = logoff_visible and bool(candidates)
    if not logoff_visible:
        logoff_tooltip = ""
    elif console_only:
        logoff_tooltip = (
            CONSOLE_LOGOFF_HINT
            + " Das Portal bietet dir hier zwei Wege an: die Sitzung kurz per RDP "
            "übernehmen und dann abmelden, oder administrativ abmelden."
        )
    elif not candidates:
        logoff_tooltip = (
            "Der Agent hat für diese Sitzung noch keinen Anmeldezeitpunkt gemeldet. "
            "Ohne ihn lässt sich die Sitzung nicht eindeutig benennen."
        )
    elif ownership is IdentityMatch.BY_NAME_UNVERIFIED:
        logoff_tooltip = UNVERIFIED_OWNER_HINT
    else:
        logoff_tooltip = (
            "Der Agent prüft Sitzung, Anmeldezeit und Benutzerkennung erneut, "
            "bevor Windows abmeldet."
        )

    tooltip = STATE_TOOLTIPS.get(state, "")
    if state is MachineState.RESERVED:
        tooltip = workstation.reservation_message or tooltip
    return MachineActions(
        state=state,
        color=state_color(state),
        primary_text=STATE_BUTTONS[state] or workstation.get_status_display(),
        primary_enabled=state in ACTIONABLE_STATES,
        primary_tooltip=tooltip,
        logoff_visible=logoff_visible,
        logoff_enabled=logoff_enabled,
        logoff_tooltip=logoff_tooltip,
        ownership=ownership,
        own_sessions=own,
    )


__all__ = [
    "ACTIONABLE_STATES",
    "STATE_EMPHASIS",
    "Emphasis",
    "css_color",
    "state_border_width",
    "CONSOLE_LOGOFF_HINT",
    "SORT_ORDER",
    "STATE_BUTTONS",
    "STATE_COLORS",
    "UNVERIFIED_OWNER_HINT",
    "MachineActions",
    "MachineState",
    "describe_actions",
    "logoff_candidates",
    "machine_state",
    "state_color",
]
