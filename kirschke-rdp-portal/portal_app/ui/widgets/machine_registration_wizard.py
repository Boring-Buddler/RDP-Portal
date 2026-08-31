"""Guided registration for a local or remote workstation."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from portal_app.services.machine_discovery import MachineDiscovery, discover_local_machine, discover_remote_machine


class MachineRegistrationWizard(QWizard):
    """Collect and preview automatically discovered workstation information."""

    SOURCE_PAGE = 0
    PREVIEW_PAGE = 1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.discovery = MachineDiscovery()
        self.setObjectName("machineRegistrationWizard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("Maschine registrieren")
        self.setMinimumSize(760, 600)
        self.resize(780, 620)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.addPage(_SourcePage(self))
        self.addPage(_PreviewPage(self))
        self.setButtonText(QWizard.NextButton, "Ermitteln")
        self.setButtonText(QWizard.FinishButton, "Profil einrichten")
        self.setButtonText(QWizard.CancelButton, "Abbrechen")

    @property
    def prefill(self) -> dict[str, str]:
        page = self.page(self.PREVIEW_PAGE)
        return page.values() if isinstance(page, _PreviewPage) else self.discovery.as_prefill()


class _SourcePage(QWizardPage):
    def __init__(self, wizard: MachineRegistrationWizard) -> None:
        super().__init__(wizard)
        self.setObjectName("machineWizardPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setTitle("Welche Maschine soll registriert werden?")
        self.setSubTitle("Die Erkennung füllt Hostname, FQDN und Netzwerkdaten soweit ohne Agent möglich aus.")
        layout = QVBoxLayout(self)
        self.local = QRadioButton("Diesen lokalen Rechner registrieren")
        self.remote = QRadioButton("Zielrechner im Netzwerk registrieren")
        self.local.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.local)
        group.addButton(self.remote)
        layout.addWidget(self.local)
        layout.addWidget(self.remote)
        self.target = QLineEdit()
        self.target.setPlaceholderText("IP-Adresse, Hostname oder FQDN, z. B. 192.168.2.68")
        self.target.setEnabled(False)
        layout.addWidget(QLabel("Zielrechner"))
        layout.addWidget(self.target)
        note = QLabel(
            "Beim Zielrechner nutzt die App DNS (Vorw\u00e4rts- und Reverse-Lookup). "
            "Subnetzmaske, Gateway und DNS des Zielrechners ben\u00f6tigen einen Agenten oder Fernverwaltung."
        )
        note.setObjectName("dialogNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.local.toggled.connect(lambda checked: self.target.setEnabled(not checked))
        self.target.textChanged.connect(self.completeChanged)

    def isComplete(self) -> bool:  # noqa: N802
        return self.local.isChecked() or bool(self.target.text().strip())

    def validatePage(self) -> bool:  # noqa: N802
        wizard = self.wizard()
        if not isinstance(wizard, MachineRegistrationWizard):
            return False
        wizard.discovery = discover_local_machine() if self.local.isChecked() else discover_remote_machine(self.target.text())
        return True


class _PreviewPage(QWizardPage):
    FIELDS = (
        ("display_name", "Anzeigename"),
        ("hostname", "Hostname"),
        ("fqdn", "FQDN"),
        ("ip_address", "IP-Adresse"),
        ("subnet_mask", "Subnetzmaske"),
        ("default_gateway", "Standardgateway"),
        ("dns_server", "DNS-Server"),
    )

    def __init__(self, wizard: MachineRegistrationWizard) -> None:
        super().__init__(wizard)
        self.setObjectName("machineWizardPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setTitle("Ermittelte Daten prüfen")
        self.setSubTitle("Die Werte sind editierbar. Anschließend ergänzen Sie bei Bedarf die RDP-Einstellungen.")
        layout = QVBoxLayout(self)
        self.message = QLabel()
        self.message.setObjectName("dialogNote")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.inputs: dict[str, QLineEdit] = {}
        for key, label in self.FIELDS:
            field = QLineEdit()
            field.setMinimumHeight(36)
            self.inputs[key] = field
            form.addRow(label, field)
        layout.addLayout(form)

    def initializePage(self) -> None:  # noqa: N802
        wizard = self.wizard()
        if not isinstance(wizard, MachineRegistrationWizard):
            return
        self.message.setText(wizard.discovery.message)
        for key, value in wizard.discovery.as_prefill().items():
            self.inputs[key].setText(value)

    def values(self) -> dict[str, str]:
        return {key: field.text().strip() for key, field in self.inputs.items()}


__all__ = ["MachineRegistrationWizard"]
