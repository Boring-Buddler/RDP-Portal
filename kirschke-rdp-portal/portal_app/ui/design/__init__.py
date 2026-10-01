"""Kirschke Corporate Design System for RDP Workstation Portal.

This module contains all design tokens, colors, typography, and styling
constants as specified in the Kirschke_Corporate_Design_Masterprompt.
"""

import re

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

# =============================================================================
# Skalierung: Schriftgröße und Maße folgen der Windows-Einstellung
# =============================================================================

#: Die Punktgröße, für die dieses Design gezeichnet wurde. Jede feste Maßangabe
#: im Portal ist an ihr gemessen, und der Skalierungsfaktor ist genau das
#: Verhältnis der tatsächlichen Systemgröße zu dieser hier.
REFERENCE_POINT_SIZE = 9.0

#: Grenzen für die übernommene Systemgröße. Nach unten, weil eine
#: Zwei-Punkt-Schrift das Fenster nicht benutzbarer macht; nach oben, weil das
#: Portal sonst auf einem kleinen Bildschirm nicht mehr vollständig passt.
MIN_POINT_SIZE = 7.0
MAX_POINT_SIZE = 16.0

_system_point_size: float | None = None


def system_point_size() -> float:
    """Die Schriftgröße, die Windows für Oberflächen vorgibt.

    Absichtlich aus ``QFontDatabase`` und nicht aus ``QApplication.font()``:
    Das Portal setzt seine eigene Schrift beim Start, und danach würde es hier
    nur noch seine eigene Vorgabe wiederfinden statt der des Systems.

    Einmal ermittelt und gemerkt. Die Antwort ändert sich innerhalb einer
    Sitzung nicht, und sie wird beim Zeichnen jeder Karte gebraucht.
    """
    global _system_point_size
    if _system_point_size is None:
        size = QFontDatabase.systemFont(QFontDatabase.GeneralFont).pointSizeF()
        if size <= 0:
            size = REFERENCE_POINT_SIZE
        _system_point_size = max(MIN_POINT_SIZE, min(MAX_POINT_SIZE, size))
    return _system_point_size


def scale_factor() -> float:
    """Wie viel größer als vorgesehen die Oberfläche hier ausfallen muss.

    Die reine Bildschirmauflösung steckt nicht darin: Qt rechnet die
    Anzeigeskalierung (125 %, 150 %) schon selbst heraus. Was Qt *nicht* tut,
    ist feste Pixelmaße mitwachsen zu lassen, wenn jemand allein die
    Schriftgröße hochsetzt -- und dann stand der Text in Knöpfen und Karten
    fester Höhe halb außerhalb.
    """
    return system_point_size() / REFERENCE_POINT_SIZE


def scaled(pixels: float) -> int:
    """Ein am 9-Punkt-Entwurf gemessenes Pixelmaß auf diese Anzeige umrechnen."""
    return max(1, round(pixels * scale_factor()))


def scaled_points(points: float) -> float:
    """Eine am Entwurf gemessene Punktgröße auf die Systemgröße umrechnen."""
    return round(points * scale_factor(), 1)


def apply_scaled_geometry(
    widget: QWidget,
    minimum: tuple[int, int],
    preferred: tuple[int, int] | None = None,
) -> None:
    """Ein Fenster skaliert aufziehen, aber nie größer als der Bildschirm.

    Die übergebenen Maße sind am 9-Punkt-Entwurf gemessen und werden mitskaliert.
    Entscheidend ist die zweite Hälfte: Ein Mindestmaß, das nicht auf den
    Bildschirm passt, macht ein Fenster unbedienbar -- es lässt sich dann weder
    kleiner ziehen noch vollständig sehen. Bei 150 % Anzeigeskalierung bleiben
    von einem 1920 x 1080-Schirm 1280 x 720 logische Pixel übrig, und ein
    Mindestmaß von 1080 x 720 passte dort nicht mehr hinein.
    """
    from PySide6.QtGui import QGuiApplication

    screen = widget.screen() or QGuiApplication.primaryScreen()
    available = screen.availableGeometry() if screen is not None else None
    limit_width = int(available.width() * 0.95) if available else scaled(minimum[0])
    limit_height = int(available.height() * 0.95) if available else scaled(minimum[1])
    minimum_width = min(scaled(minimum[0]), limit_width)
    minimum_height = min(scaled(minimum[1]), limit_height)
    widget.setMinimumSize(minimum_width, minimum_height)
    if preferred is None:
        return
    widget.resize(
        max(minimum_width, min(scaled(preferred[0]), limit_width)),
        max(minimum_height, min(scaled(preferred[1]), limit_height)),
    )


#: Maßangaben in Stylesheets, die mit der Schrift wachsen müssen. Höhen und
#: Breiten stehen mit darin, weil eine größere Schrift in einem Feld fester
#: Mindesthöhe genau das tut, was sie nicht soll: Sie wird abgeschnitten.
_SCALABLE_CSS = re.compile(r"\b(font-size:\s*)(\d+(?:\.\d+)?)pt|\b(min-height|min-width):\s*(\d+)px")


def scale_stylesheet(css: str) -> str:
    """Absolute Maße in einem Qt-Stylesheet an die Systemschrift angleichen.

    Das Portal beschreibt sein Aussehen zum großen Teil in Stylesheets, und dort
    stehen Punktgrößen als feste Zahlen. Die überschreiben die Anwendungsschrift
    -- wer in Windows eine größere Schrift eingestellt hat, bekam sie überall
    außer dort, wo es zählt. Hier wird jede dieser Zahlen beim Setzen des
    Stylesheets einmal umgerechnet, statt sie an dreißig Stellen einzeln zu
    pflegen.
    """
    if scale_factor() == 1.0:
        return css

    def replace(match: re.Match) -> str:
        if match.group(1):
            return f"{match.group(1)}{scaled_points(float(match.group(2)))}pt"
        return f"{match.group(3)}: {scaled(int(match.group(4)))}px"

    return _SCALABLE_CSS.sub(replace, css)

# =============================================================================
# Brand Colors
# =============================================================================

class BrandColors:
    """Kirschke brand colors."""

    BLUE: QColor = QColor("#668BB0")
    CHARCOAL: QColor = QColor("#231F20")
    GREEN: QColor = QColor("#778C77")
    LIGHT_BLUE: QColor = QColor("#80A3CA")


# =============================================================================
# Neutral Colors
# =============================================================================

class NeutralColors:
    """Neutral colors for backgrounds, surfaces, and text."""

    BACKGROUND: QColor = QColor("#F4F5F2")
    PAPER: QColor = QColor("#F7F7F3")
    SURFACE: QColor = QColor("#FFFFFF")
    SURFACE_ALT: QColor = QColor("#E8ECE8")
    BORDER: QColor = QColor("#CDD3CD")
    TEXT: QColor = QColor("#151515")
    TEXT_MUTED: QColor = QColor("#606862")


# =============================================================================
# Interaction Colors
# =============================================================================

class InteractionColors:
    """Colors for interactive elements (buttons, inputs, etc.)."""

    FOCUS: QColor = QColor("#1F5F99")
    HOVER: QColor = QColor("#91B2D6")
    ACTIVE: QColor = QColor("#6F91B8")


# =============================================================================
# Status Colors
# =============================================================================

class StatusColors:
    """Colors for status indicators."""

    SUCCESS: QColor = QColor("#3F6F4B")
    WARNING: QColor = QColor("#8A611F")
    ERROR: QColor = QColor("#9B2F2F")
    INFO: QColor = QColor("#1F5F99")
    #: Your own session is holding a machine while no portal window is open.
    ATTENTION: QColor = QColor("#CC7A29")
    #: Somebody else has this machine -- signed in, or booked for later.  One
    #: colour for both, because the question a person asks the dashboard is "can I
    #: use it", and the answer is the same either way.  Placed in the middle of the
    #: only real gap on the wheel (blue 208 deg to red 360 deg): every warm tone
    #: tried here sat too close to ATTENTION's orange, and this hue keeps 74 deg to
    #: its nearest neighbour where the earlier violet kept only 54 deg.
    TAKEN: QColor = QColor("#8C4C9E")


# =============================================================================
# Combined Color Palette
# =============================================================================

class Colors:
    """Complete color palette combining all color categories."""

    # Brand
    brand_blue = BrandColors.BLUE
    brand_charcoal = BrandColors.CHARCOAL
    brand_green = BrandColors.GREEN
    brand_light_blue = BrandColors.LIGHT_BLUE

    # Neutral
    background = NeutralColors.BACKGROUND
    paper = NeutralColors.PAPER
    surface = NeutralColors.SURFACE
    surface_alt = NeutralColors.SURFACE_ALT
    border = NeutralColors.BORDER
    text = NeutralColors.TEXT
    text_muted = NeutralColors.TEXT_MUTED

    # Interaction
    focus = InteractionColors.FOCUS
    hover = InteractionColors.HOVER
    active = InteractionColors.ACTIVE

    # Status
    success = StatusColors.SUCCESS
    warning = StatusColors.WARNING
    error = StatusColors.ERROR
    info = StatusColors.INFO
    attention = StatusColors.ATTENTION
    taken = StatusColors.TAKEN


# =============================================================================
# Typography
# =============================================================================

class Typography:
    """Typography based on the Windows/Qt system font and scalable point sizes.

    Die Konstanten sind die Größen des Entwurfs, gemessen an
    :data:`REFERENCE_POINT_SIZE`. Sie bleiben stehen, weil Stylesheets sie als
    Zahl brauchen; umgerechnet wird in :meth:`get_font` und in
    :func:`scale_stylesheet`.
    """

    # Font sizes
    FONT_SIZE_XS = 8
    FONT_SIZE_SM = 8
    FONT_SIZE_BASE = 9
    FONT_SIZE_LG = 10
    FONT_SIZE_XL = 11
    FONT_SIZE_2XL = 13
    FONT_SIZE_3XL = 16

    # Font weights
    FONT_WEIGHT_NORMAL = QFont.Normal
    FONT_WEIGHT_MEDIUM = QFont.Medium
    FONT_WEIGHT_SEMIBOLD = QFont.DemiBold
    FONT_WEIGHT_BOLD = QFont.Bold

    # Line heights
    LINE_HEIGHT_TIGHT = 1.2
    LINE_HEIGHT_NORMAL = 1.5
    LINE_HEIGHT_RELAXED = 1.75

    @staticmethod
    def get_font(size: int = FONT_SIZE_BASE, weight: int = FONT_WEIGHT_NORMAL) -> QFont:
        """Create a font with specified size and weight."""
        application = QApplication.instance()
        font = QFont(application.font()) if application is not None else QFont()
        # Die Entwurfsgröße wird auf die Systemgröße umgerechnet, statt sie zu
        # setzen: Sonst bekäme jede Schrift im Portal ihre 9 Punkt unabhängig
        # davon, was in Windows unter "Größe von Text" eingestellt ist.
        font.setPointSizeF(scaled_points(size))
        font.setWeight(weight)
        return font

    @classmethod
    def heading_1(cls) -> QFont:
        """Heading 1 font."""
        return cls.get_font(cls.FONT_SIZE_3XL, cls.FONT_WEIGHT_BOLD)

    @classmethod
    def heading_2(cls) -> QFont:
        """Heading 2 font."""
        return cls.get_font(cls.FONT_SIZE_2XL, cls.FONT_WEIGHT_BOLD)

    @classmethod
    def heading_3(cls) -> QFont:
        """Heading 3 font."""
        return cls.get_font(cls.FONT_SIZE_XL, cls.FONT_WEIGHT_SEMIBOLD)

    @classmethod
    def body(cls) -> QFont:
        """Body text font."""
        return cls.get_font(cls.FONT_SIZE_BASE, cls.FONT_WEIGHT_NORMAL)

    @classmethod
    def body_small(cls) -> QFont:
        """Small body text font."""
        return cls.get_font(cls.FONT_SIZE_SM, cls.FONT_WEIGHT_NORMAL)

    @classmethod
    def button(cls) -> QFont:
        """Button text font."""
        return cls.get_font(cls.FONT_SIZE_BASE, cls.FONT_WEIGHT_MEDIUM)

    @classmethod
    def label(cls) -> QFont:
        """Label text font."""
        return cls.get_font(cls.FONT_SIZE_SM, cls.FONT_WEIGHT_NORMAL)

    @classmethod
    def code(cls) -> QFont:
        """Code/monospace font."""
        font = QFont("Consolas", weight=cls.FONT_WEIGHT_NORMAL)
        font.setPointSizeF(scaled_points(cls.FONT_SIZE_SM))
        return font


# =============================================================================
# Spacing System
# =============================================================================

class Spacing:
    """Spacing values in pixels.

    Die Zahlen sind am Entwurf gemessen; :meth:`px` rechnet sie auf diese
    Anzeige um. Die Klassenattribute bleiben unskaliert, weil sie in
    Stylesheets als Zahl eingesetzt werden und dort schon
    :func:`scale_stylesheet` greift.
    """

    NONE = 0
    XXS = 2
    XS = 4
    SM = 8
    MD = 16
    LG = 24
    XL = 32
    XXL = 48
    XXXL = 64

    @classmethod
    def get(cls, size: str) -> int:
        """Get spacing value by name."""
        return getattr(cls, size.upper(), cls.MD)

    @classmethod
    def px(cls, size: str | int) -> int:
        """Ein Abstand des Entwurfs, auf diese Anzeige umgerechnet."""
        return scaled(size if isinstance(size, int) else cls.get(size))


# =============================================================================
# Border Radius
# =============================================================================

class BorderRadius:
    """Border radius values in pixels."""

    NONE = 0
    SM = 2
    MD = 4
    LG = 6
    XL = 8
    FULL = 9999  # For pill shapes (not used per design rules)


# =============================================================================
# Shadows
# =============================================================================

class Shadows:
    """Shadow definitions. Kirschke design uses minimal shadows."""

    NONE = ()
    SM = (0, 1, 2, 0.1)  # x, y, blur, opacity
    MD = (0, 2, 4, 0.15)
    LG = (0, 4, 8, 0.2)


# =============================================================================
# Agent Status Colors (mapped to Kirschke palette)
# =============================================================================

class AgentStatusColors:
    """Colors for different agent status states."""

    ONLINE = StatusColors.SUCCESS
    STALE = StatusColors.WARNING
    OFFLINE = NeutralColors.TEXT_MUTED
    ERROR = StatusColors.ERROR


# =============================================================================
# Session State Colors
# =============================================================================

class SessionStateColors:
    """Colors for different session states."""

    NONE = NeutralColors.TEXT_MUTED
    LOGON = StatusColors.INFO
    CONNECTED = StatusColors.SUCCESS
    RECONNECTED = StatusColors.INFO
    DISCONNECTED = StatusColors.WARNING
    LOGGED_OFF = NeutralColors.TEXT_MUTED


# =============================================================================
# Manual Flag Colors
# =============================================================================

class ManualFlagColors:
    """Colors for different manual flag types."""

    NONE = "transparent"
    CALCULATION_RUNNING = StatusColors.INFO
    MAINTENANCE = StatusColors.WARNING
    BLOCKED = StatusColors.ERROR


# =============================================================================
# Style Sheets
# =============================================================================

class StyleSheets:
    """Predefined Qt style sheets for common widgets."""

    @classmethod
    def main_window(cls) -> str:
        """Style sheet for the main window."""
        return f"""
            QMainWindow {{
                background-color: {Colors.background.name()};
            }}
        """

    @classmethod
    def central_widget(cls) -> str:
        """Style sheet for central widget."""
        return f"""
            QWidget {{
                background-color: {Colors.paper.name()};
            }}
        """

    @classmethod
    def button_primary(cls) -> str:
        """Style sheet for primary buttons."""
        return f"""
            QPushButton {{
                background-color: {Colors.brand_blue.name()};
                color: {Colors.surface.name()};
                border: 1px solid {Colors.brand_blue.name()};
                border-radius: {BorderRadius.MD}px;
                padding: {Spacing.SM}px {Spacing.LG}px;
                font-size: {Typography.FONT_SIZE_BASE}pt;
                font-weight: {Typography.FONT_WEIGHT_MEDIUM};
            }}
            QPushButton:hover {{
                background-color: {Colors.hover.name()};
                border-color: {Colors.hover.name()};
            }}
            QPushButton:pressed {{
                background-color: {Colors.active.name()};
                border-color: {Colors.active.name()};
            }}
            QPushButton:disabled {{
                background-color: {Colors.surface_alt.name()};
                color: {Colors.text_muted.name()};
                border-color: {Colors.border.name()};
            }}
        """

    @classmethod
    def button_secondary(cls) -> str:
        """Style sheet for secondary buttons."""
        return f"""
            QPushButton {{
                background-color: {Colors.surface.name()};
                color: {Colors.text.name()};
                border: 1px solid {Colors.border.name()};
                border-radius: {BorderRadius.MD}px;
                padding: {Spacing.SM}px {Spacing.LG}px;
                font-size: {Typography.FONT_SIZE_BASE}pt;
            }}
            QPushButton:hover {{
                background-color: {Colors.paper.name()};
                border-color: {Colors.brand_blue.name()};
            }}
            QPushButton:pressed {{
                background-color: {Colors.surface_alt.name()};
                border-color: {Colors.brand_blue.name()};
            }}
            QPushButton:disabled {{
                background-color: {Colors.surface_alt.name()};
                color: {Colors.text_muted.name()};
                border-color: {Colors.border.name()};
            }}
        """

    @classmethod
    def button_danger(cls) -> str:
        """Style sheet for danger buttons (e.g., logoff)."""
        return f"""
            QPushButton {{
                background-color: {Colors.error.name()};
                color: {Colors.surface.name()};
                border: 1px solid {Colors.error.name()};
                border-radius: {BorderRadius.MD}px;
                padding: {Spacing.SM}px {Spacing.LG}px;
            }}
            QPushButton:hover {{
                background-color: #c53f3f;
                border-color: #c53f3f;
            }}
            QPushButton:pressed {{
                background-color: #a02f2f;
                border-color: #a02f2f;
            }}
        """

    @classmethod
    def input_field(cls) -> str:
        """Style sheet for input fields."""
        return f"""
            QLineEdit, QTextEdit, QComboBox, QSpinBox, QDateEdit {{
                background-color: {Colors.surface.name()};
                color: {Colors.text.name()};
                border: 1px solid {Colors.border.name()};
                border-radius: {BorderRadius.MD}px;
                padding: {Spacing.SM}px {Spacing.MD}px;
                font-size: {Typography.FONT_SIZE_BASE}pt;
                selection-background-color: {Colors.brand_blue.name()};
                selection-color: {Colors.surface.name()};
            }}
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {{
                border-color: {Colors.focus.name()};
                outline: none;
            }}
            QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDateEdit:disabled {{
                background-color: {Colors.surface_alt.name()};
                color: {Colors.text_muted.name()};
            }}
        """

    @classmethod
    def table_view(cls) -> str:
        """Style sheet for table views."""
        return f"""
            QTableView {{
                background-color: {Colors.surface.name()};
                color: {Colors.text.name()};
                border: 1px solid {Colors.border.name()};
                border-radius: {BorderRadius.MD}px;
                gridline-color: {Colors.border.name()};
                font-size: {Typography.FONT_SIZE_SM}pt;
            }}
            QHeaderView::section {{
                background-color: {Colors.surface_alt.name()};
                color: {Colors.text.name()};
                padding: {Spacing.SM}px {Spacing.MD}px;
                border: none;
                border-bottom: 1px solid {Colors.border.name()};
                font-weight: {Typography.FONT_WEIGHT_SEMIBOLD};
            }}
            QTableView::item {{
                padding: {Spacing.XS}px {Spacing.SM}px;
                border-bottom: 1px solid {Colors.border.name()};
            }}
            QTableView::item:selected {{
                background-color: {Colors.brand_blue.name()};
                color: {Colors.surface.name()};
            }}
            QTableView::item:alternate {{
                background-color: {Colors.paper.name()};
            }}
        """

    @classmethod
    def status_badge(cls, status_color: str) -> str:
        """Style sheet for status badges."""
        return f"""
            QLabel {{
                background-color: {status_color};
                color: {Colors.surface.name()};
                border-radius: {BorderRadius.SM}px;
                padding: {Spacing.XXS}px {Spacing.XS}px;
                font-size: {Typography.FONT_SIZE_XS}pt;
                font-weight: {Typography.FONT_WEIGHT_SEMIBOLD};
            }}
        """

    @classmethod
    def card(cls) -> str:
        """Style sheet for card widgets."""
        return f"""
            QFrame {{
                background-color: {Colors.surface.name()};
                border: 1px solid {Colors.border.name()};
                border-radius: {BorderRadius.MD}px;
                padding: {Spacing.MD}px;
            }}
        """


# =============================================================================
# Design System Helper
# =============================================================================

class DesignSystem:
    """Main design system class providing easy access to all design elements."""

    colors = Colors
    typography = Typography
    spacing = Spacing
    border_radius = BorderRadius
    shadows = Shadows
    styles = StyleSheets

    # Status-specific colors
    agent_status = AgentStatusColors
    session_state = SessionStateColors
    manual_flag = ManualFlagColors

    @classmethod
    def apply_to(cls, widget: QWidget) -> None:
        """Apply base styles to a widget."""
        widget.setStyleSheet(cls.styles.central_widget())

        # Set font
        font = cls.typography.body()
        widget.setFont(font)

        # Set palette
        from PySide6.QtGui import QPalette
        palette = widget.palette()
        palette.setColor(QPalette.Window, Colors.background)
        palette.setColor(QPalette.WindowText, Colors.text)
        palette.setColor(QPalette.Base, Colors.surface)
        palette.setColor(QPalette.AlternateBase, Colors.paper)
        palette.setColor(QPalette.Text, Colors.text)
        palette.setColor(QPalette.Button, Colors.surface)
        palette.setColor(QPalette.ButtonText, Colors.text)
        palette.setColor(QPalette.Highlight, Colors.brand_blue)
        palette.setColor(QPalette.HighlightedText, Colors.surface)
        widget.setPalette(palette)


# =============================================================================
# Public API
# =============================================================================

__all__ = [
    # Skalierung
    "MAX_POINT_SIZE",
    "MIN_POINT_SIZE",
    "REFERENCE_POINT_SIZE",
    "apply_scaled_geometry",
    "scale_factor",
    "scale_stylesheet",
    "scaled",
    "scaled_points",
    "system_point_size",
    # Color classes
    "BrandColors",
    "NeutralColors",
    "InteractionColors",
    "StatusColors",
    "Colors",
    # Typography
    "Typography",
    # Spacing and layout
    "Spacing",
    "BorderRadius",
    "Shadows",
    # Status colors
    "AgentStatusColors",
    "SessionStateColors",
    "ManualFlagColors",
    # Style sheets
    "StyleSheets",
    # Main design system
    "DesignSystem",
]
