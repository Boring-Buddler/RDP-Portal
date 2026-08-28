"""Two-week workstation reservation calendar."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.reservation import Reservation
from portal_app.models.user import User
from portal_app.models.workstation import Workstation

RESERVATION_COLORS = (
    ("Blau", "#5d86a4"),
    ("Grün", "#5f8b70"),
    ("Orange", "#c1804b"),
    ("Violett", "#7a6b9d"),
    ("Rot", "#a85f62"),
)


class ReservationDialog(QDialog):
    def __init__(
        self,
        workstations: list[Workstation],
        user: User,
        reservation: Reservation | None = None,
        default_day: date | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.workstations = workstations
        self.user = user
        self.original = reservation
        self.reservation: Reservation | None = None
        self.delete_requested = False
        self.setWindowTitle("Reservierung bearbeiten" if reservation else "Maschine reservieren")
        self.setMinimumWidth(480)
        self._create_ui(default_day or date.today())
        if reservation:
            self._load(reservation)

    def _create_ui(self, default_day: date) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)
        heading = QLabel("Reservierung")
        heading.setObjectName("dialogTitle")
        root.addWidget(heading)
        form = QFormLayout()
        form.setSpacing(12)
        self.machine = QComboBox()
        for workstation in self.workstations:
            self.machine.addItem(workstation.display_name, workstation.workstation_id)
        self.title = QLineEdit("Reserviert")
        self.start = QDateTimeEdit()
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat("dd.MM.yyyy  HH:mm")
        self.start.setDateTime(QDateTime(datetime.combine(default_day, time(9, 0))))
        self.end = QDateTimeEdit()
        self.end.setCalendarPopup(True)
        self.end.setDisplayFormat("dd.MM.yyyy  HH:mm")
        self.end.setDateTime(QDateTime(datetime.combine(default_day, time(17, 0))))
        self.color = QComboBox()
        for name, value in RESERVATION_COLORS:
            self.color.addItem(name, value)
            self.color.setItemData(self.color.count() - 1, QColor(value), Qt.DecorationRole)
        form.addRow("Maschine", self.machine)
        form.addRow("Titel", self.title)
        form.addRow("Von", self.start)
        form.addRow("Bis", self.end)
        form.addRow("Farbe", self.color)
        root.addLayout(form)
        actions = QHBoxLayout()
        if self.original:
            delete = QPushButton("Reservierung löschen")
            delete.setObjectName("dangerButton")
            delete.clicked.connect(self._delete)
            actions.addWidget(delete)
        actions.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Speichern")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        root.addLayout(actions)

    def _load(self, reservation: Reservation) -> None:
        self.machine.setCurrentIndex(max(0, self.machine.findData(reservation.workstation_id)))
        self.title.setText(reservation.title)
        self.start.setDateTime(QDateTime(reservation.start))
        self.end.setDateTime(QDateTime(reservation.end))
        self.color.setCurrentIndex(max(0, self.color.findData(reservation.color)))

    def _accept(self) -> None:
        start = self.start.dateTime().toPython()
        end = self.end.dateTime().toPython()
        if end <= start:
            QMessageBox.warning(self, "Zeitraum", "Das Ende muss nach dem Beginn liegen.")
            return
        kwargs = {
            "workstation_id": self.machine.currentData(),
            "title": self.title.text().strip() or "Reserviert",
            "start": start,
            "end": end,
            "reserved_by": self.user.upn,
            "color": self.color.currentData(),
        }
        if self.original:
            kwargs["reservation_id"] = self.original.reservation_id
        self.reservation = Reservation(**kwargs)
        self.accept()

    def _delete(self) -> None:
        if QMessageBox.question(self, "Reservierung löschen", "Diese Reservierung wirklich löschen?") == QMessageBox.Yes:
            self.delete_requested = True
            self.accept()


class ReservationCalendarWidget(QWidget):
    """Outlook-like two-week grid with machines as rows and days as tiles."""

    reservations_changed = Signal(list)

    def __init__(
        self,
        workstations: list[Workstation],
        reservations: list[Reservation],
        user: User,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.workstations = workstations
        self.reservations = reservations
        self.user = user
        self.start_day = date.today()
        self.days = 14
        self._create_ui()
        self.refresh()

    def _create_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        toolbar = QHBoxLayout()
        previous = QPushButton("← 2 Wochen")
        previous.setObjectName("toolbarButton")
        previous.clicked.connect(lambda: self._move(-14))
        toolbar.addWidget(previous)
        today = QPushButton("Heute")
        today.setObjectName("toolbarButton")
        today.clicked.connect(self._today)
        toolbar.addWidget(today)
        following = QPushButton("2 Wochen →")
        following.setObjectName("toolbarButton")
        following.clicked.connect(lambda: self._move(14))
        toolbar.addWidget(following)
        toolbar.addStretch()
        self.range_label = QLabel()
        self.range_label.setObjectName("calendarRange")
        toolbar.addWidget(self.range_label)
        toolbar.addStretch()
        add = QPushButton("+ Reservierung")
        add.setObjectName("cardPrimaryButton")
        add.clicked.connect(self._add)
        toolbar.addWidget(add)
        root.addLayout(toolbar)

        self.table = QTableWidget()
        self.table.setObjectName("calendarTable")
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectItems)
        self.table.setShowGrid(True)
        self.table.verticalHeader().setDefaultSectionSize(54)
        self.table.verticalHeader().setMinimumWidth(150)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._cell_double_clicked)
        root.addWidget(self.table, 1)

    def refresh(self) -> None:
        dates = [self.start_day + timedelta(days=offset) for offset in range(self.days)]
        self.range_label.setText(f"{dates[0].strftime('%d.%m.%Y')} – {dates[-1].strftime('%d.%m.%Y')}")
        self.table.setColumnCount(self.days)
        self.table.setRowCount(len(self.workstations))
        self.table.setHorizontalHeaderLabels([f"{day.strftime('%a')}\n{day.strftime('%d.%m.')}" for day in dates])
        self.table.setVerticalHeaderLabels([ws.display_name for ws in self.workstations])
        for row, workstation in enumerate(self.workstations):
            for column, day in enumerate(dates):
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                if day == date.today():
                    item.setBackground(QColor("#eef4f8"))
                matches = self._reservations_for(workstation.workstation_id, day)
                if matches:
                    reservation = matches[0]
                    item.setBackground(QColor(reservation.color))
                    item.setForeground(QColor("#ffffff"))
                    if reservation.start.date() == day or column == 0:
                        item.setText(reservation.title)
                    item.setToolTip(
                        f"{reservation.title}\n"
                        f"{reservation.start.strftime('%d.%m.%Y %H:%M')} – "
                        f"{reservation.end.strftime('%d.%m.%Y %H:%M')}\n"
                        f"Reserviert von {reservation.reserved_by}"
                    )
                    item.setData(Qt.UserRole, reservation.reservation_id)
                self.table.setItem(row, column, item)

    def _reservations_for(self, workstation_id: str, day: date) -> list[Reservation]:
        day_start = datetime.combine(day, time.min)
        day_end = day_start + timedelta(days=1)
        return [
            reservation
            for reservation in self.reservations
            if reservation.workstation_id == workstation_id and reservation.overlaps_day(day_start, day_end)
        ]

    def set_workstations(self, workstations: list[Workstation]) -> None:
        self.workstations = workstations
        self.refresh()

    def set_user(self, user: User) -> None:
        self.user = user

    def _move(self, days: int) -> None:
        self.start_day += timedelta(days=days)
        self.refresh()

    def _today(self) -> None:
        self.start_day = date.today()
        self.refresh()

    def _add(self) -> None:
        selected_day = self.start_day
        if self.table.currentColumn() >= 0:
            selected_day += timedelta(days=self.table.currentColumn())
        dialog = ReservationDialog(self.workstations, self.user, default_day=selected_day, parent=self)
        if dialog.exec() == QDialog.Accepted and dialog.reservation:
            if self._has_conflict(dialog.reservation):
                QMessageBox.warning(
                    self,
                    "Zeitraum belegt",
                    "Für diese Maschine existiert in diesem Zeitraum bereits eine Reservierung.",
                )
                return
            self.reservations.append(dialog.reservation)
            self.refresh()
            self.reservations_changed.emit(self.reservations)

    def _cell_double_clicked(self, row: int, column: int) -> None:
        item = self.table.item(row, column)
        reservation_id = item.data(Qt.UserRole) if item else None
        if not reservation_id:
            self.table.setCurrentCell(row, column)
            self._add()
            return
        reservation = next((item for item in self.reservations if item.reservation_id == reservation_id), None)
        if not reservation:
            return
        self._edit_reservation(reservation)

    def _selected_reservation(self) -> Reservation | None:
        item = self.table.currentItem()
        reservation_id = item.data(Qt.UserRole) if item else None
        if not reservation_id:
            return None
        return next(
            (reservation for reservation in self.reservations if reservation.reservation_id == reservation_id),
            None,
        )

    def _edit_reservation(self, reservation: Reservation) -> None:
        dialog = ReservationDialog(self.workstations, self.user, reservation=reservation, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        index = self.reservations.index(reservation)
        if dialog.delete_requested:
            self.reservations.pop(index)
        elif dialog.reservation:
            if self._has_conflict(dialog.reservation, reservation.reservation_id):
                QMessageBox.warning(
                    self,
                    "Zeitraum belegt",
                    "Für diese Maschine existiert in diesem Zeitraum bereits eine Reservierung.",
                )
                return
            self.reservations[index] = dialog.reservation
        self.refresh()
        self.reservations_changed.emit(self.reservations)

    def _delete_selected_reservation(self) -> None:
        reservation = self._selected_reservation()
        if not reservation:
            return
        answer = QMessageBox.warning(
            self,
            "Reservierung löschen",
            f"Die Reservierung „{reservation.title}“ für diese Maschine wirklich löschen?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        self.reservations.remove(reservation)
        self.refresh()
        self.reservations_changed.emit(self.reservations)

    def _has_conflict(self, candidate: Reservation, ignore_id: str | None = None) -> bool:
        return any(
            reservation.reservation_id != ignore_id
            and reservation.workstation_id == candidate.workstation_id
            and reservation.start < candidate.end
            and reservation.end > candidate.start
            for reservation in self.reservations
        )


__all__ = ["ReservationCalendarWidget", "ReservationDialog"]
