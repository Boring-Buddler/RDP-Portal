"""Kirschke Corporate Design System for RDP Workstation Portal.

This module contains all design tokens, colors, typography, and styling
constants as specified in the Kirschke_Corporate_Design_Masterprompt.
"""

from PySide6.QtGui import QColor, QFont
from PySide6.QtCore import Qt


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


# =============================================================================
# Typography
# =============================================================================

class Typography:
    """Typography settings using Segoe UI as the primary font family."""
    
    # Font families (fallback chain)
    FONT_FAMILY = "Segoe UI"
    FONT_FAMILY_FALLBACK = ["Segoe UI", "Inter", "Arial", "Helvetica", "sans-serif"]
    
    # Font sizes
    FONT_SIZE_XS = 10
    FONT_SIZE_SM = 12
    FONT_SIZE_BASE = 14
    FONT_SIZE_LG = 16
    FONT_SIZE_XL = 18
    FONT_SIZE_2XL = 20
    FONT_SIZE_3XL = 24
    
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
        font = QFont(Typography.FONT_FAMILY, size, weight)
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
        font = QFont("Consolas", cls.FONT_SIZE_SM, cls.FONT_WEIGHT_NORMAL)
        return font


# =============================================================================
# Spacing System
# =============================================================================

class Spacing:
    """Spacing values in pixels."""
    
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
                font-family: {Typography.FONT_FAMILY};
                font-size: {Typography.FONT_SIZE_BASE}px;
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
                font-family: {Typography.FONT_FAMILY};
                font-size: {Typography.FONT_SIZE_BASE}px;
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
                font-family: {Typography.FONT_FAMILY};
                font-size: {Typography.FONT_SIZE_BASE}px;
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
                font-family: {Typography.FONT_FAMILY};
                font-size: {Typography.FONT_SIZE_SM}px;
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
                font-size: {Typography.FONT_SIZE_XS}px;
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
    def apply_to(cls, widget: "QWidget") -> None:
        """Apply base styles to a widget."""
        widget.setStyleSheet(cls.styles.central_widget())
        
        # Set font
        font = cls.typography.body()
        widget.setFont(font)
        
        # Set palette
        palette = widget.palette()
        palette.setColor(palette.Window, Colors.background)
        palette.setColor(palette.WindowText, Colors.text)
        palette.setColor(palette.Base, Colors.surface)
        palette.setColor(palette.AlternateBase, Colors.paper)
        palette.setColor(palette.Text, Colors.text)
        palette.setColor(palette.Button, Colors.surface)
        palette.setColor(palette.ButtonText, Colors.text)
        palette.setColor(palette.Highlight, Colors.brand_blue)
        palette.setColor(palette.HighlightedText, Colors.surface)
        widget.setPalette(palette)


# =============================================================================
# Public API
# =============================================================================

__all__ = [
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
