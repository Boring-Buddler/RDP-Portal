"""Per-machine login choice, shared by cards and the detail page."""

from PySide6.QtCore import QPointF, Signal
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from portal_app.models.user import User
from portal_app.models.workstation import Workstation
from portal_app.ui.widgets.scroll_safe_combo import ScrollSafeComboBox


class AccountComboBox(ScrollSafeComboBox):
    """Keep the dropdown affordance visible under the application stylesheet."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.Text), 1.5))
        x, y = self.width() - 16, self.height() / 2
        painter.drawLine(QPointF(x - 4, y - 2), QPointF(x, y + 2))
        painter.drawLine(QPointF(x, y + 2), QPointF(x + 4, y - 2))


class LoginAccountSelector(QWidget):
    account_selected = Signal(Workstation, str)
    add_requested = Signal(Workstation)
    ADD_VALUE = "\0add-account"

    def __init__(self, workstation: Workstation | None, user: User, parent=None):
        super().__init__(parent)
        self.workstation = workstation
        self.user = user
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel("Anmelden als")
        label.setObjectName("cardMeta")
        layout.addWidget(label)
        self.combo = AccountComboBox()
        self.combo.setObjectName("loginAccountCombo")
        self.combo.setStyleSheet("QComboBox#loginAccountCombo { padding-right: 28px; } QComboBox#loginAccountCombo::down-arrow { image: none; }")
        self.combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.combo.setMinimumWidth(0)
        self.combo.setAccessibleName("Anmeldekonto für den Zielrechner")
        self.combo.setToolTip("Bestehendes Windows-Konto auswählen. Das Kennwort fragt Windows ab.")
        layout.addWidget(self.combo)
        self.combo.activated.connect(self._activated)
        self.set_workstation(workstation, user)

    def set_workstation(self, workstation: Workstation | None, user: User) -> None:
        self.workstation, self.user = workstation, user
        if self.combo.view().isVisible():
            return
        self.combo.blockSignals(True)
        self.combo.clear()
        if workstation:
            default = workstation.username_hint or user.get_rdp_username() or "Windows-Anmeldung"
            self.combo.addItem(f"Standard · {default}", "")
            for account in workstation.login_accounts:
                self.combo.addItem(account, account)
            for account in workstation.session_accounts():
                if self.combo.findData(account) < 0:
                    self.combo.addItem(f"Angemeldet · {account}", account)
            self.combo.insertSeparator(self.combo.count())
            self.combo.addItem("+ Benutzer hinzufügen …", self.ADD_VALUE)
            self.combo.setCurrentIndex(max(0, self.combo.findData(workstation.selected_login_account or "")))
        self.combo.setEnabled(workstation is not None)
        self.combo.blockSignals(False)

    def _activated(self, index: int) -> None:
        if self.workstation is None:
            return
        value = self.combo.itemData(index)
        if value == self.ADD_VALUE:
            self.combo.setCurrentIndex(max(0, self.combo.findData(self.workstation.selected_login_account or "")))
            self.add_requested.emit(self.workstation)
        elif isinstance(value, str):
            self.account_selected.emit(self.workstation, value)
