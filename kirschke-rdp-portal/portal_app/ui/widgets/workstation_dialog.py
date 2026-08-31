"""Create and edit workstation connection profiles."""

from __future__ import annotations

import ipaddress
from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.workstation import Workstation
from shared.enums import ConnectionTargetMode
from shared.validation import RDPProfileValidator, RDPValidationError


class WorkstationDialog(QDialog):
    """Form covering machine master data and supported RDP options."""

    def __init__(
        self,
        workstation: Workstation | None = None,
        suggested_id: str = "WS-001",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.original = workstation
        self.suggested_id = suggested_id
        self.workstation: Workstation | None = None
        self.setWindowTitle("Maschine bearbeiten" if workstation else "Maschine hinzufügen")
        self.setMinimumSize(620, 650)
        self._create_ui()
        self._load_values()

    @property
    def should_save(self) -> bool:
        return self.save_settings.isChecked()

    def _create_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)

        heading = QLabel("Verbindungsprofil")
        heading.setObjectName("dialogTitle")
        root.addWidget(heading)
        note = QLabel(
            "Maschinenspezifische Anmeldedaten überschreiben die allgemeinen Benutzereinstellungen. "
            "Passwörter werden nicht in der App gespeichert."
        )
        note.setObjectName("dialogNote")
        note.setWordWrap(True)
        root.addWidget(note)

        tabs = QTabWidget()
        tabs.addTab(self._create_master_tab(), "Stammdaten")
        tabs.addTab(self._create_rdp_tab(), "RDP-Einstellungen")
        root.addWidget(tabs, 1)

        self.save_settings = QCheckBox("Einstellungen lokal speichern")
        self.save_settings.setChecked(True)
        root.addWidget(self.save_settings)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Speichern")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _create_master_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(18, 20, 18, 18)
        form.setSpacing(12)
        self.workstation_id = QLineEdit()
        self.display_name = QLineEdit()
        self.hostname = QLineEdit()
        self.fqdn = QLineEdit()
        self.ip_address = QLineEdit()
        self.subnet_mask = QLineEdit()
        self.default_gateway = QLineEdit()
        self.dns_server = QLineEdit()
        self.site = QLineEdit()
        self.description = QLineEdit()
        self.enabled = QCheckBox("Maschine ist aktiv")
        form.addRow("Maschinen-ID", self.workstation_id)
        form.addRow("Anzeigename *", self.display_name)
        self.hostname.setPlaceholderText("z. B. PC-CAD-01")
        self.fqdn.setPlaceholderText("z. B. PC-CAD-01.firma.local")
        self.ip_address.setPlaceholderText("z. B. 192.168.10.42")
        form.addRow("Hostname", self.hostname)
        form.addRow("FQDN", self.fqdn)
        form.addRow("IP-Adresse", self.ip_address)
        form.addRow("Subnetzmaske", self.subnet_mask)
        form.addRow("Standardgateway", self.default_gateway)
        form.addRow("DNS-Server", self.dns_server)
        form.addRow("Standort", self.site)
        form.addRow("Beschreibung", self.description)
        form.addRow("", self.enabled)
        return page

    def _create_rdp_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(18, 20, 18, 18)
        form.setSpacing(12)
        self.connection_target = QComboBox()
        self.connection_target.addItem(
            "Automatisch (FQDN → Hostname → IP)", ConnectionTargetMode.AUTO.value
        )
        self.connection_target.addItem("IP-Adresse", ConnectionTargetMode.IP_ADDRESS.value)
        self.connection_target.addItem("Hostname", ConnectionTargetMode.HOSTNAME.value)
        self.connection_target.addItem("FQDN", ConnectionTargetMode.FQDN.value)
        self.connection_target.currentIndexChanged.connect(self._update_target_note)
        self.username_hint = QLineEdit()
        self.username_hint.setPlaceholderText("z. B. DOMÄNE\\benutzer oder user@firma.de")
        self.gateway_hostname = QLineEdit()
        self.entra_sso = QCheckBox("Webkonto / Microsoft Entra verwenden (nur Hostname oder FQDN)")
        self.entra_sso.toggled.connect(self._update_target_note)
        self.trust_unverified_server = QCheckBox(
            "Zertifikatswarnung fÃ¼r diese Maschine nach BestÃ¤tigung Ã¼berspringen"
        )
        self.trust_unverified_server.setToolTip(
            "Nur nach PrÃ¼fung der Zieladresse aktivieren. Die ServeridentitÃ¤t wird dann nicht mehr von Windows abgefragt."
        )
        self.hostname.textChanged.connect(self._update_target_note)
        self.fqdn.textChanged.connect(self._update_target_note)
        self.ip_address.textChanged.connect(self._update_target_note)
        self.target_note = QLabel()
        self.target_note.setObjectName("dialogNote")
        self.target_note.setWordWrap(True)
        self.screen_mode = QComboBox()
        self.screen_mode.addItem("Vollbild", "fullscreen")
        self.screen_mode.addItem("Fenster", "windowed")
        self.resolution = QComboBox()
        self.resolution.setEditable(True)
        self.resolution.addItems(["1920x1080", "1600x900", "1366x768", "1280x720"])
        self.use_all_monitors = QCheckBox("Alle Monitore verwenden")
        self.redirect_clipboard = QCheckBox("Zwischenablage")
        self.redirect_drives = QCheckBox("Lokale Laufwerke")
        self.redirect_printers = QCheckBox("Drucker")
        self.redirect_audio = QCheckBox("Audio")
        form.addRow("Verbindungsziel", self.connection_target)
        form.addRow("", self.target_note)
        form.addRow("Maschinen-Benutzername", self.username_hint)
        form.addRow("RD-Gateway", self.gateway_hostname)
        form.addRow("Authentifizierung", self.entra_sso)
        form.addRow("ServeridentitÃ¤t", self.trust_unverified_server)
        form.addRow("Darstellung", self.screen_mode)
        form.addRow("Auflösung", self.resolution)
        form.addRow("Monitore", self.use_all_monitors)
        redirects = QHBoxLayout()
        redirects.addWidget(self.redirect_clipboard)
        redirects.addWidget(self.redirect_drives)
        redirects.addWidget(self.redirect_printers)
        redirects.addWidget(self.redirect_audio)
        form.addRow("Umleitungen", redirects)
        return page

    def _load_values(self) -> None:
        ws = self.original
        self.workstation_id.setText(ws.workstation_id if ws else self.suggested_id)
        self.workstation_id.setReadOnly(ws is not None)
        self.display_name.setText(ws.display_name if ws else "")
        self.hostname.setText(ws.hostname if ws else "")
        self.fqdn.setText(ws.fqdn or "" if ws else "")
        self.ip_address.setText(ws.ip_address or "" if ws else "")
        self.subnet_mask.setText(ws.subnet_mask or "" if ws else "255.255.255.0")
        self.default_gateway.setText(ws.default_gateway or "" if ws else "")
        self.dns_server.setText(ws.dns_server or "" if ws else "")
        self.site.setText(ws.site or "" if ws else "")
        self.description.setText(ws.description or "" if ws else "")
        self.enabled.setChecked(ws.enabled if ws else True)
        self.username_hint.setText(ws.username_hint or "" if ws else "")
        self.gateway_hostname.setText(ws.gateway_hostname or "" if ws else "")
        self.entra_sso.setChecked(ws.entra_sso_enabled if ws else False)
        self.trust_unverified_server.setChecked(ws.trust_unverified_server if ws else False)
        target_mode = ws.connection_target_mode if ws else ConnectionTargetMode.AUTO
        target_index = self.connection_target.findData(target_mode.value)
        self.connection_target.setCurrentIndex(max(0, target_index))
        mode = ws.screen_mode if ws and ws.screen_mode else "fullscreen"
        self.screen_mode.setCurrentIndex(max(0, self.screen_mode.findData(mode)))
        self.resolution.setCurrentText(ws.resolution or "1920x1080" if ws else "1920x1080")
        self.use_all_monitors.setChecked(ws.use_all_monitors if ws else False)
        self.redirect_clipboard.setChecked(ws.redirect_clipboard if ws else True)
        self.redirect_drives.setChecked(ws.redirect_drives if ws else False)
        self.redirect_printers.setChecked(ws.redirect_printers if ws else False)
        self.redirect_audio.setChecked(ws.redirect_audio if ws else True)
        self._update_target_note()

    def _update_target_note(self, _value: object = None) -> None:
        mode = ConnectionTargetMode(self.connection_target.currentData())
        if mode == ConnectionTargetMode.AUTO:
            description = "Die App verwendet zuerst FQDN, dann Hostname und zuletzt die IP-Adresse."
        elif mode == ConnectionTargetMode.IP_ADDRESS:
            description = "Die Verbindung wird direkt zur hinterlegten IP-Adresse aufgebaut."
        elif mode == ConnectionTargetMode.HOSTNAME:
            description = "Die Verbindung verwendet den kurzen Windows-Hostnamen."
        else:
            description = "Die Verbindung verwendet den vollqualifizierten Domänennamen (FQDN)."
        candidates = {
            ConnectionTargetMode.IP_ADDRESS: self.ip_address.text().strip(),
            ConnectionTargetMode.HOSTNAME: self.hostname.text().strip(),
            ConnectionTargetMode.FQDN: self.fqdn.text().strip(),
        }
        if mode == ConnectionTargetMode.AUTO:
            target = next(
                (
                    candidates[candidate]
                    for candidate in (
                        ConnectionTargetMode.FQDN,
                        ConnectionTargetMode.HOSTNAME,
                        ConnectionTargetMode.IP_ADDRESS,
                    )
                    if candidates[candidate]
                ),
                "",
            )
        else:
            target = candidates[mode]
        try:
            if not target:
                raise ValueError
            ipaddress.ip_address(target)
            uses_ip = True
        except ValueError:
            uses_ip = False
        if self.entra_sso.isChecked() and uses_ip:
            description += " Webkonto/Entra wird dabei automatisch deaktiviert, da Windows es mit IP-Zielen nicht unterstützt."
        self.target_note.setText(description)

    @staticmethod
    def _optional(edit: QLineEdit) -> str | None:
        value = edit.text().strip()
        return value or None

    def _validate_network(self) -> bool:
        fields = (
            ("IP-Adresse", self.ip_address),
            ("Subnetzmaske", self.subnet_mask),
            ("Standardgateway", self.default_gateway),
            ("DNS-Server", self.dns_server),
        )
        for label, edit in fields:
            value = edit.text().strip()
            if not value:
                continue
            try:
                ipaddress.ip_address(value)
            except ValueError:
                QMessageBox.warning(self, "Ungültige Netzwerkangabe", f"{label} ist keine gültige IP-Adresse.")
                edit.setFocus()
                return False
        return True

    def _accept(self) -> None:
        if not self.display_name.text().strip():
            QMessageBox.warning(self, "Pflichtfeld", "Der Anzeigename muss ausgefüllt sein.")
            return
        if not self._validate_network():
            return
        mode = ConnectionTargetMode(self.connection_target.currentData())
        targets = {
            ConnectionTargetMode.IP_ADDRESS: self.ip_address.text().strip(),
            ConnectionTargetMode.HOSTNAME: self.hostname.text().strip(),
            ConnectionTargetMode.FQDN: self.fqdn.text().strip(),
        }
        if not any(targets.values()):
            QMessageBox.warning(
                self,
                "Verbindungsziel fehlt",
                "Bitte mindestens eine IP-Adresse, einen Hostnamen oder einen FQDN eintragen.",
            )
            return
        if mode != ConnectionTargetMode.AUTO and not targets[mode]:
            labels = {
                ConnectionTargetMode.IP_ADDRESS: "IP-Adresse",
                ConnectionTargetMode.HOSTNAME: "Hostname",
                ConnectionTargetMode.FQDN: "FQDN",
            }
            QMessageBox.warning(
                self,
                "Verbindungsziel fehlt",
                f"Für das gewählte Verbindungsziel muss das Feld „{labels[mode]}“ ausgefüllt sein.",
            )
            return
        try:
            if targets[ConnectionTargetMode.HOSTNAME]:
                RDPProfileValidator.validate_hostname(targets[ConnectionTargetMode.HOSTNAME])
            if targets[ConnectionTargetMode.FQDN]:
                RDPProfileValidator.validate_hostname(targets[ConnectionTargetMode.FQDN])
            if self.gateway_hostname.text().strip():
                RDPProfileValidator.validate_gateway(self.gateway_hostname.text().strip())
        except RDPValidationError as exc:
            QMessageBox.warning(self, "Ungültiges Verbindungsziel", str(exc))
            return
        values = {
            "workstation_id": self.workstation_id.text().strip() or self.suggested_id,
            "display_name": self.display_name.text().strip(),
            "hostname": self.hostname.text().strip(),
            "fqdn": self._optional(self.fqdn),
            "ip_address": self._optional(self.ip_address),
            "subnet_mask": self._optional(self.subnet_mask),
            "default_gateway": self._optional(self.default_gateway),
            "dns_server": self._optional(self.dns_server),
            "connection_target_mode": mode,
            "site": self._optional(self.site),
            "description": self._optional(self.description),
            "enabled": self.enabled.isChecked(),
            "username_hint": self._optional(self.username_hint),
            "gateway_hostname": self._optional(self.gateway_hostname),
            "entra_sso_enabled": self.entra_sso.isChecked(),
            "trust_unverified_server": self.trust_unverified_server.isChecked(),
            "screen_mode": self.screen_mode.currentData(),
            "resolution": self.resolution.currentText().strip() or None,
            "use_all_monitors": self.use_all_monitors.isChecked(),
            "redirect_clipboard": self.redirect_clipboard.isChecked(),
            "redirect_drives": self.redirect_drives.isChecked(),
            "redirect_printers": self.redirect_printers.isChecked(),
            "redirect_audio": self.redirect_audio.isChecked(),
        }
        self.workstation = replace(self.original, **values) if self.original else Workstation(**values)
        self.accept()


__all__ = ["WorkstationDialog"]
