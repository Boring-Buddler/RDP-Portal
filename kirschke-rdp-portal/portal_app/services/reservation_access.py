"""Time-limited portal access; this does not grant Windows login permissions."""
from datetime import datetime


def apply_reservations(workstations, reservations, user_upn, now=None):
    now = now or datetime.now()
    if now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)
    changed = False
    for ws in workstations:
        active = [r for r in reservations if r.workstation_id == ws.workstation_id and r.start <= now < r.end]
        previous = (ws.reservation_message, ws.reservation_block_reason)
        ws.reservation_message = ""
        ws.reservation_block_reason = ""
        if active:
            own = bool(user_upn.strip()) and all(r.reserved_by.strip().casefold() == user_upn.strip().casefold() for r in active)
            owners = ", ".join(sorted({r.reserved_by or "Unbekannter Benutzer" for r in active}))
            until = max(r.end for r in active).strftime("%d.%m. %H:%M")
            ws.reservation_message = f"Für dich reserviert bis {until}" if own else f"Reserviert für {owners} bis {until}"
            if not own:
                ws.reservation_block_reason = ws.reservation_message
        changed |= previous != (ws.reservation_message, ws.reservation_block_reason)
    return changed
