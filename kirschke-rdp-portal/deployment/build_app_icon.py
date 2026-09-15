"""Regenerate the Windows application icon from the Kirschke logo.

The signet is cropped out of the wide header logo -- the same mark
``portal_app.ui.icons`` puts in the title bar -- but an ``.ico`` needs two things
the title-bar version does not:

* **A background.** The mark is black on transparent. On a dark taskbar that is
  an invisible icon, so it is drawn in white on the brand charcoal instead.
* **Padding.** Windows draws taskbar and Explorer icons edge to edge. The raw
  crop touches all four borders, which reads as a cut-off image next to icons
  that keep a margin.

Run after changing ``kirschke_logo.png``; the generated ``.ico`` is committed so
a build never depends on Pillow:

    python deployment/build_app_icon.py
"""

from __future__ import annotations

from pathlib import Path

#: Brand charcoal, matching ``BrandColors.CHARCOAL`` in portal_app.ui.design.
BACKGROUND = (35, 31, 32, 255)

#: Share of the icon edge left free around the mark on every side.
PADDING = 0.17

#: Corner rounding as a share of the icon edge. Windows does not round icons
#: itself, and a hard square sits oddly among the rounded ones in the taskbar.
RADIUS = 0.18

#: Every size Windows picks from: taskbar, Explorer views, Alt+Tab, the high-DPI
#: shortcut. A missing size is scaled by Windows and looks noticeably worse.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

ASSETS = Path(__file__).resolve().parent.parent / "portal_app" / "ui" / "assets"
SOURCE = ASSETS / "kirschke_logo.png"
TARGET = ASSETS / "kirschke.ico"


def build_master(edge: int = 1024):
    """The icon at one large size; ``.ico`` sizes are scaled down from it."""
    from PIL import Image, ImageDraw

    logo = Image.open(SOURCE).convert("RGBA")
    # The signet is the leftmost, roughly square part of the wide logo.
    mark = logo.crop((0, 0, min(logo.width, round(logo.height * 1.08)), logo.height))
    # The mark is black on transparent; recolour it to white through its alpha.
    white = Image.new("RGBA", mark.size, (255, 255, 255, 255))
    white.putalpha(mark.getchannel("A"))
    mark = white

    canvas = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    plate = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(
        (0, 0, edge - 1, edge - 1), radius=round(edge * RADIUS), fill=BACKGROUND
    )
    canvas.alpha_composite(plate)

    inner = round(edge * (1 - 2 * PADDING))
    scale = min(inner / mark.width, inner / mark.height)
    mark = mark.resize((round(mark.width * scale), round(mark.height * scale)), Image.LANCZOS)
    canvas.alpha_composite(
        mark, ((edge - mark.width) // 2, (edge - mark.height) // 2)
    )
    return canvas


def main() -> int:
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("Pillow wird benötigt: python -m pip install pillow")  # noqa: T201
        return 1
    if not SOURCE.exists():
        print(f"Logo nicht gefunden: {SOURCE}")  # noqa: T201
        return 1
    master = build_master()
    master.save(TARGET, format="ICO", sizes=[(size, size) for size in SIZES])
    print(f"Geschrieben: {TARGET} ({', '.join(str(size) for size in SIZES)})")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
