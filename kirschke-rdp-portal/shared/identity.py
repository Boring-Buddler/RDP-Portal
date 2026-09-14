r"""One typed Windows identity instead of four loose name strings.

Windows names the same person in several ways, and each form is produced by a
different layer:

* ``DOMAIN\user`` -- the down-level name.  WTS reports it for a session, and
  ``whoami`` prints it for the portal process.  For Entra accounts the domain is
  the pseudo-domain ``AzureAD`` and the account part is the *profile* name, so it
  is a display name and nothing more.
* ``user@domain.tld`` -- the UPN.  This is what a person types and what the Entra
  sign-in uses; an .rdp file needs it, carrying the ``AzureAD\`` prefix when the
  target authenticates the account classically.
* ``S-1-...`` -- the SID.  This is the only form Windows actually authorizes
  against: group membership and user rights store SIDs, and the readable names in
  ``Get-LocalGroupMember`` are just a reverse lookup.

Resolving a name to a SID is local and cache dependent for Entra accounts -- it
succeeds only where that account is already known.  That is why this module keeps
the forms apart instead of normalising them into one string, and why
:meth:`WindowsIdentity.matches` reports *how* two identities matched rather than
just whether they did.  A name comparison is a display hint; only a SID
comparison may gate a security decision, and no comparison performed here is a
substitute for Windows authenticating the caller.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from shared.session_identity import session_username

#: Pseudo-domain Windows uses to push Entra identities through APIs that predate
#: them and insist on ``DOMAIN\user``.
ENTRA_DOMAIN = "AzureAD"

#: Entra account SIDs are derived from the Entra object GUID and always start here.
ENTRA_SID_PREFIX = "S-1-12-1-"


class IdentityMatch(Enum):
    """How -- and how convincingly -- two identities were found to be the same."""

    NO = "no"
    #: Names agree but no SID was available on both sides.  Good enough to label a
    #: card "your session", never good enough to authorize anything.
    BY_NAME_UNVERIFIED = "by_name_unverified"
    #: Both sides carried a SID and the SIDs are equal.
    BY_SID = "by_sid"

    def __bool__(self) -> bool:
        return self is not IdentityMatch.NO

    @property
    def is_proof(self) -> bool:
        """Whether this match rests on the one form Windows authorizes against."""
        return self is IdentityMatch.BY_SID


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


@dataclass(frozen=True)
class WindowsIdentity:
    """The known name forms of one Windows account, kept apart on purpose."""

    sid: str | None = None
    down_level: str | None = None
    upn: str | None = None

    @classmethod
    def from_names(
        cls,
        down_level: Any = None,
        sid: Any = None,
        upn: Any = None,
    ) -> WindowsIdentity:
        r"""Build an identity, sorting each supplied spelling into its own field.

        Two shapes carry a UPN without being handed one: a bare ``user@domain``
        is a UPN and not a down-level name at all, and ``AzureAD\user@domain`` is
        the down-level *and* the UPN at once.  Recognising both here is what lets
        :meth:`for_rdp_username` switch between the two Entra spellings later.
        """
        name = _clean(down_level)
        resolved_upn = _clean(upn)
        if name and resolved_upn is None and "@" in name:
            domain, separator, account = name.partition("\\")
            if not separator:
                name, resolved_upn = None, name
            elif domain.casefold() == ENTRA_DOMAIN.casefold() and "@" in account:
                resolved_upn = account
        return cls(sid=_clean(sid), down_level=name, upn=resolved_upn)

    @classmethod
    def from_session(cls, session: Mapping[str, Any]) -> WindowsIdentity:
        """Build an identity from one session as the agent reported it."""
        return cls.from_names(
            down_level=session_username(session),
            sid=session.get("sid"),
            upn=session.get("upn"),
        )

    @property
    def domain(self) -> str | None:
        """The down-level domain part, or ``None`` when no down-level name is known."""
        if not self.down_level or "\\" not in self.down_level:
            return None
        return self.down_level.split("\\", 1)[0] or None

    @property
    def account(self) -> str | None:
        """The down-level account part, without its domain."""
        if not self.down_level:
            return None
        return self.down_level.rsplit("\\", 1)[-1] or None

    @property
    def is_entra(self) -> bool:
        """Whether this is a Microsoft Entra account rather than a local or AD one."""
        if self.sid and self.sid.upper().startswith(ENTRA_SID_PREFIX.upper()):
            return True
        domain = self.domain
        return bool(domain and domain.casefold() == ENTRA_DOMAIN.casefold())

    def for_display(self) -> str:
        """The form a person recognises.  Never use this to decide anything."""
        return self.down_level or self.upn or ""

    def for_rdp_username(self, *, aad_auth: bool = False) -> str | None:
        r"""The account name to write into an .rdp file.

        With ``enablerdsaadauth:i:1`` Windows runs the Entra web sign-in and wants
        the plain UPN.  Without it the same Entra account has to be named through
        the compatibility pseudo-domain, ``AzureAD\user@domain.tld``, or Windows
        authenticates something else and the target refuses the remote logon.
        """
        if not self.is_entra:
            return self.down_level or self.upn
        if aad_auth:
            return self.upn or self.down_level
        if self.upn:
            return ENTRA_DOMAIN + "\\" + self.upn
        return self.down_level

    def comparable_names(self) -> set[str]:
        """Every spelling that should be treated as naming this same account."""
        names = {self.down_level, self.upn, self.account}
        if self.upn:
            names.add(ENTRA_DOMAIN + "\\" + self.upn)
        return {name.casefold() for name in names if name}

    def matches(self, other: WindowsIdentity | None) -> IdentityMatch:
        """Compare against another identity, reporting which form decided it."""
        if other is None:
            return IdentityMatch.NO
        if self.sid and other.sid:
            # A SID is available on both sides, so it decides -- including when it
            # says no.  Falling back to names here would let a stale or wrongly
            # resolved name override the only authoritative form.
            return (
                IdentityMatch.BY_SID
                if self.sid.casefold() == other.sid.casefold()
                else IdentityMatch.NO
            )
        if self.comparable_names() & other.comparable_names():
            return IdentityMatch.BY_NAME_UNVERIFIED
        return IdentityMatch.NO


def entra_rdp_username(account: str | None, *, aad_auth: bool = False) -> str | None:
    r"""Apply the Entra naming rule to one configured account name.

    The portal stores whatever account a person picked for a machine, and a bare
    UPN carries no domain to recognise it by -- so the *caller* decides that this
    machine authenticates Entra accounts, and this applies the spelling rule.  A
    name already qualified for some other domain is left untouched.
    """
    name = _clean(account)
    if not name:
        return None
    identity = WindowsIdentity.from_names(down_level=name)
    if identity.down_level and not identity.is_entra:
        return identity.down_level
    if identity.upn:
        return identity.upn if aad_auth else ENTRA_DOMAIN + "\\" + identity.upn
    return identity.down_level or name


__all__ = [
    "ENTRA_DOMAIN",
    "ENTRA_SID_PREFIX",
    "IdentityMatch",
    "WindowsIdentity",
    "entra_rdp_username",
]
