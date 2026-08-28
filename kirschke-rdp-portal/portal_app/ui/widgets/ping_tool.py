"""Reusable asynchronous ping tool for arbitrary safe host targets."""

from __future__ import annotations

import locale
import re

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from shared.validation import RDPProfileValidator, RDPValidationError


class PingToolWidget(QFrame):
    """Run ping without opening a terminal or accepting command options."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pingTool")
        self.process: QProcess | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(9)
        title = QLabel("Freier Ping")
        title.setObjectName("pingTitle")
        layout.addWidget(title)
        self.target = QLineEdit()
        self.target.setObjectName("pingInput")
        self.target.setPlaceholderText("Hostname oder IP-Adresse")
        self.target.setMinimumWidth(230)
        self.target.returnPressed.connect(self.start_ping)
        layout.addWidget(self.target)
        self.result = QLabel("Bereit")
        self.result.setObjectName("pingResult")
        self.result.setMinimumWidth(110)
        self.result.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.result)
        self.button = QPushButton("Ping")
        self.button.setObjectName("toolbarButton")
        self.button.clicked.connect(self.start_ping)
        layout.addWidget(self.button)

    def start_ping(self) -> None:
        if self.process is not None:
            return
        target = self.target.text().strip()
        try:
            RDPProfileValidator.validate_hostname(target)
        except RDPValidationError:
            self._set_result("Ungültiges Ziel", False)
            self.target.setFocus()
            return
        self.result.setText("Prüfe …")
        self.result.setProperty("pingOk", None)
        self.button.setEnabled(False)
        process = QProcess(self)
        self.process = process
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._error)
        process.start("ping", ["-n", "1", "-w", "2000", target])

    def _finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        success = exit_code == 0 and exit_status == QProcess.NormalExit
        detail = self._latency_text() if success else None
        self._set_result(f"Erreichbar{f' · {detail}' if detail else ''}" if success else "Nicht erreichbar", success)
        self._cleanup()

    def _latency_text(self) -> str | None:
        if not self.process:
            return None
        encoding = locale.getpreferredencoding(False)
        output = bytes(self.process.readAllStandardOutput()).decode(encoding, errors="replace")
        match = re.search(r"(?:zeit|time)[=<]\s*(\d+)\s*ms", output, re.IGNORECASE)
        return f"{match.group(1)} ms" if match else None

    def _error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.FailedToStart:
            self._set_result("Ping nicht verfügbar", False)
            self._cleanup()

    def _set_result(self, text: str, success: bool) -> None:
        self.result.setText(text)
        self.result.setProperty("pingOk", success)
        self.result.style().unpolish(self.result)
        self.result.style().polish(self.result)

    def _cleanup(self) -> None:
        self.button.setEnabled(True)
        if self.process:
            self.process.deleteLater()
        self.process = None


__all__ = ["PingToolWidget"]
