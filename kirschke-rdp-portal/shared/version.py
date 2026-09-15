"""The one place the portal and agent versions are defined.

Before this, the portal version existed in four files (plus two that still said
0.1.0) and the agent version was hardcoded in six, two of which fell back to
1.0.0 and stamped that into event records.  Everything that reports a version
imports it from here.

``portal_app.version`` re-exports PORTAL_VERSION so existing imports keep working.
"""

from __future__ import annotations

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
PORTAL_VERSION = "0.3.10"
# 1.4.0: every reported session carries its account SID, so the portal no longer
# has to resolve Entra names against a cache that may not know them.
AGENT_VERSION = "1.4.3"

__all__ = ["AGENT_VERSION", "PORTAL_VERSION"]
