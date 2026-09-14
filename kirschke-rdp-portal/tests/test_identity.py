"""The four Windows name forms, kept apart, and the rule that compares them."""

import pytest

from shared.identity import (
    ENTRA_DOMAIN,
    IdentityMatch,
    WindowsIdentity,
    entra_rdp_username,
)

BACKSLASH = chr(92)
ENTRA_DOWN_LEVEL = ENTRA_DOMAIN + BACKSLASH + "ChristianBecker"
ENTRA_UPN = "becker@prof-kirschke.de"
ENTRA_QUALIFIED = ENTRA_DOMAIN + BACKSLASH + ENTRA_UPN


@pytest.mark.parametrize(
    ("spelling", "down_level", "upn"),
    [
        (ENTRA_DOWN_LEVEL, ENTRA_DOWN_LEVEL, None),
        # A bare UPN is a UPN, not a down-level name with an empty domain.
        (ENTRA_UPN, None, ENTRA_UPN),
        # AzureAD\upn is both at once, which is what lets the .rdp spelling switch.
        (ENTRA_QUALIFIED, ENTRA_QUALIFIED, ENTRA_UPN),
        ("KIRSCHKE" + BACKSLASH + "becker", "KIRSCHKE" + BACKSLASH + "becker", None),
        ("", None, None),
        (None, None, None),
    ],
)
def test_each_spelling_lands_in_its_own_field(spelling, down_level, upn) -> None:
    identity = WindowsIdentity.from_names(spelling)
    assert identity.down_level == down_level
    assert identity.upn == upn


@pytest.mark.parametrize(
    ("spelling", "is_entra"),
    [
        (ENTRA_DOWN_LEVEL, True),
        (ENTRA_QUALIFIED, True),
        ("azuread" + BACKSLASH + "someone", True),
        ("KIRSCHKE" + BACKSLASH + "becker", False),
        (ENTRA_UPN, False),  # a bare UPN carries no domain to recognise
    ],
)
def test_entra_accounts_are_recognised_by_their_domain(spelling, is_entra) -> None:
    assert WindowsIdentity.from_names(spelling).is_entra is is_entra


def test_an_entra_sid_identifies_the_account_even_without_a_domain() -> None:
    assert WindowsIdentity.from_names("becker", sid="S-1-12-1-1-2-3-4").is_entra is True


def test_a_sid_decides_the_comparison_in_both_directions() -> None:
    """Equal SIDs match despite different names; different SIDs never match."""
    same = WindowsIdentity.from_names(ENTRA_DOWN_LEVEL, sid="S-1-12-1-1-2-3-4")
    renamed = WindowsIdentity.from_names(
        ENTRA_DOMAIN + BACKSLASH + "Someone.Else", sid="s-1-12-1-1-2-3-4"
    )
    impostor = WindowsIdentity.from_names(ENTRA_DOWN_LEVEL, sid="S-1-12-1-9-9-9-9")

    assert same.matches(renamed) is IdentityMatch.BY_SID
    assert same.matches(renamed).is_proof
    # Same readable name, different account: the name must not rescue this.
    assert same.matches(impostor) is IdentityMatch.NO
    assert not same.matches(impostor)


def test_without_sids_a_name_match_is_reported_as_unverified() -> None:
    mine = WindowsIdentity.from_names("azuread" + BACKSLASH + "christianbecker")
    theirs = WindowsIdentity.from_names(ENTRA_DOWN_LEVEL)

    match = mine.matches(theirs)

    assert match is IdentityMatch.BY_NAME_UNVERIFIED
    assert match  # good enough to label a card
    assert not match.is_proof  # never good enough to authorize


def test_one_sided_sid_degrades_to_the_name_comparison() -> None:
    with_sid = WindowsIdentity.from_names(ENTRA_DOWN_LEVEL, sid="S-1-12-1-1-2-3-4")
    without = WindowsIdentity.from_names(ENTRA_DOWN_LEVEL)

    assert with_sid.matches(without) is IdentityMatch.BY_NAME_UNVERIFIED


def test_the_qualified_and_bare_upn_name_the_same_account() -> None:
    assert (
        WindowsIdentity.from_names(ENTRA_QUALIFIED).matches(
            WindowsIdentity.from_names(ENTRA_UPN)
        )
        is IdentityMatch.BY_NAME_UNVERIFIED
    )


def test_nothing_matches_a_missing_identity() -> None:
    assert WindowsIdentity.from_names(ENTRA_DOWN_LEVEL).matches(None) is IdentityMatch.NO


@pytest.mark.parametrize(
    ("account", "classic", "aad"),
    [
        # The whole point: without the web sign-in the UPN needs the pseudo-domain.
        (ENTRA_UPN, ENTRA_QUALIFIED, ENTRA_UPN),
        (ENTRA_QUALIFIED, ENTRA_QUALIFIED, ENTRA_UPN),
        # No UPN known, so the display name is the best available spelling.
        (ENTRA_DOWN_LEVEL, ENTRA_DOWN_LEVEL, ENTRA_DOWN_LEVEL),
        # Another domain is none of our business.
        ("KIRSCHKE" + BACKSLASH + "becker",) * 3,
        ("becker",) * 3,
        (None, None, None),
        ("", None, None),
    ],
)
def test_entra_rdp_username_applies_the_spelling_rule(account, classic, aad) -> None:
    assert entra_rdp_username(account) == classic
    assert entra_rdp_username(account, aad_auth=True) == aad


def test_display_never_invents_a_name() -> None:
    assert WindowsIdentity.from_names(ENTRA_DOWN_LEVEL).for_display() == ENTRA_DOWN_LEVEL
    assert WindowsIdentity.from_names(ENTRA_UPN).for_display() == ENTRA_UPN
    assert WindowsIdentity().for_display() == ""


def test_identity_is_built_from_one_reported_session() -> None:
    identity = WindowsIdentity.from_session(
        {"domain": ENTRA_DOMAIN, "username": "ChristianBecker", "sid": "S-1-12-1-1-2-3-4"}
    )

    assert identity.down_level == ENTRA_DOWN_LEVEL
    assert identity.sid == "S-1-12-1-1-2-3-4"
    assert identity.is_entra is True
