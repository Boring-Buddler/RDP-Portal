"""Visible pilot release identifier, also included in support reports.

Defined in ``shared.version`` so the portal, the agent and the installers cannot
drift apart; re-exported here because this is the established import path.
"""

from shared.version import PORTAL_VERSION

__all__ = ["PORTAL_VERSION"]
