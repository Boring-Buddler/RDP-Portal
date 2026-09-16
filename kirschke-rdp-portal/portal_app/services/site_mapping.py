"""Which office an address belongs to.

Two sites, two IPv4 ranges, and nobody types the site name correctly twice in a
row: "Ettlingen", "ettlingen" and "Ettlingen " are three sites as far as the card
filter is concerned, because ``site`` is free text everywhere else in the portal.
Deriving it from the address that was just discovered removes the typing, and
with it the three-way split.

The mapping stays data, not code: a third range is one entry here, and an address
that matches nothing simply yields no site rather than a guessed one.  Guessing
would be worse than leaving it blank -- a machine filed under the wrong office is
harder to notice than one filed under none.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network, ip_address

#: Range to office. Written as networks, not string prefixes, because
#: ``"192.168.20.5".startswith("192.168.2")`` is true and would put every Munich
#: machine in Ettlingen.
SITE_NETWORKS: tuple[tuple[IPv4Network, str], ...] = (
    (IPv4Network("192.168.2.0/24"), "Ettlingen"),
    (IPv4Network("192.168.20.0/24"), "München"),
)


def site_for_address(value: str | None) -> str:
    """Return the office an IPv4 address belongs to, or an empty string.

    Anything that is not a plain IPv4 address -- a host name, an IPv6 address, a
    blank field -- has no site here. Names are deliberately not mapped: the same
    short name exists at both offices.
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        address = ip_address(text)
    except ValueError:
        return ""
    if not isinstance(address, IPv4Address):
        return ""
    return next(
        (site for network, site in SITE_NETWORKS if address in network),
        "",
    )


def known_sites() -> list[str]:
    """Every office this portal can name, for offering them in a list."""
    result: list[str] = []
    for _, site in SITE_NETWORKS:
        if site not in result:
            result.append(site)
    return result


__all__ = ["SITE_NETWORKS", "known_sites", "site_for_address"]
