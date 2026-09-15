"""The one place the portal and agent versions are defined.

Before this, the portal version existed in four files (plus two that still said
0.1.0) and the agent version was hardcoded in six, two of which fell back to
1.0.0 and stamped that into event records.  Everything that reports a version
imports it from here.

``portal_app.version`` re-exports PORTAL_VERSION so existing imports keep working.
"""

from __future__ import annotations

# 0.6.1: both setup windows name the version they are about to install. The
# portal setup had the number hardcoded and it had gone three versions stale --
# it offered to install 0.2.12 while 0.5.x sat in the package. Along the way:
# every PowerShell script with German text now carries a byte order mark, without
# which Windows PowerShell 5.1 reads the file as ANSI and mangles it -- an en dash
# then even breaks the parser.
# 0.6.0: the SharePoint folder is no longer the default storage location. It was
# a guess about how one person's OneDrive is laid out, and it failed differently
# on every PC that did not match -- refused halfway up the profile, or refused
# inside a synced library the account may not write to. The portal now stores
# locally unless a shared folder is set in the admin area, and an installation
# that already keeps its state in the old folder keeps finding it there.
# 0.5.5: the shared storage folder is used only when the synchronised library is
# actually present. The profile part always came from %USERPROFILE%; the folder
# chain under it was the assumption that broke. Creating it anyway produced a
# look-alike that never syncs, so everyone would believe they share a state that
# in truth exists once per machine. Without the library the portal stays local.
# 0.5.4: two things that made the portal unusable on a colleague's PC. The setup
# started PowerShell without -ExecutionPolicy Bypass, so a machine whose policy
# forbids scripts refused to install -- as administrator too, with a message that
# reads like a rights problem. And the first run died with an unhandled traceback
# when the configured storage folder could not be created: it now falls back to a
# local folder and says so, instead of never showing a window.
# 0.5.3: your own session without a window is now blue/orange dashed instead of
# solid orange, so the orange dash means one thing everywhere -- somebody holds
# the machine without being connected -- while the base colour says who. Border
# weight still follows what you can act on: four pixels for yours, two for a
# colleague's. Also: the quick resolution list now reaches 2K and 4K, but only as far as
# the screen in front of you goes -- a session larger than the panel is only
# reachable by scrolling. A panel whose size is not one of the standard steps
# joins the list as its own entry, so 'as large as this screen allows' can be
# picked at all.
# 0.5.2: the same account name in two Unicode spellings no longer counts as two
# people. Windows reports 'Schaelike' with a precomposed umlaut in one place and
# with a combining diaeresis in another; they look identical and never compared
# equal, so a person's own machine stayed marked as occupied by a stranger even
# after entering the account exactly as displayed. Also: a stored 'Anmelden als'
# choice is kept even when no session currently reports it, instead of silently
# falling back to the default; and 'Das bin ich' moved to the detail page.
# 0.5.1: the portal now also remembers the spelling the agent reports for a
# session it opened itself. Remembering only the account it connects with was
# useless for Entra, where the UPN and the reported profile name share nothing
# -- a person's own machine kept showing up as occupied by a stranger.
# 0.5.0: the automatic target no longer insists on a name that cannot be
# resolved -- across two sites a short Windows name has no chance, and RDP
# failed on it while the IP address next to it worked. The same check now
# guards the agent channel, whose server name comes from the fallback share.
# Also: a foreign session whose window is closed is drawn violet/orange
# dashed, and one click records a reported account as your own.
# 0.4.1: the machine card is a fixed 4:3 tile instead of stretching across the
# window, and carries a quick choice of resolution and all-monitors right next
# to the name. A checkbox outside a dialog was unstyled in the light theme.
# 0.4.0: reservations travel through each machine's own agent, so a portal on
# another PC sees a booking without a shared state file. Also: a real Windows
# application icon, the machine card shows the site instead of repeating the
# name, adding a machine lives in the admin area only, and the calendar is
# readable in both themes.
# 1.5.0 (agent): RESERVE/1 -- the agent keeps its own machine's reservations
# and reports them with every snapshot. Older agents report none, which the
# portal distinguishes from "none booked".
# 0.3.9: an account entered under "Weitere eigene Windows-Konten" now also
# passes the portal's ownership check for a logoff. The agent still requires
# the request to come from the machine that opened the session.
# 0.3.10: a console session can now be ended after a short RDP takeover, and
# 1.4.3 (agent): the same machine is recognised across IPv4, IPv6 and its name,
# so a logoff from exactly the right computer is no longer refused.
# 1.4.2 (agent): a refused logoff now names the requesting machine and the one
# that built the session, instead of only stating that they differ.
# 1.4.1 (agent setup): an update pre-fills the machine ID, status folder and
# interval from the installed agent instead of resetting them to the host name.
# 0.3.8: the detail page now shows the agent version and, per session, whether
# it is the console and which RDP client the agent reports -- the two facts a
# refused logoff turns on, and both were invisible.
# 0.3.7: violet moved into the middle of the only gap on the colour wheel, and
# weight now follows what you can act on: full border for usable machines,
# a quieter one for everything you cannot touch.
# 0.3.6: violet for a machine somebody else holds -- brown and amber both sat
# too close to the orange of your own idle session on a card border.
# 0.3.5: one rule for "is this the agent of this machine" -- the status channel
# and the logoff path no longer disagree about a generated portal ID.
# 0.3.4: brown for every machine somebody else holds (signed in or booked),
# blue only for your own. "Berechnung laeuft" retired; reservations replace it.
# 0.3.3: raise an already running RDP window instead of refusing, and recognise
# further Windows accounts as your own so a local account is not a stranger.
# 0.3.2: brown for a running calculation, and a colour key under the grid.
# 0.3.1: one machine state decides colour and buttons; orange marks an own session
# holding a machine with no portal window, violet a foreign reservation.
# 0.3.0: typed Windows identity, SID-based session ownership, one button matrix.
PORTAL_VERSION = "0.6.1"
# 1.4.0: every reported session carries its account SID, so the portal no longer
# has to resolve Entra names against a cache that may not know them.
AGENT_VERSION = "1.5.0"

__all__ = ["AGENT_VERSION", "PORTAL_VERSION"]
