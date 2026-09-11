"""Explicit live agent request without blocking the UI thread."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout
from shared.status_pipe import request_snapshot


class LiveStatusWorker(QThread):
    result = Signal(object, int)
    failure = Signal(str)

    def __init__(self, target, parent=None):
        super().__init__(parent)
        self.target = target

    def run(self):
        try:
            snapshot, elapsed = request_snapshot(self.target)
            self.result.emit(snapshot, elapsed)
        except Exception as exc:
            code = getattr(exc, "winerror", None) or type(exc).__name__
            self.failure.emit(f"Live-Abfrage fehlgeschlagen ({code}). Agent 1.2.0 muss auf dem Zielrechner laufen. "
                "Die Windows-Netzwerkverbindung muss mit dessen lokalem Lesekonto PortalLeser bestehen. "
                "Prüfe die Netzwerkfreigabe im Konfigurator. Der bisherige Status wurde nicht als aktuell bestätigt.")


class LiveStatusDialog(QDialog):
    def __init__(self, target, parent=None):
        super().__init__(parent)
        self.snapshot = None
        self.elapsed = None
        self.setWindowTitle("Agent live abfragen")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        self.status = QLabel(f"Direkte Statusanfrage an {target} …\nDie Netzwerkverbindung kann einige Sekunden benötigen.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.close_button = QPushButton("Schließen")
        self.close_button.setObjectName("toolbarButton")
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button)
        self.worker = LiveStatusWorker(target, self)
        self.worker.result.connect(self._result)
        self.worker.failure.connect(self.status.setText)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _result(self, snapshot, elapsed):
        self.snapshot, self.elapsed = snapshot, elapsed

    def _finished(self):
        self.close_button.setEnabled(True)
        if self.snapshot is not None:
            self.accept()

    def reject(self):
        if not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
