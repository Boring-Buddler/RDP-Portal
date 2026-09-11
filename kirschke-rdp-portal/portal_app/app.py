"""Main application for Kirschke RDP Workstation Portal."""

import logging
import os
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

# A direct ``python portal_app/app.py`` start puts only ``portal_app`` on
# sys.path.  Add the project directory first so absolute package imports work
# just like they do with ``python -m portal_app.app``.
if __package__ in {None, ""}:
    project_directory = str(Path(__file__).resolve().parents[1])
    if project_directory not in sys.path:
        sys.path.insert(0, project_directory)

from PySide6.QtWidgets import QApplication, QWidget, QMessageBox
from PySide6.QtCore import QEvent
from PySide6.QtGui import QPalette

from portal_app.ui.design import Colors, Typography
from portal_app.ui.main_window import MainWindow
from portal_app.ui.icons import kirschke_window_icon
from portal_app.models.user import MockUser


logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Portable installations need a writable log outside the program folder."""
    directory = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "KirschkeRDPPortal" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handlers = [RotatingFileHandler(directory / "portal.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


class RDPPortalApp(QApplication):
    """Main application class for the RDP Workstation Portal."""
    
    def __init__(self, argv: list[str]):
        """Initialize the application."""
        super().__init__(argv)
        
        # Set application metadata
        self.setApplicationName("Kirschke RDP Workstation Portal")
        self.setApplicationVersion("0.1.0")
        self.setOrganizationName("Prof. Kirschke")
        self.setOrganizationDomain("prof-kirschke.de")
        self.portal_icon = kirschke_window_icon()
        self.setWindowIcon(self.portal_icon)
        self.installEventFilter(self)
        
        # Apply design system
        self._apply_design_system()
        
        # Set default font
        default_font = Typography.body()
        self.setFont(default_font)
        
        # Create and show main window
        try:
            self.main_window = MainWindow()
        except (OSError, ValueError, RuntimeError) as exc:
            logger.exception("Portal startup failed")
            QMessageBox.critical(None, "Portal konnte nicht gestartet werden", str(exc))
            raise
        self.main_window.show()
        
        logger.info("RDP Workstation Portal started")

    def eventFilter(self, watched, event):  # noqa: N802
        """Apply the branded signet to every Qt top-level window and dialog."""
        if event.type() in (QEvent.Show, QEvent.Polish) and isinstance(watched, QWidget):
            if watched.isWindow() and not self.portal_icon.isNull():
                watched.setWindowIcon(self.portal_icon)
        return super().eventFilter(watched, event)
    
    def _apply_design_system(self) -> None:
        """Apply Kirschke design system to the application."""
        # Set palette
        palette = self.palette()
        palette.setColor(QPalette.Window, Colors.background)
        palette.setColor(QPalette.WindowText, Colors.text)
        palette.setColor(QPalette.Base, Colors.surface)
        palette.setColor(QPalette.AlternateBase, Colors.paper)
        palette.setColor(QPalette.Text, Colors.text)
        palette.setColor(QPalette.Button, Colors.surface)
        palette.setColor(QPalette.ButtonText, Colors.text)
        palette.setColor(QPalette.Highlight, Colors.brand_blue)
        palette.setColor(QPalette.HighlightedText, Colors.surface)
        palette.setColor(QPalette.ToolTipBase, Colors.surface)
        palette.setColor(QPalette.ToolTipText, Colors.text)
        self.setPalette(palette)
    
    def get_current_user(self) -> MockUser:
        """Get the current authenticated user (mock for Phase 1)."""
        # For Phase 1, return a mock user
        # In Phase 2, this will use actual Entra ID authentication
        return MockUser.create_user()
    
    def get_admin_user(self) -> MockUser:
        """Get an admin user (for testing admin features)."""
        return MockUser.create_admin()


def main():
    """Main entry point for the application."""
    configure_logging()
    # Validate environment
    try:
        from shared.validation import validate_environment
        env_info = validate_environment()
        logger.info(f"Environment validated: Python {env_info['python_version_info'].major}.{env_info['python_version_info'].minor}")
    except Exception as e:
        print(f"Environment validation failed: {e}")
        sys.exit(1)
    
    # Create application
    app = RDPPortalApp(sys.argv)
    
    # Execute
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Application crashed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
