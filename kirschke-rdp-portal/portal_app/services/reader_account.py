r"""The read-only ``PortalLeser`` account the agent setup creates on every target.

This account is what the portal authenticates as when it reads a machine's status
share and when it opens the agent's named pipe.  It is a *Windows* account on
each target, so unlike the portal admin password -- which ships only as a PBKDF2
hash, because verifying a typed password is all it has to do -- this one has to
be available in clear text: an SMB logon cannot be performed with a hash.

That difference is the whole reason this module exists separately, and it is the
cost of shipping the password with the release: anybody who has the portal
program can read it out, and with it read the status folder of every workstation.
The account is deliberately narrow -- read-only on one folder, and denied
interactive, remote-interactive, batch and service logon by the agent setup --
so that is the whole of what leaks.  It is not an administrator and cannot sign
anyone off.

The repository ships **no** password. ``BUNDLED_READER_PASSWORD`` is filled in
when a release is built, the same way ``_ADMIN_PASSWORD_HASH`` is maintained in
:mod:`portal_app.services.admin_security`.  With it empty, every machine simply
asks once and Windows remembers the answer, which is the behaviour without any
rollout secret at all.

Precedence, highest first:

1. what this user already stored in the Windows credential manager, because a
   person correcting a password must not be overruled by the release;
2. the bundled password, so a standard rollout needs no typing at all;
3. nothing -- the assistant asks.
"""

from __future__ import annotations

#: Account name the agent setup creates. Local to each target, hence unqualified.
DEFAULT_READER_ACCOUNT = "PortalLeser"

#: Password shipped with the release. Empty in the repository on purpose --
#: filling it in is a release step, not a source change. See the module
#: docstring for what shipping it does and does not expose.
BUNDLED_READER_PASSWORD = "Kirschke"

#: Account the bundled password belongs to.
BUNDLED_READER_ACCOUNT = DEFAULT_READER_ACCOUNT


def bundled_credentials() -> tuple[str, str] | None:
    """The release's own reader account, or None when none was built in."""
    account = (BUNDLED_READER_ACCOUNT or "").strip()
    password = BUNDLED_READER_PASSWORD or ""
    return (account, password) if account and password else None


def has_bundled_password() -> bool:
    """Whether this build can connect a share without asking anybody."""
    return bundled_credentials() is not None


__all__ = [
    "BUNDLED_READER_ACCOUNT",
    "BUNDLED_READER_PASSWORD",
    "DEFAULT_READER_ACCOUNT",
    "bundled_credentials",
    "has_bundled_password",
]
