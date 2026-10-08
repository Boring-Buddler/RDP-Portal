"""Per-machine login choice, shared by cards and the detail page."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionComboBox,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.user import User
from portal_app.models.workstation import Workstation
from portal_app.ui.widgets.scroll_safe_combo import ScrollSafeComboBox
from shared.identity import is_entra_profile_name, same_account_name


class AccountComboBox(ScrollSafeComboBox):
    """Keep the dropdown affordance visible under the application stylesheet.

    Zu lange Kontonamen enden mit „…“. Das Feld hat keine Mindestbreite, damit
    es in der schmalen Listenzeile Platz lässt -- und Qt schnitt den Text dann
    ohne Hinweis ab. Der volle Name steht in der aufgeklappten Liste.
    """

    def _label_option(self) -> tuple[QStyleOptionComboBox, int]:
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        field = self.style().subControlRect(
            QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self
        )
        return option, field.width()

    def is_elided(self) -> bool:
        """Ob der gewählte Eintrag gerade gekürzt dargestellt wird."""
        option, width = self._label_option()
        return self.fontMetrics().horizontalAdvance(option.currentText) > width

    def paintEvent(self, event) -> None:
        option, width = self._label_option()
        option.currentText = self.fontMetrics().elidedText(
            option.currentText, Qt.ElideRight, width
        )
        styled = QStylePainter(self)
        styled.drawComplexControl(QStyle.CC_ComboBox, option)
        styled.drawControl(QStyle.CE_ComboBoxLabel, option)
        styled.end()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.Text), 1.5))
        x, y = self.width() - 16, self.height() / 2
        painter.drawLine(QPointF(x - 4, y - 2), QPointF(x, y + 2))
        painter.drawLine(QPointF(x, y + 2), QPointF(x + 4, y - 2))


class AccountStarDelegate(QStyledItemDelegate):
    """Draw a separate favorite target at the right edge of each account row."""

    def __init__(self, selector: LoginAccountSelector) -> None:
        super().__init__(selector.combo)
        self.selector = selector

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        value = index.data(Qt.UserRole)
        if not isinstance(value, str) or value == self.selector.ADD_VALUE:
            return
        active = value == self.selector.preferred_account
        painter.save()
        painter.setPen(self.selector.combo.palette().color(QPalette.HighlightedText if active else QPalette.Text))
        painter.drawText(option.rect.adjusted(0, 0, -10, 0), Qt.AlignRight | Qt.AlignVCenter,
                         "★" if active else "☆")
        painter.restore()


class LoginAccountSelector(QWidget):
    account_selected = Signal(Workstation, str)
    preferred_toggled = Signal(Workstation, object)
    add_requested = Signal(Workstation)
    ADD_VALUE = "\0add-account"

    def __init__(self, workstation: Workstation | None, user: User, parent=None):
        super().__init__(parent)
        self.workstation = workstation
        self.user = user
        self.preferred_account: str | None = None
        self._content_key: tuple | None = None
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
        self.combo.setToolTip(
            "Windows-Konto auswählen. Stern rechts: bevorzugtes Konto. "
            "Im geöffneten Menü geht das auch mit Strg+D."
        )
        layout.addWidget(self.combo)
        self.combo.setItemDelegate(AccountStarDelegate(self))
        self.combo.view().installEventFilter(self)
        self.combo.view().viewport().installEventFilter(self)
        self.combo.activated.connect(self._activated)
        self.set_workstation(workstation, user)

    def eventFilter(self, source, event) -> bool:
        if source is self.combo.view().viewport() and event.type() == QEvent.MouseButtonPress:
            position = event.position().toPoint()
            index = self.combo.view().indexAt(position)
            if index.isValid() and position.x() >= self.combo.view().viewport().width() - 34:
                return self._toggle_preferred(index.data(Qt.UserRole))
        if (source is self.combo.view() and event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_D and event.modifiers() & Qt.ControlModifier):
            return self._toggle_preferred(
                self.combo.view().currentIndex().data(Qt.UserRole)
            )
        return super().eventFilter(source, event)

    def _toggle_preferred(self, value: object) -> bool:
        if not isinstance(value, str) or value == self.ADD_VALUE or not self.workstation:
            return False
        chosen = None if value == self.preferred_account else value
        self.preferred_toggled.emit(self.workstation, chosen)
        self.combo.hidePopup()
        return True

    def set_preferred_account(self, account: str | None) -> None:
        if self.preferred_account != account:
            self.preferred_account = account
            self.combo.view().viewport().update()

    def set_workstation(self, workstation: Workstation | None, user: User) -> None:
        self.workstation, self.user = workstation, user
        if self.combo.view().isVisible():
            return
        content_key = (
            workstation.workstation_id if workstation else None,
            workstation.username_hint if workstation else None,
            tuple(workstation.login_accounts) if workstation else (),
            tuple(workstation.session_accounts()) if workstation else (),
            workstation.selected_login_account if workstation else None,
            user.get_rdp_username(),
            tuple(user.own_accounts),
            tuple(user.shared_accounts),
        )
        if content_key == self._content_key:
            return
        self._content_key = content_key
        self.combo.blockSignals(True)
        self.combo.clear()
        if workstation:
            default = workstation.username_hint or user.get_rdp_username() or "Windows-Anmeldung"
            self.combo.addItem(f"Standard · {default}", "")
            for account in workstation.login_accounts:
                self.combo.addItem(account, account)
            # Die eigenen Konten aus den Einstellungen, damit sie nicht bei jeder
            # Maschine einzeln hinterlegt werden muessen. Ein Entra-Profilname
            # bleibt draussen: Mit ihm lehnt Windows jede Anmeldung ab.
            for account in user.own_accounts:
                if (
                    is_entra_profile_name(account)
                    or same_account_name(account, default)
                    or self._listed(account)
                ):
                    continue
                prefix = "Gemeinsam" if user.is_shared_account(account) else "Eigenes"
                self.combo.addItem(f"{prefix} · {account}", account)
            for account in workstation.session_accounts():
                if self.combo.findData(account) < 0:
                    self.combo.addItem(f"Angemeldet · {account}", account)
            chosen = workstation.selected_login_account or ""
            # Die gespeicherte Wahl steht nicht zwangslaeufig in der Liste: sie
            # kommt dort nur vor, solange sie unter login_accounts gefuehrt wird
            # oder gerade als Sitzung gemeldet ist. Meldet der Agent dieselbe
            # Person unter einer anderen Schreibweise -- bei Entra der Profilname
            # statt der UPN -- verschwand der Eintrag, findData lieferte -1 und
            # die Auswahl sprang stillschweigend auf "Standard" zurueck.
            if chosen and self.combo.findData(chosen) < 0:
                self.combo.addItem(f"Gewählt · {chosen}", chosen)
            self.combo.insertSeparator(self.combo.count())
            self.combo.addItem("+ Benutzer hinzufügen …", self.ADD_VALUE)
            self.combo.setCurrentIndex(max(0, self.combo.findData(chosen)))
        self.combo.setEnabled(workstation is not None)
        self.combo.blockSignals(False)

    def _listed(self, account: str) -> bool:
        """Ob die Auswahl dieses Konto schon führt, in welcher Schreibweise auch immer."""
        return any(
            same_account_name(self.combo.itemData(row), account)
            for row in range(self.combo.count())
            if isinstance(self.combo.itemData(row), str) and self.combo.itemData(row)
        )

    def _activated(self, index: int) -> None:
        if self.workstation is None:
            return
        value = self.combo.itemData(index)
        if value == self.ADD_VALUE:
            self.combo.setCurrentIndex(max(0, self.combo.findData(self.workstation.selected_login_account or "")))
            self.add_requested.emit(self.workstation)
        elif isinstance(value, str):
            self.account_selected.emit(self.workstation, value)
