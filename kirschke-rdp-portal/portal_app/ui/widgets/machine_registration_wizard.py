"""Guided registration and connection setup for workstations.

Three routes end here, and they exist because the old wizard only covered the
last one:

* **Agenten suchen** -- sweep the network, list every machine that runs an agent,
  and set several of them up in one pass.  This is the route a first install
  takes, and the one that closes the gap where agent assignment could only pick
  from a status folder that did not exist yet.
* **Diesen Rechner** and **Zielrechner** -- the original DNS-based discovery for
  a single machine, unchanged apart from the site it now fills in.

The wizard collects decisions and never writes anything.  Creating machines,
storing the agent assignment and connecting the fallback share all happen in
``MainWindow``, which owns the inventory and the store.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from portal_app.services.agent_discovery import (
    AgentProbe,
    AgentScanner,
    local_sweep_networks,
    probe_prefill,
    sweep_addresses,
)
from portal_app.services.machine_discovery import (
    MachineDiscovery,
    discover_local_machine,
    discover_remote_machine,
)
from portal_app.services.site_mapping import known_sites, site_for_address
from portal_app.ui.widgets.scroll_safe_combo import ScrollSafeComboBox as QComboBox
from portal_app.ui.widgets.table_cells import reset_rows

#: Sentinel in the target combo box meaning "create a machine for this agent".
NEW_MACHINE = "__new__"

#: Sentinel meaning "leave this agent alone for now".
SKIP_MACHINE = "__skip__"


@dataclass
class AgentAssignment:
    """One found agent and what the user decided to do with it."""

    probe: AgentProbe
    #: Existing machine to link to, or "" when a new machine should be created.
    workstation_id: str = ""
    display_name: str = ""
    site: str = ""

    @property
    def creates_machine(self) -> bool:
        return not self.workstation_id

    def prefill(self) -> dict[str, str]:
        """Machine form values for a newly created machine."""
        values = probe_prefill(self.probe)
        if self.display_name:
            values["display_name"] = self.display_name
        if self.site:
            values["site"] = self.site
        return values


class MachineRegistrationWizard(QWizard):
    """Collect and preview automatically discovered workstation information."""

    SOURCE_PAGE = 0
    SCAN_PAGE = 1
    ASSIGN_PAGE = 2
    PREVIEW_PAGE = 3

    def __init__(self, parent=None, workstations=None, *, first_run: bool = False) -> None:
        super().__init__(parent)
        self.discovery = MachineDiscovery()
        self.workstations = list(workstations or [])
        self.first_run = first_run
        #: Agents the sweep found, in the order they answered.
        self.probes: list[AgentProbe] = []
        #: What the user decided for the agents they picked. Read after exec().
        self.assignments: list[AgentAssignment] = []
        self.mode = "scan"
        self.setObjectName("machineRegistrationWizard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle(
            "Verbindungsassistent – Erstinstallation" if first_run else "Maschine registrieren"
        )
        self.setMinimumSize(760, 600)
        self.resize(900, 680)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.IndependentPages, False)
        self.addPage(_SourcePage(self))
        self.addPage(_ScanPage(self))
        self.addPage(_AssignPage(self))
        self.addPage(_PreviewPage(self))
        self.setButtonText(QWizard.NextButton, "Weiter")
        self.setButtonText(QWizard.BackButton, "Zurück")
        self.setButtonText(QWizard.FinishButton, "Profil einrichten")
        self.setButtonText(QWizard.CancelButton, "Abbrechen")

    @property
    def prefill(self) -> dict[str, str]:
        page = self.page(self.PREVIEW_PAGE)
        return page.values() if isinstance(page, _PreviewPage) else self.discovery.as_prefill()

    @property
    def selected_probe(self) -> AgentProbe | None:
        """The single agent chosen on the manual route, if one was matched."""
        return self.assignments[0].probe if self.assignments else None

    def done(self, result: int) -> None:
        """Stop a running sweep before the wizard goes away.

        Its thread pool waits for outstanding probes when it is destroyed, so a
        sweep abandoned halfway would hold the closed wizard -- and with it the
        portal -- for as long as the remaining addresses take to time out.
        """
        page = self.page(self.SCAN_PAGE)
        if isinstance(page, _ScanPage):
            page.scanner.stop()
        super().done(result)

    def machine_choices(self) -> list[tuple[str, str]]:
        """(label, workstation_id) for every machine an agent could link to."""
        return [
            (f"{ws.display_name} · {ws.workstation_id}", ws.workstation_id)
            for ws in self.workstations
        ]

    def assigned_agent_ids(self) -> dict[str, str]:
        """Agent ID (casefolded) to the machine that already claims it."""
        result: dict[str, str] = {}
        for ws in self.workstations:
            key = (ws.agent_workstation_id or ws.workstation_id).strip().casefold()
            if key:
                result[key] = ws.display_name
        return result


class _SourcePage(QWizardPage):
    def __init__(self, wizard: MachineRegistrationWizard) -> None:
        super().__init__(wizard)
        self.setObjectName("machineWizardPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setTitle("Welche Maschine soll registriert werden?")
        self.setSubTitle(
            "Die Suche findet Rechner, auf denen der Kirschke-Agent läuft, und richtet "
            "Verbindung und Datei-Fallback gleich mit ein."
        )
        layout = QVBoxLayout(self)
        self.scan = QRadioButton("Agenten im Netzwerk suchen (empfohlen)")
        self.local = QRadioButton("Diesen lokalen Rechner registrieren")
        self.remote = QRadioButton("Zielrechner manuell eintragen")
        self.scan.setChecked(True)
        group = QButtonGroup(self)
        for button in (self.scan, self.local, self.remote):
            group.addButton(button)
            layout.addWidget(button)
        self.target = QLineEdit()
        self.target.setPlaceholderText("IP-Adresse, Hostname oder FQDN, z. B. 192.168.2.68")
        self.target.setEnabled(False)
        layout.addWidget(QLabel("Zielrechner"))
        layout.addWidget(self.target)
        note = QLabel(
            "Die Suche klopft jede Adresse des gewählten Bereichs daraufhin ab, ob dort der "
            "Statuskanal des Agenten antwortet. Sie ändert auf den Zielrechnern nichts.\n"
            "Beim manuellen Weg nutzt die App DNS (Vorwärts- und Reverse-Lookup); "
            "Subnetzmaske, Gateway und DNS des Zielrechners benötigen einen Agenten."
        )
        note.setObjectName("dialogNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.remote.toggled.connect(self.target.setEnabled)
        self.remote.toggled.connect(self.completeChanged)
        self.target.textChanged.connect(self.completeChanged)

    def isComplete(self) -> bool:  # noqa: N802
        return not self.remote.isChecked() or bool(self.target.text().strip())

    def nextId(self) -> int:  # noqa: N802
        return (
            MachineRegistrationWizard.SCAN_PAGE
            if self.scan.isChecked()
            else MachineRegistrationWizard.PREVIEW_PAGE
        )

    def validatePage(self) -> bool:  # noqa: N802
        wizard = self.wizard()
        if not isinstance(wizard, MachineRegistrationWizard):
            return False
        if self.scan.isChecked():
            wizard.mode = "scan"
            return True
        wizard.mode = "local" if self.local.isChecked() else "remote"
        wizard.discovery = (
            discover_local_machine()
            if self.local.isChecked()
            else discover_remote_machine(self.target.text())
        )
        return True


class ReaderCredentialFields(QWidget):
    """The reader-account fields, kept out of sight until they are needed.

    With a password shipped in the release the normal first run needs no
    credentials at all, and asking anyway invites somebody to type a second,
    different password and then wonder why one machine behaves unlike the rest.
    The fields appear when there is nothing to fall back on, or when an agent was
    found that the release password cannot read -- which is what they are for.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.user = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.hint = QLabel()
        self.hint.setObjectName("dialogNote")
        self.hint.setWordWrap(True)
        layout.addRow("Lesekonto", self.user)
        layout.addRow("Kennwort", self.password)
        layout.addRow("", self.hint)
        self.setVisible(False)

    def load_account(self) -> None:
        """Fill in the account in use and say where it came from."""
        from portal_app.services.reader_account import DEFAULT_READER_ACCOUNT
        from portal_app.services.share_connection import (
            reader_account_name,
            reader_account_source,
        )

        try:
            name, source = reader_account_name(), reader_account_source()
        except Exception:  # noqa: BLE001 - an absent credential store is not an error
            name, source = DEFAULT_READER_ACCOUNT, "none"
        if not self.user.text().strip():
            self.user.setText(name or DEFAULT_READER_ACCOUNT)
        self.hint.setText(
            {
                "bundled": "Dieses Portal bringt ein Lesekonto mit. Hier nur eintragen, was "
                "auf einem abweichend eingerichteten Rechner gilt.",
                "stored": "Auf diesem PC ist bereits ein Lesekonto hinterlegt. Ein neuer "
                "Eintrag ersetzt es.",
            }.get(
                source,
                "Das gemeinsame Lesekonto der Agent-Setups. Windows speichert das Kennwort in "
                "der Anmeldeinformationsverwaltung dieses Benutzers; das Portal schreibt es in "
                "keine Datei.",
            )
        )
        # Nothing on board and nothing stored: there is no other way in, so ask
        # straight away rather than after a fruitless sweep.
        if source == "none":
            self.setVisible(True)

    def save(self) -> None:
        """Store what was typed, so the sweep and every later start can use it."""
        from portal_app.services.share_connection import save_reader_credentials

        username, password = self.user.text().strip(), self.password.text()
        if not username or not password:
            return
        try:
            save_reader_credentials(username, password)
        except Exception as exc:  # noqa: BLE001 - reported, never fatal to the sweep
            self.hint.setText(f"Zugangsdaten konnten nicht gespeichert werden: {exc}")
        finally:
            self.password.clear()


class _ScanPage(QWizardPage):
    """Sweep for agents and let the user pick the ones to set up."""

    def __init__(self, wizard: MachineRegistrationWizard) -> None:
        super().__init__(wizard)
        self.setObjectName("machineWizardPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setTitle("Agenten suchen")
        self.setSubTitle(
            "Gefundene Agenten mehrfach auswählbar. Ein Agent, der sich nicht identifiziert, "
            "läuft zwar, lässt das Portal aber noch nicht lesen."
        )
        self.scanner = AgentScanner(parent=self)
        self.scanner.found.connect(self._on_found)
        self.scanner.progress.connect(self._on_progress)
        self.scanner.finished.connect(self._on_finished)
        layout = QVBoxLayout(self)
        form = QHBoxLayout()
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText("192.168.2.0/24, 192.168.20.0/24")
        form.addWidget(QLabel("Suchbereich"), 0)
        form.addWidget(self.ranges, 1)
        self.start_button = QPushButton("Suche starten")
        self.start_button.setObjectName("cardPrimaryButton")
        self.start_button.clicked.connect(self._toggle_scan)
        form.addWidget(self.start_button)
        layout.addLayout(form)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("Noch nicht gesucht")
        layout.addWidget(self.progress)
        self.results = QListWidget()
        self.results.setSelectionMode(QAbstractItemView.NoSelection)
        self.results.itemChanged.connect(lambda _: self.completeChanged.emit())
        layout.addWidget(self.results, 1)
        self.credentials = ReaderCredentialFields(self)
        layout.addWidget(self.credentials)
        self.status = QLabel()
        self.status.setObjectName("dialogNote")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    @property
    def reader_user(self) -> QLineEdit:
        return self.credentials.user

    @property
    def reader_password(self) -> QLineEdit:
        return self.credentials.password

    def initializePage(self) -> None:  # noqa: N802
        if not self.ranges.text().strip():
            self.ranges.setText(", ".join(local_sweep_networks()))
        self.credentials.load_account()

    def isComplete(self) -> bool:  # noqa: N802
        return bool(self._checked_probes()) and not self.scanner.running

    def nextId(self) -> int:  # noqa: N802
        return MachineRegistrationWizard.ASSIGN_PAGE

    @Slot()
    def _toggle_scan(self) -> None:
        if self.scanner.running:
            self.scanner.cancel()
            self.status.setText("Suche wird abgebrochen …")
            return
        self.credentials.save()
        try:
            targets = sweep_addresses(
                [part.strip() for part in self.ranges.text().split(",") if part.strip()]
            )
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if not targets:
            self.status.setText("Bitte mindestens einen Bereich angeben, etwa 192.168.2.0/24.")
            return
        wizard = self.wizard()
        if isinstance(wizard, MachineRegistrationWizard):
            wizard.probes = []
        self.results.clear()
        self.progress.setRange(0, len(targets))
        self.progress.setValue(0)
        self.progress.setFormat("%v von %m Adressen geprüft")
        self.status.setText("")
        self.start_button.setText("Suche abbrechen")
        self.scanner.start(targets)
        self.completeChanged.emit()

    @Slot(object)
    def _on_found(self, probe: object) -> None:
        if not isinstance(probe, AgentProbe):
            return
        wizard = self.wizard()
        assigned = (
            wizard.assigned_agent_ids() if isinstance(wizard, MachineRegistrationWizard) else {}
        )
        if isinstance(wizard, MachineRegistrationWizard):
            wizard.probes.append(probe)
        claimed = assigned.get(probe.workstation_id.casefold()) if probe.identified else None
        label = probe.label()
        if claimed:
            label += f" · bereits zugeordnet zu {claimed}"
        item = QListWidgetItem(label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        # Pre-select what is actually actionable: an identified agent that no
        # machine claims yet. Everything else has to be ticked deliberately.
        item.setCheckState(Qt.Checked if probe.identified and not claimed else Qt.Unchecked)
        item.setData(Qt.UserRole, probe)
        if not probe.identified:
            item.setToolTip(probe.message)
        self.results.addItem(item)

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setValue(done)
        self.progress.setMaximum(total)

    @Slot(int)
    def _on_finished(self, found: int) -> None:
        self.start_button.setText("Suche wiederholen")
        unreadable = sum(
            1
            for index in range(self.results.count())
            if not self.results.item(index).data(Qt.UserRole).identified
        )
        message = f"{found} Agent(en) gefunden."
        if unreadable:
            message += (
                f" Davon {unreadable} ohne Identifikation – Lesekonto und Kennwort eintragen "
                "und die Suche wiederholen."
            )
            # This is the situation the credential fields exist for.
            self.credentials.setVisible(True)
        if not found:
            message += " Bereich, VPN und laufende Agent-Aufgabe prüfen."
        self.status.setText(message)
        self.completeChanged.emit()

    def _checked_probes(self) -> list[AgentProbe]:
        return [
            self.results.item(index).data(Qt.UserRole)
            for index in range(self.results.count())
            if self.results.item(index).checkState() == Qt.Checked
        ]

    def validatePage(self) -> bool:  # noqa: N802
        wizard = self.wizard()
        if not isinstance(wizard, MachineRegistrationWizard):
            return False
        wizard.probes = self._checked_probes()
        return bool(wizard.probes)

    def cleanupPage(self) -> None:  # noqa: N802
        self.scanner.cancel()
        super().cleanupPage()


class _AssignPage(QWizardPage):
    """Decide, per found agent, which machine it belongs to."""

    def __init__(self, wizard: MachineRegistrationWizard) -> None:
        super().__init__(wizard)
        self.setObjectName("machineWizardPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setTitle("Agenten den Maschinen zuordnen")
        self.setSubTitle(
            "Neue Maschinen werden mit den erkannten Netzwerkdaten angelegt. "
            "Der Standort ergibt sich aus der IP-Adresse und bleibt änderbar."
        )
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Agent", "Ziel", "Anzeigename", "Standort"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # Widths are set explicitly rather than by resizeColumnsToContents():
        # that measures the item text and ignores the combo boxes and line edits
        # living in the cells, which left every one of them clipped mid-word.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 260), (2, 170), (3, 150)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().setDefaultSectionSize(38)
        layout.addWidget(self.table, 1)
        note = QLabel(
            "Für jede angelegte Maschine richtet das Portal anschließend den Datei-Fallback "
            "\\\\RECHNER\\RDP-Status ein und verbindet ihn."
        )
        note.setObjectName("dialogNote")
        note.setWordWrap(True)
        layout.addWidget(note)

    def initializePage(self) -> None:  # noqa: N802
        wizard = self.wizard()
        if not isinstance(wizard, MachineRegistrationWizard):
            return
        choices = wizard.machine_choices()
        reset_rows(self.table, len(wizard.probes))
        for row, probe in enumerate(wizard.probes):
            agent = QTableWidgetItem(probe.label())
            agent.setData(Qt.UserRole, probe)
            self.table.setItem(row, 0, agent)
            target = QComboBox()
            target.addItem("Neue Maschine anlegen", NEW_MACHINE)
            for label, workstation_id in choices:
                target.addItem(f"Verknüpfen: {label}", workstation_id)
            target.addItem("Vorerst überspringen", SKIP_MACHINE)
            self.table.setCellWidget(row, 1, target)
            name = QLineEdit(probe.hostname or probe.target)
            self.table.setCellWidget(row, 2, name)
            site = QComboBox()
            site.setEditable(True)
            site.addItem("")
            for known in known_sites():
                site.addItem(known)
            site.setCurrentText(site_for_address(probe.target))
            self.table.setCellWidget(row, 3, site)

    def nextId(self) -> int:  # noqa: N802
        return -1

    def validatePage(self) -> bool:  # noqa: N802
        wizard = self.wizard()
        if not isinstance(wizard, MachineRegistrationWizard):
            return False
        assignments: list[AgentAssignment] = []
        for row in range(self.table.rowCount()):
            probe = self.table.item(row, 0).data(Qt.UserRole)
            target = self.table.cellWidget(row, 1).currentData()
            if target == SKIP_MACHINE:
                continue
            assignments.append(
                AgentAssignment(
                    probe=probe,
                    workstation_id="" if target == NEW_MACHINE else str(target),
                    display_name=self.table.cellWidget(row, 2).text().strip(),
                    site=self.table.cellWidget(row, 3).currentText().strip(),
                )
            )
        wizard.assignments = assignments
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
        ("site", "Standort"),
    )

    def __init__(self, wizard: MachineRegistrationWizard) -> None:
        super().__init__(wizard)
        self.setObjectName("machineWizardPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setTitle("Ermittelte Daten prüfen")
        self.setSubTitle(
            "Die Werte sind editierbar. Anschließend ergänzen Sie bei Bedarf die RDP-Einstellungen."
        )
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
        self.agent_status = QLabel()
        self.agent_status.setObjectName("dialogNote")
        self.agent_status.setWordWrap(True)
        layout.addWidget(self.agent_status)

    def initializePage(self) -> None:  # noqa: N802
        wizard = self.wizard()
        if not isinstance(wizard, MachineRegistrationWizard):
            return
        self.message.setText(wizard.discovery.message)
        for key, value in wizard.discovery.as_prefill().items():
            if key in self.inputs:
                self.inputs[key].setText(value)
        self._probe_agent(wizard)

    def _probe_agent(self, wizard: MachineRegistrationWizard) -> None:
        """Say whether this one machine already runs a reachable agent.

        A single blocking probe is acceptable here where a sweep is not: it is
        one address, bounded by the same short timeout, and the answer decides
        whether the fallback can be set up without asking anything further.
        """
        from PySide6.QtGui import QGuiApplication

        from portal_app.services.agent_discovery import probe_agent

        target = (
            self.inputs["ip_address"].text().strip()
            or self.inputs["hostname"].text().strip()
            or self.inputs["fqdn"].text().strip()
        )
        wizard.assignments = []
        if not target:
            self.agent_status.setText("")
            return
        self.agent_status.setText(f"{target} wird auf einen Agenten geprüft …")
        # Bounded, but a target whose pipe exists and does not answer can use the
        # full request timeout. Say so with the cursor rather than looking hung.
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            probe = probe_agent(target)
        finally:
            QGuiApplication.restoreOverrideCursor()
        if probe.identified:
            wizard.assignments = [
                AgentAssignment(
                    probe=probe,
                    display_name=self.inputs["display_name"].text().strip(),
                    site=self.inputs["site"].text().strip(),
                )
            ]
            self.agent_status.setText(
                f"Agent gefunden: {probe.workstation_id} · {probe.hostname} · "
                f"Version {probe.agent_version or '?'}. Zuordnung und Datei-Fallback "
                "werden mit eingerichtet."
            )
        elif probe.agent_present:
            self.agent_status.setText(probe.message)
        else:
            self.agent_status.setText(
                "Auf diesem Ziel antwortet kein Agent. Die Maschine wird ohne Agent-Zuordnung "
                "angelegt; der Assistent lässt sich später erneut aufrufen."
            )

    def values(self) -> dict[str, str]:
        return {key: field.text().strip() for key, field in self.inputs.items()}

    def validatePage(self) -> bool:  # noqa: N802
        """Carry late edits to name and site into the pending assignment."""
        wizard = self.wizard()
        if isinstance(wizard, MachineRegistrationWizard) and wizard.assignments:
            wizard.assignments[0].display_name = self.inputs["display_name"].text().strip()
            wizard.assignments[0].site = self.inputs["site"].text().strip()
        return True


__all__ = [
    "NEW_MACHINE",
    "SKIP_MACHINE",
    "AgentAssignment",
    "MachineRegistrationWizard",
    "ReaderCredentialFields",
]
