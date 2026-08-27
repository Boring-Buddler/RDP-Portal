"""Main application for Kirschke RDP Workstation Portal."""

import sys
import logging
from typing import Optional
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon

from portal_app.ui.design import DesignSystem, Colors, Typography
from portal_app.ui.main_window import MainWindow
from portal_app.models.user import MockUser


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('rdp_portal.log'),
    ]
)
logger = logging.getLogger(__name__)


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
        
        # Apply design system
        self._apply_design_system()
        
        # Set default font
        default_font = Typography.body()
        self.setFont(default_font)
        
        # Create and show main window
        self.main_window = MainWindow()
        self.main_window.show()
        
        logger.info("RDP Workstation Portal started")
    
    def _apply_design_system(self) -> None:
        """Apply Kirschke design system to the application."""
        # Set palette
        palette = self.palette()
        palette.setColor(palette.Window, Colors.background)
        palette.setColor(palette.WindowText, Colors.text)
        palette.setColor(palette.Base, Colors.surface)
        palette.setColor(palette.AlternateBase, Colors.paper)
        palette.setColor(palette.Text, Colors.text)
        palette.setColor(palette.Button, Colors.surface)
        palette.setColor(palette.ButtonText, Colors.text)
        palette.setColor(palette.Highlight, Colors.brand_blue)
        palette.setColor(palette.HighlightedText, Colors.surface)
        palette.setColor(palette.ToolTipBase, Colors.surface)
        palette.setColor(palette.ToolTipText, Colors.text)
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
