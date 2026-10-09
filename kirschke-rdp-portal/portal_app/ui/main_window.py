"""Main window for the locally testable Kirschke RDP portal."""

from __future__ import annotations

import logging
import sys
import uuid
from copy import copy, deepcopy
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.reservation import Reservation
from portal_app.models.session import SessionEvent
from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.active_directory_sync import (
    check_active_directory_readiness,
    sync_rdp_group_members,
)
from portal_app.services.admin_security import (
    AdminLockoutError,
    GlobalAdminPasswordVerifier,
    directory_mode,
)
from portal_app.services.agent_identity import machine_hostnames
from portal_app.services.agent_status import LocalAgentStatusService
from portal_app.services.directory_users import discover_windows_domain_accounts
from portal_app.services.fallback_scanning import FallbackScanner, ShareReconnector
from portal_app.services.live_status_polling import AutomaticLiveStatusPoller
from portal_app.services.local_identity import detect_initial_user
from portal_app.services.local_store import (
    LocalStore,
    StoreConflictError,
    StoreReadError,
    file_signatures,
)
from portal_app.services.reservation_access import apply_reservations
from portal_app.services.session_claims import BackgroundSessionClaimReporter
from portal_app.services.start_inventory import load_start_inventory
from portal_app.services.store_watch import StoreChangeProbe
from portal_app.services.windows_admin_auth import (
    check_windows_admin_authorization,
    test_password_fallback_allowed,
)
from portal_app.ui.design import Typography, apply_scaled_geometry, scale_stylesheet, scaled
from portal_app.ui.icons import kirschke_window_icon
from portal_app.ui.widgets.machine_registration_wizard import (
    AgentAssignment,
    MachineRegistrationWizard,
)
from portal_app.ui.widgets.management_pages import AdministrationWidget, SettingsWidget
from portal_app.ui.widgets.rdp_access_dialog import RDPAccessDialog
from portal_app.ui.widgets.reservation_calendar import ReservationCalendarWidget
from portal_app.ui.widgets.session_log import SessionLogWidget
from portal_app.ui.widgets.user_settings_dialog import UserSettingsDialog
from portal_app.ui.widgets.workstation_cards import WorkstationCardsWidget
from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget
from portal_app.ui.widgets.workstation_dialog import WorkstationDialog
from portal_app.version import PORTAL_VERSION
from shared.enums import EventResult, EventSource, EventType, ManualFlagType
from shared.name_resolution import prefetch as prefetch_names
from shared.name_resolution import unc_server_name
from shared.schemas import RDPProfileSchema
from shared.session_identity import is_active_session, is_console_session, session_username

logger = logging.getLogger(__name__)


def rdp_profile(workstation: Workstation, user: MockUser) -> RDPProfileSchema:
    """Das RDP-Profil für diesen Portal-Benutzer.

    Ist der Benutzer selbst mit einem Entra-Konto angemeldet, gilt eine bloße
    E-Mail-Adresse als Entra-Konto und bekommt die Schreibweise, die das Ziel
    ohne Webanmeldung braucht -- siehe ``Workstation.rdp_account``.
    """
    return workstation.get_rdp_profile(
        user.get_rdp_username(), entra_user=user.windows_account().is_entra
    )


def rdp_launch_profile(workstation: Workstation, user: MockUser) -> RDPProfileSchema:
    """Wie ``rdp_profile``, aber mit dem Ziel, das die Karte anzeigt.

    Siehe ``Workstation.get_launch_profile``.
    """
    return workstation.get_launch_profile(
        user.get_rdp_username(), entra_user=user.windows_account().is_entra
    )


def _saved_credentials_allow_launch(
    parent: QWidget, profile: RDPProfileSchema, target: str
) -> bool:
    """Gespeicherte Windows-Anmeldedaten für ein anderes Konto vorher klären.

    Hat Windows für das Ziel Anmeldedaten gespeichert, meldet mstsc mit ihnen
    an und übergeht das Konto aus der .rdp-Datei. Die Auswahl unter "Anmelden
    als" lief damit ins Leere, ohne dass irgendwo stand, warum. Entfernt wird
    der Eintrag nur auf ausdrückliche Bestätigung; das Kennwort sieht das
    Portal dabei nie.

    Gibt zurück, ob gestartet werden soll.
    """
    from portal_app.services import rdp_diagnostics
    from shared.identity import same_account_name

    chosen = profile.effective_rdp_username()
    if not _server_credentials_allow_launch(parent, chosen, target):
        return False
    if not chosen:
        return True
    saved = rdp_diagnostics.saved_rdp_credential_user(target)
    if not saved or same_account_name(saved, chosen):
        return True
    question = QMessageBox(parent)
    question.setIcon(QMessageBox.Warning)
    question.setWindowTitle("Gespeicherte Anmeldung für ein anderes Konto")
    question.setText(
        f"Windows hat für {target} Anmeldedaten von „{saved}“ gespeichert. "
        f"Damit meldet Remotedesktop dich als „{saved}“ an und nicht als das "
        f"gewählte Konto „{chosen}“."
    )
    question.setInformativeText(
        "Wird der gespeicherte Eintrag entfernt, fragt Windows beim Start das "
        f"Kennwort für „{chosen}“ ab."
    )
    remove = question.addButton("Eintrag entfernen und verbinden", QMessageBox.AcceptRole)
    keep = question.addButton("Gespeichertes Konto nutzen", QMessageBox.DestructiveRole)
    question.addButton(QMessageBox.Cancel)
    question.setDefaultButton(remove)
    question.exec()
    clicked = question.clickedButton()
    if clicked is keep:
        return True
    if clicked is not remove:
        return False
    success, detail = rdp_diagnostics.clear_saved_rdp_credentials(target)
    if not success:
        QMessageBox.warning(parent, "Eintrag nicht entfernt", detail)
        return False
    logger.info("Gespeicherte RDP-Anmeldedaten für %s entfernt", target)
    return True


def _server_credentials_allow_launch(parent: QWidget, chosen: str | None, target: str) -> bool:
    r"""Einen Windows-Eintrag für den ganzen Server vor dem Start klären.

    So ein Eintrag (``Domain:target=<Ziel>``) entsteht beim Speichern der
    Zugangsdaten einer Dateifreigabe, und mstsc nimmt ihn genauso wie einen
    RDP-Eintrag. Lautet er auf das Lesekonto ``PortalLeser``, scheitert jede
    Verbindung mit "nicht zur Remoteanmeldung autorisiert": Das Agent-Setup
    verbietet diesem Konto die Remoteanmeldung. Dann gibt es nichts zu
    behalten, nur zu entfernen -- die Freigaben verbindet das Portal mit
    seinem eigenen Eintrag.
    """
    from portal_app.services import rdp_diagnostics
    from portal_app.services.reader_account import DEFAULT_READER_ACCOUNT
    from shared.identity import same_account_name

    saved = rdp_diagnostics.saved_server_credential_user(target)
    if not saved:
        return True
    reader = saved.rsplit("\\", 1)[-1].casefold() == DEFAULT_READER_ACCOUNT.casefold()
    if not reader and (not chosen or same_account_name(saved, chosen)):
        return True
    question = QMessageBox(parent)
    question.setIcon(QMessageBox.Warning)
    question.setWindowTitle("Gespeicherte Anmeldung für den ganzen Server")
    if reader:
        question.setText(
            f"Windows hat für {target} das Lesekonto „{saved}“ gespeichert, "
            "vermutlich beim Verbinden einer Statusfreigabe. Remotedesktop meldet "
            "sich damit an statt mit dem gewählten Konto – und dieses Konto darf "
            "sich nie per Remotedesktop anmelden."
        )
        question.setInformativeText(
            "Wird der Eintrag entfernt, fragt Windows beim Start nach dem Kennwort "
            "des gewählten Kontos. Die Freigaben verbindet das Portal weiterhin "
            "selbst."
        )
    else:
        question.setText(
            f"Windows hat für {target} Anmeldedaten von „{saved}“ gespeichert. "
            f"Damit meldet Remotedesktop dich als „{saved}“ an und nicht als das "
            f"gewählte Konto „{chosen}“."
        )
        question.setInformativeText(
            "Der Eintrag gilt für den ganzen Rechner, also auch für Dateifreigaben "
            "dort. Wird er entfernt, fragt Windows beim Start das Kennwort für "
            f"„{chosen}“ ab."
        )
    remove = question.addButton("Eintrag entfernen und verbinden", QMessageBox.AcceptRole)
    keep = None if reader else question.addButton("Gespeichertes Konto nutzen", QMessageBox.DestructiveRole)
    question.addButton(QMessageBox.Cancel)
    question.setDefaultButton(remove)
    question.exec()
    clicked = question.clickedButton()
    if keep is not None and clicked is keep:
        return True
    if clicked is not remove:
        return False
    success, detail = rdp_diagnostics.clear_saved_server_credentials(target)
    if not success:
        QMessageBox.warning(parent, "Eintrag nicht entfernt", detail)
        return False
    logger.info("Gespeicherte Server-Anmeldedaten für %s entfernt", target)
    return True


class MainWindow(QMainWindow):
    """Card dashboard, editing forms and calendar backed by local test data."""

    workstation_selected = Signal(Workstation)
    refresh_requested = Signal()

    #: Server, deren alter Anmeldeeintrag beim Start entfernt wurde. Siehe
    #: _prepare_shared_folders.
    _retired_credential_servers: tuple[str, ...] = ()

    PAGE_MACHINES = 0
    PAGE_CALENDAR = 1
    PAGE_LOGS = 2
    PAGE_ADMIN = 3
    PAGE_SETTINGS = 4
    PAGE_DETAIL = 5

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        automatic_live_status: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Kirschke · RDP Portal {PORTAL_VERSION}")
        self._automatic_live_status_enabled = automatic_live_status
        self.logo_path = Path(__file__).resolve().parent / "assets" / "kirschke_logo.png"
        self.setWindowIcon(kirschke_window_icon())
        self._apply_initial_geometry()

        self.store = LocalStore()
        self.directory_mode = directory_mode()
        self.admin_password_verifier = GlobalAdminPasswordVerifier()
        self.agent_status_service = LocalAgentStatusService(
            directory=self.store.agent_status_directory
        )
        self.live_status_poller = AutomaticLiveStatusPoller(max_parallel=4, parent=self)
        # Maschinen, gegen die gerade eine Abmeldung laeuft. Siehe
        # _run_status_update_cycle: waehrend der Abmeldung ist der Agent
        # nicht abfragbar, und das darf nicht als Ausfall erscheinen.
        self._logoff_in_progress: set[str] = set()
        # Meldet dem Agenten jede vom Portal gestartete Verbindung und haelt
        # nach, was noch nicht angekommen ist. Wiederholt wird, weil das
        # Ausbleiben einer Meldung selbst eine Auskunft ist -- siehe
        # portal_app.services.session_claims. Die Pipe-Aufrufe laufen im
        # Hintergrund, weil eine abgeschaltete Maschine sonst bei jedem
        # Statuslauf das Fenster sekundenlang anhielt.
        self._claim_reporter = BackgroundSessionClaimReporter(parent=self)
        # Maschine und Konto, fuer die diese Sitzung bereits eine Aufschaltung
        # gemeldet hat. Siehe _learn_reported_account: Ohne das ginge bei jedem
        # Statuslauf erneut eine Pipe-Anfrage an dieselbe Maschine.
        self._reported_claims: set[tuple[str, str]] = set()
        self.fallback_scanner = FallbackScanner(parent=self)
        self.fallback_scanner.completed.connect(self._on_fallback_scan_completed)
        # Letztes Ergebnis des Ordner-Scans. Eine Live-Antwort wendet es mit dem
        # neuen Live-Stand erneut an, statt die Ordner noch einmal zu lesen --
        # vorher lief dafuer pro Maschine und Statuslauf ein blockierender
        # SMB-Scan im UI-Thread.
        self._last_fallback_scans: object | None = None
        # Buendelt die Live-Antworten eines Statuslaufs zu einer Aktualisierung.
        self._live_apply_timer = QTimer(self)
        self._live_apply_timer.setSingleShot(True)
        self._live_apply_timer.setInterval(150)
        self._live_apply_timer.timeout.connect(self._apply_live_results)
        self.share_reconnector = ShareReconnector(parent=self)
        # Prueft das gemeinsame Inventar auf Aenderungen, ohne dass ein
        # haengender SMB-Server den UI-Thread anhaelt.
        self.store_probe = StoreChangeProbe(parent=self)
        self.store_probe.completed.connect(self._on_store_probe)
        self.share_reconnector.completed.connect(self._on_shares_reconnected)
        # Agent IDs a sweep has seen, so the settings table can offer an agent
        # before any machine claims it.
        self._discovered_agent_ids: list[str] = []
        self.workstations: list[Workstation] = []
        self.reservations: list[Reservation] = []
        self.session_events: list[SessionEvent] = []
        self.current_user = detect_initial_user(MockUser.create_user())
        self.nav_buttons: list[QPushButton] = []
        self._admin_unlocked = False
        self._pending_save = False
        # Set by a non-blocking poll whose reservation change still needs a view
        # refresh once the background folder scan delivers.
        self._reservation_change_pending = False
        # Gesetzt, wenn der eingestellte Speicherort nicht nutzbar war. Wird
        # gezeigt, sobald ein Fenster da ist, an dem ein Dialog haengen kann.
        self._storage_fallback_notice = ""
        self._load_data()
        # Alle Namen gleichzeitig nachschlagen, bevor der erste Statuslauf sie
        # einzeln abfragt. Nacheinander kostete jeder nicht aufloesbare Name
        # den Start bis zu zwei Sekunden.
        prefetch_names(
            name for item in self.workstations for name in item.names_to_resolve()
        )
        self._create_ui()
        self._update_storage_status("Gemeinsamer Speicher bereit")
        self._connect_signals()
        self._apply_theme()
        # A crash or "End task" skips the cleanup in closeEvent, and the leftover
        # .rdp files name the target machine and the user.
        self._cleanup_stale_rdp_files()
        if self._storage_fallback_notice:
            QTimer.singleShot(0, self._show_storage_fallback_notice)
        self.rdp_poll_timer = QTimer(self)
        self.rdp_poll_timer.setInterval(1500)
        self.rdp_poll_timer.timeout.connect(self._poll_rdp_sessions)
        self.rdp_poll_timer.start()
        self._poll_rdp_sessions()
        self.agent_poll_timer = QTimer(self)
        self.agent_poll_timer.setInterval(self.store.status_refresh_interval * 1000)
        self.agent_poll_timer.timeout.connect(self._scheduled_status_update)
        self.agent_poll_timer.start()
        self._poll_agent_status()
        if self._automatic_live_status_enabled:
            QTimer.singleShot(0, lambda: self._run_status_update_cycle(force=True))
        self.shared_store_sync_timer = QTimer(self)
        self.shared_store_sync_timer.setInterval(5000)
        self.shared_store_sync_timer.timeout.connect(
            lambda: self._sync_shared_store(blocking=False)
        )
        self.shared_store_sync_timer.start()
        if self._automatic_live_status_enabled:
            # Both of these reach the network on their own, which is exactly what
            # ``automatic_live_status=False`` exists to switch off -- a test must
            # not sweep a subnet or open a modal assistant.
            #
            # Rebuild the SMB sessions the configured fallbacks need. Without
            # this the paths and the saved Windows credentials both survived a
            # restart while the connection did not, so the file fallback -- and
            # the live channel, whose pipe target is derived from the same
            # server -- stayed dead until somebody re-ran the setup dialog.
            QTimer.singleShot(0, self._reconnect_status_shares)
            if not self.workstations:
                # An empty inventory is the first start. Adding machines is
                # otherwise an admin action, but here it is the only way past an
                # empty window, so the assistant opens without the password gate.
                QTimer.singleShot(150, lambda: self._run_connection_wizard(first_run=True))

    def _apply_initial_geometry(self) -> None:
        """Startgröße aus dem tatsächlich verfügbaren Bildschirm ableiten.

        Vorher standen hier feste 1360 x 860 mit einem Minimum von 1080 x 720.
        Beides ist in logischen Pixeln gerechnet, und genau die werden knapp,
        sobald jemand die Windows-Anzeige auf 150 % stellt: Aus einem
        1920 x 1080-Schirm werden 1280 x 720 logische Pixel, das Minimum passte
        nicht mehr hinein, und das Fenster ließ sich nicht klein genug ziehen,
        um noch an die Taskleiste zu kommen.

        Das Minimum bleibt eine Aussage darüber, ab wann die Oberfläche
        unbrauchbar wird -- es wird aber nie größer gesetzt, als der Bildschirm
        hergibt.
        """
        apply_scaled_geometry(self, (1080, 720), (1360, 860))

    def _prepare_shared_folders(self) -> None:
        """Inventar- und Protokollfreigabe verbinden, bevor das Portal sie liest.

        Bis 0.9.3 hat das Windows still erledigt -- mit dem Server-Eintrag, den
        der Freigabedialog anlegte. Derselbe Eintrag hat aber Remotedesktop auf
        das Lesekonto umgelenkt; siehe ``credential_payload``. Ohne ihn muss das
        Portal die Verbindung selbst aufbauen, und zwar vor dem ersten Lesen:
        Sonst landete es beim Start im Notbetrieb mit der lokalen Kopie.
        """
        from portal_app.services.share_connection import (
            connect_status_share,
            retire_legacy_server_credentials,
        )

        try:
            retired = retire_legacy_server_credentials()
        except Exception as exc:  # noqa: BLE001 - Aufraeumen darf den Start nie verhindern
            # Genau das ist in 0.9.4 passiert: Ein fehlendes Modul in der
            # gebauten EXE beendete das Portal vor dem ersten Fenster.
            logger.warning("Alte Server-Anmeldedaten nicht geprüft: %s", exc)
            retired = []
        if retired:
            logger.info(
                "Alte Server-Anmeldedaten des Lesekontos entfernt: %s", ", ".join(retired)
            )
        # Auch der Live-Kanal ritt auf diesem Eintrag mit: Die Pipe meldet sich
        # mit der SMB-Sitzung an, die zum Server schon besteht. Deshalb wird die
        # Statusfreigabe dieser Server beim Start mit verbunden.
        self._retired_credential_servers = tuple(retired)
        try:
            folders = (self.store.inventory_directory, self.store.event_log_directory)
        except (OSError, ValueError) as exc:
            logger.warning("Speichereinstellung nicht lesbar: %s", exc)
            return
        for folder in folders:
            if folder is not None and str(folder).startswith("\\\\"):
                try:
                    _, message = connect_status_share(str(folder))
                except Exception as exc:  # noqa: BLE001 - dann gilt der Notbetrieb, kein Absturz
                    message = f"nicht verbunden ({type(exc).__name__}: {exc})"
                logger.info("Freigabe %s: %s", folder, message)

    def _load_data(self) -> None:
        # Ohne eigenen Stand beginnt ein Portal mit dem mitgelieferten
        # Startinventar: echte Maschinen statt eines leeren Fensters, und nie
        # erfundene Ziele. Ein vorhandener Stand geht immer vor.
        fallback: list[Workstation] = load_start_inventory()
        if self._automatic_live_status_enabled:
            self._prepare_shared_folders()
        try:
            loaded = self.store.load(fallback, self.current_user)
        except StoreReadError as exc:
            if self.store.inventory_directory is None:
                raise
            loaded = self._load_without_shared_inventory(exc, fallback)
        self.workstations, self.current_user, self.reservations = loaded
        if self.store.configuration_notice:
            self._storage_fallback_notice = "\n\n".join(
                part for part in (self._storage_fallback_notice, self.store.configuration_notice)
                if part
            )
        self._apply_local_agent_fallbacks()
        self.session_events = self.store.load_events()
        self.directory_accounts = self.store.load_directory_accounts()
        self.theme_mode = self.store.theme_mode
        self.dark_mode = self._resolve_dark_mode()
        self._saved_workstations = deepcopy(self.workstations)
        self._saved_user = deepcopy(self.current_user)
        if not self.store.path.exists():
            self._save_initial_state()
        try:
            self.store.initialize_event_log()
        except OSError as exc:
            # Das Ereignisprotokoll legt seinen Ordner selbst an und war damit der
            # zweite Weg, auf dem ein unerreichbarer Speicherort das Portal noch
            # vor dem ersten Fenster beendet hat. Ohne Protokoll laesst sich
            # arbeiten; ohne Portal nicht.
            logger.warning("Ereignisprotokoll nicht nutzbar: %s", exc)

    def _load_without_shared_inventory(
        self, exc: Exception, fallback: list[Workstation]
    ) -> tuple[list[Workstation], MockUser, list[Reservation]]:
        """Starten, obwohl die Freigabe des gemeinsamen Inventars nicht geht.

        Das Portal legt dort nichts an und schreibt dort nichts hin: Ein leeres
        oder veraltetes Inventar auf der Freigabe liesse bei allen anderen die
        Maschinen verschwinden. Gearbeitet wird lokal mit dem zuletzt gelesenen
        Stand, und das wird gesagt.
        """
        logger.warning("Gemeinsames Inventar nicht nutzbar: %s", exc)
        local = self.store.use_local_fallback()
        self._storage_fallback_notice = (
            f"{exc}\n\nDas Portal arbeitet vorerst lokal unter:\n{local}\n"
            "mit dem zuletzt gelesenen Stand des gemeinsamen Inventars.\n\n"
            "Änderungen an Maschinen und Reservierungen werden dabei NICHT mit den "
            "anderen Portalen geteilt und beim nächsten Start mit erreichbarer "
            "Freigabe nicht übernommen. Die Freigabe selbst bleibt unverändert."
        )
        return self.store.load(fallback, self.current_user)

    def _save_initial_state(self) -> None:
        """Write the first state file, and survive a storage location that is gone.

        Falling back to a local folder keeps the portal usable. It also stops the
        state from being shared, so the reason is reported rather than left for
        somebody to notice when a colleague's machines fail to show up.
        """
        try:
            self.store.save(
                self._saved_workstations, self._saved_user, self.reservations, self.store.theme_mode
            )
            return
        except OSError as exc:
            intended = self.store.directory
            logger.warning("Speicherort %s nicht nutzbar: %s", intended, exc)
        try:
            local = self.store.use_local_fallback()
            self.store.save(
                self._saved_workstations, self._saved_user, self.reservations, self.store.theme_mode
            )
        except OSError as exc:
            self._storage_fallback_notice = (
                "Das Portal konnte keinen Speicherort anlegen. Es startet, merkt "
                f"sich aber nichts.\n\nZuletzt versucht: {self.store.directory}\n{exc}"
            )
            return
        self._storage_fallback_notice = (
            f"Der eingestellte Speicherort ist auf diesem PC nicht erreichbar:\n{intended}\n\n"
            f"Das Portal arbeitet vorerst lokal unter:\n{local}\n\n"
            "Maschinen und Reservierungen werden dabei NICHT mit den anderen "
            "Portalen geteilt. Den Speicherort wieder verfügbar machen und das "
            "Portal neu starten."
        )

    def _show_storage_fallback_notice(self) -> None:
        """Say once that the portal is not writing where it was configured to."""
        notice, self._storage_fallback_notice = self._storage_fallback_notice, ""
        if notice:
            QMessageBox.warning(self, "Speicherort nicht erreichbar", notice)

    def _apply_local_agent_fallbacks(self) -> None:
        """Attach client-local fallback paths to freshly loaded shared machines."""
        for workstation in self.workstations:
            directory, explicit = self.store.get_workstation_agent_status_directory(
                workstation.workstation_id
            )
            workstation.agent_fallback_directory = str(directory)
            workstation.agent_fallback_is_explicit = explicit

    def _create_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("appBackground")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(34, 26, 34, 26)
        outer.setSpacing(0)
        shell = QFrame()
        shell.setObjectName("appShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self._create_header())
        shell_layout.addWidget(self._create_navigation())
        shell_layout.addWidget(self._create_content(), 1)
        outer.addWidget(shell)

    def _create_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(36, 22, 36, 18)
        layout.setSpacing(14)
        self.logo_label = QLabel()
        self.logo_label.setObjectName("brandLogo")
        self.logo_label.setFixedSize(scaled(285), scaled(48))
        layout.addWidget(self.logo_label)
        self._update_logo()
        product = QLabel(f"RDP PORTAL · TEST {PORTAL_VERSION}")
        product.setObjectName("productName")
        layout.addWidget(product)
        layout.addStretch()
        self.user_button = QPushButton()
        self.user_button.setObjectName("userButton")
        self.user_button.setCursor(Qt.PointingHandCursor)
        self.user_button.clicked.connect(self._edit_user)
        layout.addWidget(self.user_button)
        self.avatar_button = QPushButton()
        self.avatar_button.setObjectName("avatarButton")
        self.avatar_button.setFixedSize(scaled(42), scaled(42))
        self.avatar_button.setCursor(Qt.PointingHandCursor)
        self.avatar_button.clicked.connect(self._edit_user)
        layout.addWidget(self.avatar_button)
        self._update_user_header()
        return header

    def _create_navigation(self) -> QWidget:
        navigation = QWidget()
        navigation.setObjectName("navigation")
        layout = QHBoxLayout(navigation)
        layout.setContentsMargins(28, 0, 28, 0)
        layout.setSpacing(4)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        labels = ("Maschinen", "Kalender", "Logs", "Admin", "Einstellungen")
        for index, label in enumerate(labels):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setProperty("pageIndex", index)
            button.setChecked(index == self.PAGE_MACHINES)
            self.nav_group.addButton(button)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch()
        return navigation

    def _create_content(self) -> QWidget:
        content = QWidget()
        content.setObjectName("content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 8, 30, 18)
        layout.setSpacing(8)
        self.page_eyebrow = QLabel("ARBEITSPLATZÜBERSICHT")
        self.page_eyebrow.setObjectName("eyebrow")
        self.page_eyebrow.hide()
        layout.addWidget(self.page_eyebrow)
        title_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        self.page_title = QLabel("Maschinen")
        self.page_title.setObjectName("pageTitle")
        self.page_title.setFont(Typography.heading_1())
        title_box.addWidget(self.page_title)
        self.page_subtitle = QLabel("Verfügbare Arbeitsplätze und aktive Sitzungen auf einen Blick.")
        self.page_subtitle.setObjectName("pageSubtitle")
        self.page_subtitle.hide()
        title_box.addWidget(self.page_subtitle)
        title_row.addLayout(title_box)
        title_row.addStretch()
        self.summary = QLabel()
        self.summary.setObjectName("summaryBadge")
        self._update_summary()
        title_row.addWidget(self.summary, alignment=Qt.AlignVCenter)
        self.overview_refresh_button = QPushButton("Aktualisieren")
        self.overview_refresh_button.setObjectName("toolbarButton")
        self.overview_refresh_button.clicked.connect(self.on_refresh)
        title_row.addWidget(self.overview_refresh_button, alignment=Qt.AlignVCenter)
        layout.addLayout(title_row)

        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        self.overview_view = WorkstationCardsWidget(self.workstations, self.current_user, self)
        self.stack.addWidget(self.overview_view)
        self.calendar_view = ReservationCalendarWidget(
            self.workstations, list(self.reservations), self.current_user, self
        )
        # _apply_theme lief schon, bevor es diesen Kalender gab -- ohne diese
        # Zeile startet er im dunklen Thema mit hellen Zellen.
        self.calendar_view.set_dark_mode(self.dark_mode)
        self.stack.addWidget(self.calendar_view)
        self.session_log_view = SessionLogWidget([], self.current_user, self)
        self.session_log_view.set_events(self.session_events)
        self.stack.addWidget(self.session_log_view)
        self.admin_view = AdministrationWidget(self.workstations, self)
        self.admin_view.set_storage_directory(
            str(self.store.directory), self.store.uses_shared_inventory
        )
        self.admin_view.set_directory_mode(self.directory_mode)
        self.stack.addWidget(self.admin_view)
        self.settings_view = SettingsWidget(
            self.current_user,
            theme_mode=self.theme_mode,
            dark_mode=self.dark_mode,
            status_refresh_interval=self.store.status_refresh_interval,
            parent=self,
        )
        self.stack.addWidget(self.settings_view)
        self.detail_view = WorkstationDetailWidget(self.current_user, self)
        self.stack.addWidget(self.detail_view)
        layout.addWidget(self.stack, 1)
        return content

    def _connect_signals(self) -> None:
        self.nav_group.buttonClicked.connect(self._on_navigation_clicked)
        self.overview_view.workstation_selected.connect(self.on_workstation_selected)
        self.overview_view.connect_requested.connect(self.on_connect_requested)
        self.overview_view.logoff_requested.connect(self._logoff_session)
        self.overview_view.account_selected.connect(self._select_login_account)
        self.overview_view.account_add_requested.connect(self._add_login_account)
        self.overview_view.display_settings_changed.connect(self._set_display_settings)
        self.overview_view.order_changed.connect(self._save_machine_order)
        self.overview_view.favorite_toggled.connect(self._set_machine_favorite)
        self.overview_view.preferred_toggled.connect(self._set_preferred_login_account)
        self.overview_view.view_changed.connect(self._set_machine_view)
        self.overview_view.set_machine_order(self.store.machine_order)
        self.overview_view.set_favorites(self.store.favorite_workstations)
        self.overview_view.set_preferred_accounts(self.store.preferred_login_accounts)
        self.overview_view.set_machine_view(self.store.machine_view)
        self.admin_view.event_log_directory_requested.connect(self._setup_event_log_directory)
        self.admin_view.event_log_directory_cleared.connect(self._clear_event_log_directory)
        self.admin_view.inventory_directory_requested.connect(self._setup_inventory_directory)
        self.admin_view.inventory_directory_cleared.connect(self._clear_inventory_directory)
        self._refresh_event_log_location()
        self.admin_view.add_requested.connect(self._add_workstation)
        self.admin_view.edit_requested.connect(self._edit_workstation)
        self.admin_view.force_disconnect_requested.connect(self._force_disconnect_workstation)
        self.admin_view.force_logoff_requested.connect(self._admin_logoff_workstation)
        self.admin_view.delete_requested.connect(self._delete_workstation)
        self.admin_view.rdp_access_requested.connect(self._manage_rdp_access)
        self.admin_view.lock_requested.connect(self._lock_admin)
        self.admin_view.save_requested.connect(self._save_admin_settings)
        self.admin_view.active_directory_status_requested.connect(self._update_active_directory_status)
        self.settings_view.edit_user_requested.connect(self._edit_user)
        self.settings_view.agent_refresh_requested.connect(
            lambda: self._run_status_update_cycle(force=True)
        )
        self.settings_view.theme_changed.connect(self._set_theme_mode)
        self.settings_view.status_refresh_interval_changed.connect(
            self._set_status_refresh_interval
        )
        agent_panel = self.settings_view.agent_connection
        agent_panel.wizard_requested.connect(lambda: self._run_connection_wizard())
        agent_panel.reconnect_requested.connect(self._reconnect_status_shares)
        agent_panel.credentials_save_requested.connect(self._save_reader_credentials)
        agent_panel.agent_assignment_changed.connect(self._set_agent_assignment)
        agent_panel.fallback_setup_requested.connect(self._setup_fallback_by_id)
        self._show_reader_account()
        self._refresh_agent_panel()
        self.calendar_view.reservations_changed.connect(self._on_reservations_changed)
        self.detail_view.back_requested.connect(self._show_machines)
        self.detail_view.edit_requested.connect(self._edit_workstation)
        self.detail_view.connect_requested.connect(self.on_connect_requested)
        self.detail_view.logoff_requested.connect(self._logoff_session)
        self.detail_view.live_status_requested.connect(self._query_live_status)
        self.detail_view.account_selected.connect(self._select_login_account)
        self.detail_view.account_add_requested.connect(self._add_login_account)
        self.detail_view.account_selector.preferred_toggled.connect(
            self._set_preferred_login_account
        )
        self.detail_view.account_claim_requested.connect(self._claim_reported_account)
        self.detail_view.diagnostics_requested.connect(self._run_rdp_diagnostics)
        self.detail_view.agent_assignment_requested.connect(self._assign_agent)
        self.detail_view.fallback_setup_requested.connect(self._setup_workstation_fallback)
        self.detail_view.workstation_updated.connect(self._on_workstation_updated)
        self.workstation_selected.connect(self.detail_view.set_workstation)
        self.live_status_poller.succeeded.connect(self._on_live_status_succeeded)
        self.live_status_poller.failed.connect(self._on_live_status_failed)

    @Slot(Workstation, str)
    def _claim_reported_account(self, workstation: Workstation, account: str) -> None:
        r"""Record the account a foreign session runs under as the user's own.

        For an Entra account the agent reports the profile name
        ("AzureAD\HendrikSchaelikeAdmin") while the portal knows the UPN
        ("schaelike-adm@..."). Neither can be derived from the other, so the
        portal has to be told once -- and the only party who knows is the
        person looking at the card.

        This grants nothing: Windows still asks for that account's password,
        and the agent authorizes a logoff on its own.
        """
        if not account.strip():
            return
        answer = QMessageBox.question(
            self,
            "Konto als eigenes eintragen",
            f"Gehört dir das Windows-Konto „{account}“ selbst?\n\n"
            "Es wird unter Einstellungen → Weitere eigene Windows-Konten "
            "gespeichert. Sitzungen dieses Kontos gelten danach als deine. "
            "Berechtigungen vergibt das nicht — Windows fragt weiterhin nach "
            "dem Kennwort.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        if not self.current_user.claim_account(account):
            QMessageBox.information(
                self,
                "Bereits eingetragen",
                f"„{account}“ ist bereits als eigenes Konto hinterlegt.",
            )
            return
        self._saved_user = deepcopy(self.current_user)
        if not self._persist():
            return
        self._refresh_workstation_views()
        self._run_status_update_cycle([workstation], force=True)

    @Slot(Workstation, object, bool)
    def _set_display_settings(
        self,
        workstation: Workstation,
        resolution: object,
        use_all_monitors: bool,
    ) -> None:
        """Store the quick choice from a machine card.

        "Vollbild" is the absence of a resolution rather than a size of its
        own: mstsc then uses whatever the screen is. Writing one anyway would
        pin the session to today's monitor.
        """
        value = str(resolution).strip() if resolution else None
        workstation.screen_mode = "windowed" if value else "fullscreen"
        workstation.resolution = value
        workstation.use_all_monitors = bool(use_all_monitors)
        self._commit_workstation(workstation)
        self._persist()

    @Slot(Workstation, str)
    def _select_login_account(self, workstation: Workstation, account: str) -> None:
        if account and account not in workstation.login_accounts + workstation.session_accounts():
            return
        try:
            self.store.save_login_selection(workstation.workstation_id, account, self._saved_user)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Anmeldekonto nicht gespeichert", str(exc))
        else:
            workstation.selected_login_account = account or None
        self._refresh_login_views(workstation)

    @Slot(Workstation, bool)
    def _set_machine_favorite(self, workstation: Workstation, favorite: bool) -> None:
        try:
            self.store.save_favorite(workstation.workstation_id, favorite, self._saved_user)
        except OSError as exc:
            QMessageBox.warning(self, "Favorit nicht gespeichert", str(exc))
        self.overview_view.set_favorites(self.store.favorite_workstations)

    @Slot(Workstation, object)
    def _set_preferred_login_account(
        self, workstation: Workstation, account: object
    ) -> None:
        value = account if isinstance(account, str) else None
        if value and value not in workstation.login_accounts + workstation.session_accounts():
            return
        try:
            self.store.save_preferred_login_account(
                workstation.workstation_id, value, self._saved_user
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Bevorzugtes Konto nicht gespeichert", str(exc))
            return
        self.overview_view.set_preferred_accounts(self.store.preferred_login_accounts)
        if self.detail_view.workstation is not None:
            self.detail_view.account_selector.set_preferred_account(
                self.store.preferred_login_accounts.get(workstation.workstation_id)
            )
        if value is not None:
            self._select_login_account(workstation, value)

    @Slot(str)
    def _set_machine_view(self, view: str) -> None:
        try:
            self.store.save_machine_view(view, self._saved_user)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Ansicht nicht gespeichert", str(exc))
            return
        self.overview_view.set_machine_view(view)

    @Slot(list)
    def _save_machine_order(self, order: list) -> None:
        """Die selbst gelegte Kartenreihenfolge merken.

        Persönlich, nicht gemeinsam: Würde sie geteilt, legte der Letzte, der
        eine Karte verschiebt, die Anordnung für alle fest.
        """
        try:
            stored = self.store.save_machine_order([str(item) for item in order], self._saved_user)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Reihenfolge nicht gespeichert",
                f"Die Anordnung konnte nicht in deinen Einstellungen abgelegt werden: {exc}",
            )
            return
        self.overview_view.set_machine_order(stored)

    def _refresh_login_views(self, workstation: Workstation) -> None:
        self._refresh_workstation_views()
        if self.detail_view.workstation and self.detail_view.workstation.workstation_id == workstation.workstation_id:
            self.detail_view.set_workstation(workstation)

    @Slot(Workstation)
    def _add_login_account(self, workstation: Workstation) -> None:
        from shared.login_accounts import normalize_login_accounts

        account, accepted = QInputDialog.getText(
            self, "Anmeldekonto hinzufügen",
            f"Bestehendes Windows-Konto für {workstation.display_name}:\n"
            "Zum Beispiel ZIELPC\\benutzer, DOMÄNE\\benutzer oder benutzer@firma.de.\n"
            "Es wird nur der Kontoname hinterlegt; kein Windows-Konto angelegt und kein Kennwort gespeichert.",
        )
        if not accepted:
            return
        # A timer may have refreshed the inventory while the modal dialog was open.
        workstation = next((ws for ws in self.workstations if ws.workstation_id == workstation.workstation_id), None)
        if workstation is None:
            QMessageBox.warning(self, "Maschine nicht mehr vorhanden", "Bitte die Maschinenübersicht aktualisieren.")
            return
        try:
            accounts = normalize_login_accounts(workstation.login_accounts + [account])
            if len(accounts) > 100:
                raise ValueError("Pro Maschine können höchstens 100 Anmeldekonten hinterlegt werden.")
        except ValueError as exc:
            QMessageBox.warning(self, "Ungültiges Anmeldekonto", str(exc))
            return
        previous = list(workstation.login_accounts)
        saved_before = deepcopy(self._saved_workstations)
        workstation.login_accounts = accounts
        saved = next((ws for ws in self._saved_workstations if ws.workstation_id == workstation.workstation_id), None)
        if saved is None:
            QMessageBox.warning(self, "Maschine zuerst speichern", "Bitte die Maschinenstammdaten zuerst speichern.")
            workstation.login_accounts = previous
            return
        saved.login_accounts = accounts
        if not self._persist():
            workstation.login_accounts = previous
            self._saved_workstations = saved_before
            self._refresh_login_views(workstation)
            return
        selected = next(value for value in accounts if value.casefold() == account.strip().casefold())
        self._select_login_account(workstation, selected)

    @Slot(Workstation)
    def _assign_agent(self, workstation: Workstation) -> None:
        from shared.agent_snapshot import load_agent_snapshots

        try:
            snapshots = load_agent_snapshots(self.agent_status_service.directory_for(workstation))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Agent-Zuordnung", str(exc))
            return
        newest = {}
        for snapshot in snapshots:
            key = snapshot.workstation_id.strip().casefold()
            if key not in newest or snapshot.observed_at_utc > newest[key].observed_at_utc:
                newest[key] = snapshot
        choices = {"Automatisch über Maschinen-ID / Hostname": None}
        for snapshot in sorted(newest.values(), key=lambda item: item.workstation_id.casefold()):
            choices[f"{snapshot.workstation_id} · {snapshot.hostname} · Meldung {snapshot.observed_at_utc.astimezone():%d.%m. %H:%M:%S}"] = snapshot.workstation_id.strip()
        current = next((i for i, value in enumerate(choices.values())
                        if value and value.casefold() == (workstation.agent_workstation_id or "").casefold()), 0)
        choice, accepted = QInputDialog.getItem(
            self, f"Agent für {workstation.display_name} zuordnen",
            "Den Agenten dieses Zielrechners auswählen.\nDie RDP-Adresse und bestehende Reservierungen bleiben erhalten.",
            list(choices), current, False,
        )
        if not accepted:
            return
        workstation = next((ws for ws in self.workstations if ws.workstation_id == workstation.workstation_id), None)
        if workstation is None:
            return
        selected = choices[choice]
        expected = (selected or workstation.workstation_id).casefold()
        if any(ws is not workstation and (ws.agent_workstation_id or ws.workstation_id).strip().casefold() == expected
               for ws in self.workstations):
            QMessageBox.warning(self, "Agent bereits zugeordnet", "Dieser Agent ist bereits einer anderen Maschine zugeordnet.")
            return
        saved = next((ws for ws in self._saved_workstations if ws.workstation_id == workstation.workstation_id), None)
        if saved is None:
            QMessageBox.warning(self, "Maschine zuerst speichern", "Bitte zuerst die Maschinenstammdaten speichern.")
            return
        previous, saved_previous = workstation.agent_workstation_id, saved.agent_workstation_id
        workstation.agent_workstation_id = saved.agent_workstation_id = selected
        if not self._persist():
            workstation.agent_workstation_id, saved.agent_workstation_id = previous, saved_previous
            return
        self._poll_agent_status()
        self.detail_view.set_workstation(workstation)

    @Slot(Workstation)
    def _setup_workstation_fallback(self, workstation: Workstation) -> None:
        from portal_app.ui.widgets.share_setup_dialog import ShareSetupDialog

        try:
            target, _ = workstation.get_connection_target()
        except ValueError:
            target = workstation.hostname
        server = unc_server_name(workstation.hostname or target or workstation.display_name)
        # Do not prefill a machine with the former global fallback.  Its server
        # and the machine-local PortalLeser account can otherwise be mixed (for
        # example Remote-Ettlingen as server with NB12KI as account).  Only a
        # path explicitly saved for this machine is safe to offer again.
        current = (
            workstation.agent_fallback_directory or ""
            if workstation.agent_fallback_is_explicit
            else ""
        )
        dialog = ShareSetupDialog(
            current,
            self,
            suggested_path=fr"\\{server}\RDP-Status",
            suggested_username=fr"{server}\PortalLeser",
            workstation_name=workstation.display_name,
        )
        self.agent_poll_timer.stop()
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            path = self.store.set_workstation_agent_status_directory(
                workstation.workstation_id,
                dialog.connected_path,
            )
            workstation.agent_fallback_directory = str(path)
            workstation.agent_fallback_is_explicit = True
            self._poll_agent_status()
            self.detail_view.set_workstation(workstation)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Datei-Fallback nicht gespeichert", str(exc))
        finally:
            self.agent_poll_timer.start()
            dialog.deleteLater()

    # --- Connection assistant and central agent administration ---------------

    def _configured_fallback_paths(self) -> dict[str, str]:
        """Every explicitly configured UNC fallback, keyed by machine ID."""
        return {
            ws.workstation_id: ws.agent_fallback_directory
            for ws in self.workstations
            if ws.agent_fallback_is_explicit
            and (ws.agent_fallback_directory or "").startswith("\\\\")
        }

    @Slot()
    def _reconnect_status_shares(self) -> None:
        """Ask Windows to re-establish the SMB session of every status share."""
        paths = self._configured_fallback_paths()
        for server in self._retired_credential_servers:
            paths.setdefault(f"server:{server}", rf"\\{server}\RDP-Status")
        if not paths:
            self._refresh_agent_panel()
            return
        if self.share_reconnector.request(paths):
            self.settings_view.agent_connection.set_status(
                f"{len(paths)} Statusfreigabe(n) werden verbunden …"
            )

    @Slot(object)
    def _on_shares_reconnected(self, results: object) -> None:
        if not isinstance(results, dict):
            return
        failures = [message for success, message in results.values() if not success]
        connected = len(results) - len(failures)
        summary = f"{connected} von {len(results)} Statusfreigabe(n) verbunden."
        if failures:
            # Name the first few rather than only counting them: a wrong password
            # and a switched-off machine need different reactions.
            summary += " " + " ".join(sorted(set(failures))[:3])
        self.settings_view.agent_connection.set_status(summary)
        logger.info("Statusfreigaben verbunden: %s", summary)
        self._poll_agent_status(blocking=False)

    def _run_connection_wizard(self, *, first_run: bool = False) -> None:
        """Search for agents, then create or link the machines they belong to."""
        wizard = MachineRegistrationWizard(
            parent=self, workstations=self.workstations, first_run=first_run
        )
        # The sweep and the live poller both talk to the same single-instance
        # pipes; letting the timer fire into a running scan only produces
        # spurious failures on machines the scan is already holding.
        self.agent_poll_timer.stop()
        try:
            accepted = wizard.exec() == QDialog.Accepted
        finally:
            self.agent_poll_timer.start()
        self._remember_discovered_agents(wizard)
        self._show_reader_account()
        if not accepted:
            return
        if wizard.mode == "scan":
            self._apply_agent_assignments(wizard.assignments)
            return
        self._create_machine_from_preview(wizard)

    def _remember_discovered_agents(self, wizard: MachineRegistrationWizard) -> None:
        known = set(self._discovered_agent_ids)
        for probe in wizard.probes:
            if probe.identified:
                known.add(probe.workstation_id)
        self._discovered_agent_ids = sorted(known)
        self._refresh_agent_panel()

    def _create_machine_from_preview(self, wizard: MachineRegistrationWizard) -> None:
        """The single-machine route: show the full profile form as before."""
        dialog = WorkstationDialog(
            suggested_id=self._next_workstation_id(),
            prefill=wizard.prefill,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted or not dialog.workstation:
            return
        if any(ws.workstation_id == dialog.workstation.workstation_id for ws in self.workstations):
            QMessageBox.warning(self, "Doppelte ID", "Diese Maschinen-ID ist bereits vergeben.")
            return
        fallback, explicit = self.store.get_workstation_agent_status_directory(
            dialog.workstation.workstation_id
        )
        dialog.workstation.agent_fallback_directory = str(fallback)
        dialog.workstation.agent_fallback_is_explicit = explicit
        self.workstations.append(dialog.workstation)
        probe = wizard.selected_probe
        if probe is not None and probe.identified:
            self._attach_agent(dialog.workstation, probe)
        self._refresh_workstation_views()
        if dialog.should_save or probe is not None:
            self._commit_workstation(dialog.workstation)
            self._persist()
        self._refresh_agent_panel()

    def _apply_agent_assignments(self, assignments: list[AgentAssignment]) -> None:
        """Create or link one machine per chosen agent and connect its fallback."""
        if not assignments:
            return
        created: list[str] = []
        linked: list[str] = []
        problems: list[str] = []
        for assignment in assignments:
            probe = assignment.probe
            claimed = next(
                (
                    ws
                    for ws in self.workstations
                    if (ws.agent_workstation_id or "").strip().casefold()
                    == probe.workstation_id.casefold()
                    and ws.workstation_id != assignment.workstation_id
                ),
                None,
            )
            if claimed is not None:
                problems.append(
                    f"{probe.workstation_id}: bereits {claimed.display_name} zugeordnet."
                )
                continue
            if assignment.creates_machine:
                workstation = self._machine_from_assignment(assignment)
                if workstation is None:
                    problems.append(f"{probe.target}: keine gültigen Verbindungsdaten ermittelt.")
                    continue
                self.workstations.append(workstation)
                created.append(workstation.display_name)
            else:
                workstation = next(
                    (
                        ws
                        for ws in self.workstations
                        if ws.workstation_id == assignment.workstation_id
                    ),
                    None,
                )
                if workstation is None:
                    problems.append(f"{assignment.workstation_id}: Maschine nicht mehr vorhanden.")
                    continue
                if assignment.site:
                    workstation.site = assignment.site
                linked.append(workstation.display_name)
            message = self._attach_agent(workstation, probe)
            if message:
                problems.append(message)
            self._commit_workstation(workstation)
        self._refresh_workstation_views()
        self._persist()
        self._poll_agent_status(blocking=False)
        self._refresh_agent_panel()
        self._report_assignments(created, linked, problems)

    def _report_assignments(
        self,
        created: list[str],
        linked: list[str],
        problems: list[str],
    ) -> None:
        lines = []
        if created:
            lines.append(f"Neu angelegt: {', '.join(created)}")
        if linked:
            lines.append(f"Verknüpft: {', '.join(linked)}")
        if problems:
            lines.append("\nNicht eingerichtet:\n" + "\n".join(problems))
        if not lines:
            return
        show = QMessageBox.warning if problems else QMessageBox.information
        show(self, "Verbindungsassistent", "\n".join(lines))

    def _machine_from_assignment(self, assignment: AgentAssignment) -> Workstation | None:
        """Build a machine from what the agent and DNS reported about it."""
        prefill = assignment.prefill()
        if not (prefill.get("hostname") or prefill.get("ip_address") or prefill.get("fqdn")):
            return None
        workstation_id = self._next_workstation_id()
        fallback, explicit = self.store.get_workstation_agent_status_directory(workstation_id)
        return Workstation(
            workstation_id=workstation_id,
            display_name=prefill.get("display_name") or workstation_id,
            hostname=prefill.get("hostname", ""),
            fqdn=prefill.get("fqdn") or None,
            ip_address=prefill.get("ip_address") or None,
            subnet_mask=prefill.get("subnet_mask") or None,
            default_gateway=prefill.get("default_gateway") or None,
            dns_server=prefill.get("dns_server") or None,
            site=prefill.get("site") or None,
            agent_fallback_directory=str(fallback),
            agent_fallback_is_explicit=explicit,
        )

    def _attach_agent(self, workstation: Workstation, probe) -> str:
        """Record the agent for a machine and set up its file fallback.

        Returns a problem description, or an empty string on success. Both steps
        belong together: an agent that is reachable over the pipe today may be
        reachable only over the share tomorrow, and the assignment is what makes
        either channel attributable to this machine.
        """
        if probe.identified:
            workstation.agent_workstation_id = probe.workstation_id
        return self._auto_setup_fallback(workstation, probe)

    def _auto_setup_fallback(self, workstation: Workstation, probe) -> str:
        """Point a machine at its agent's own status share and connect it.

        The agent setup always creates ``RDP-Status`` on the target, so the path
        is derivable rather than something a person has to type per machine --
        which is what made this step get skipped and the fallback stay unset.
        """
        from portal_app.services.share_connection import connect_status_share

        server = unc_server_name(probe.hostname or probe.target or workstation.hostname)
        if not server:
            return f"{workstation.display_name}: kein Servername für die Statusfreigabe."
        path = rf"\\{server}\RDP-Status"
        connected, message = connect_status_share(path)
        if not connected:
            return f"{workstation.display_name}: {message}"
        try:
            stored = self.store.set_workstation_agent_status_directory(
                workstation.workstation_id, path
            )
        except (OSError, ValueError) as exc:
            return f"{workstation.display_name}: Fallback nicht gespeichert ({exc})."
        workstation.agent_fallback_directory = str(stored)
        workstation.agent_fallback_is_explicit = True
        return ""

    def _show_reader_account(self) -> None:
        """Tell the settings page which reader account is in use, and whence."""
        from portal_app.services.share_connection import (
            reader_account_name,
            reader_account_source,
        )

        try:
            name, source = reader_account_name(), reader_account_source()
        except Exception:  # noqa: BLE001 - an absent credential store is not an error
            name, source = "", "none"
        self.settings_view.agent_connection.set_reader_account(name, source)

    @Slot(str, str)
    def _save_reader_credentials(self, username: str, password: str) -> None:
        from portal_app.services.share_connection import save_reader_credentials

        try:
            save_reader_credentials(username, password)
        except Exception as exc:  # noqa: BLE001 - shown, never fatal
            self.settings_view.agent_connection.set_status(
                f"Lesekonto konnte nicht gespeichert werden: {exc}"
            )
            return
        self._show_reader_account()
        self._reconnect_status_shares()

    @Slot(str, str)
    def _set_agent_assignment(self, workstation_id: str, agent_id: str) -> None:
        """Apply an assignment made in the settings table."""
        workstation = next(
            (ws for ws in self.workstations if ws.workstation_id == workstation_id), None
        )
        if workstation is None:
            return
        expected = (agent_id or workstation.workstation_id).strip().casefold()
        if any(
            ws is not workstation
            and (ws.agent_workstation_id or ws.workstation_id).strip().casefold() == expected
            for ws in self.workstations
        ):
            QMessageBox.warning(
                self,
                "Agent bereits zugeordnet",
                "Dieser Agent ist bereits einer anderen Maschine zugeordnet.",
            )
            self._refresh_agent_panel()
            return
        saved = next(
            (ws for ws in self._saved_workstations if ws.workstation_id == workstation_id), None
        )
        previous = workstation.agent_workstation_id
        workstation.agent_workstation_id = agent_id or None
        if saved is not None:
            saved.agent_workstation_id = agent_id or None
        if not self._persist():
            workstation.agent_workstation_id = previous
            if saved is not None:
                saved.agent_workstation_id = previous
        self._poll_agent_status(blocking=False)
        self._refresh_agent_panel()

    @Slot(str)
    def _setup_fallback_by_id(self, workstation_id: str) -> None:
        workstation = next(
            (ws for ws in self.workstations if ws.workstation_id == workstation_id), None
        )
        if workstation is not None:
            self._setup_workstation_fallback(workstation)
            self._refresh_agent_panel()

    def _refresh_agent_panel(self) -> None:
        if not hasattr(self, "settings_view"):
            return
        panel = self.settings_view.agent_connection
        panel.set_known_agents(self._discovered_agent_ids)
        panel.set_workstations(self.workstations)

    @staticmethod
    def _cleanup_stale_rdp_files() -> None:
        """Remove .rdp files an earlier run could not delete."""
        from portal_app.rdp import cleanup_old_rdp_files

        try:
            removed = cleanup_old_rdp_files(older_than_hours=24)
        except OSError as exc:
            logger.warning("Alte RDP-Dateien konnten nicht entfernt werden: %s", exc)
            return
        if removed:
            logger.info("%s verwaiste RDP-Datei(en) aus dem Temp-Ordner entfernt", removed)

    @Slot()
    def _learn_reported_account(self, workstation: Workstation) -> bool:
        r"""Adopt the account name the agent reports for a session opened from here.

        The portal knows which account it connected *with*; the agent reports
        which account the session actually runs under. For an Entra account those
        are two unrelated spellings -- ``schaelike-adm@firma.de`` against
        ``AzureAD\HendrikSchaelikeAdmin`` -- so remembering only the first left
        a person's own machine showing up as occupied by a stranger.

        The link between the two is attested rather than guessed: the session
        names this computer as its RDP client, which Windows reports and which
        the agent uses for its own authorization. Only sessions for which this
        portal still tracks an open window are considered, so a session somebody
        else once opened from this PC is not adopted.
        """
        from portal_app.rdp import has_active_rdp_session
        from portal_app.services.local_identity import local_machine_names
        from shared.session_identity import is_active_session, session_username

        if not has_active_rdp_session(workstation.workstation_id):
            return False
        here = local_machine_names()
        claimed = False
        for item in workstation.agent_sessions:
            if not is_active_session(item):
                continue
            reported = {
                str(item.get(key) or "").strip().casefold()
                for key in ("client_name", "client_address")
            }
            if not (reported & here):
                continue
            account = session_username(item)
            # Dieselbe Lücke wie oben, nur für die Aufschaltmeldung: Gemeldet
            # wurde beim Start der Kontoname, mit dem das Portal verbindet. Bei
            # einem Entra-Konto ist das die UPN, während der Agent die Sitzung
            # unter dem Profilnamen führt -- dann fände die Meldung ihre Sitzung
            # nie. Hier ist die Zuordnung durch den Client-Namen bezeugt, also
            # wird sie unter der Schreibweise nachgereicht, die der Agent
            # tatsächlich meldet. Einmal pro Konto und Maschine, sonst ginge bei
            # jedem Statuslauf eine Pipe-Anfrage hinaus.
            if (workstation.workstation_id, account.casefold()) not in self._reported_claims:
                self._reported_claims.add((workstation.workstation_id, account.casefold()))
                self._report_session_claim(workstation, account)
            if self.current_user.claim_account(account):
                claimed = True
        return claimed

    def _poll_rdp_sessions(self) -> None:
        """Record closed RDP clients without adding a persistent visual notice."""
        from portal_app.rdp import consume_finished_rdp_sessions

        finished = consume_finished_rdp_sessions()
        for session in finished:
            workstation = next(
                (item for item in self.workstations if item.workstation_id == session.workstation_id),
                None,
            )
            if workstation:
                self._record_event(
                    workstation,
                    EventType.RDP_DISCONNECT,
                    EventResult.SUCCESS,
                    "Lokales RDP-Fenster nicht mehr vorhanden",
                )

    @Slot()
    def _poll_agent_status(self, *, blocking: bool = True) -> None:
        """Refresh reservations and the agent file fallback.

        ``blocking`` reads the fallback folders inline and is what startup,
        explicit user actions and the tests rely on.  The recurring heartbeat
        passes ``blocking=False``: reading a UNC path can stall for the SMB
        timeout, which must never happen on the Qt main thread, so the read goes
        to ``FallbackScanner`` and the result arrives in
        ``_on_fallback_scan_completed``.
        """
        reservation_changed = apply_reservations(self.workstations, self.reservations, self.current_user.upn)
        if reservation_changed:
            self._refresh_workstation_views()
        try:
            self.agent_status_service.set_directory(self.store.agent_status_directory)
            directories = self.agent_status_service.fallback_directories(self.workstations)
        except (OSError, ValueError) as exc:
            self._report_agent_status_failure(exc)
            return
        if not blocking:
            self._reservation_change_pending = self._reservation_change_pending or reservation_changed
            # A scan that is still running will deliver on its own; queuing a
            # second one would only build a backlog behind a slow share.
            self.fallback_scanner.request(directories)
            return
        try:
            scans = self.agent_status_service.scan_directories(directories)
        except (OSError, ValueError) as exc:
            self._report_agent_status_failure(exc)
            return
        self._apply_fallback_scans(scans, reservation_changed)

    def _report_agent_status_failure(self, exc: Exception) -> None:
        self._update_storage_status(f"Agent-Status nicht lesbar: {exc}")
        self.settings_view.agent_status.setText(f"Agent-Status nicht lesbar: {exc}")
        self.settings_view.set_agent_report(f"RDP-Portal {PORTAL_VERSION}\nKonfiguration: {self.store.agent_config_path}\nFehler: {exc}")
        self.overview_view.agent_channel_status.setText("Agent-Status nicht lesbar · Einstellungen prüfen")

    @Slot(object)
    def _on_fallback_scan_completed(self, scans: object) -> None:
        """Apply a background folder scan on the UI thread."""
        reservation_changed = self._reservation_change_pending
        self._reservation_change_pending = False
        try:
            self._apply_fallback_scans(scans, reservation_changed)
        except (OSError, ValueError) as exc:
            self._report_agent_status_failure(exc)

    def _apply_fallback_scans(self, scans: object, reservation_changed: bool) -> None:
        self._last_fallback_scans = scans
        changed =self.agent_status_service.apply_scans(self.workstations, scans)
        self.settings_view.set_agent_bridge_status(
            self.agent_status_service.last_match_count,
            self.agent_status_service.last_snapshot_count,
            self.agent_status_service.directory_summary,
            self.agent_status_service.last_errors,
        )
        service = self.agent_status_service
        self.settings_view.set_agent_report(service.last_report + f"\nPortalprogramm: {Path(sys.executable).resolve()}\nInventar: {self.store.path}\nKonfiguration: {self.store.agent_config_path}")
        checked = service.last_checked_at.astimezone().strftime("%H:%M:%S")
        live_count = sum(ws.agent_status_source == "live" and not ws.agent_live_error for ws in self.workstations)
        fallback_count = sum(ws.agent_status_source == "file" for ws in self.workstations)
        result = (
            f"Live {live_count} · Datei-Fallback {fallback_count} · "
            f"{service.last_match_count}/{len(self.workstations)} Maschinen zugeordnet"
        )
        if service.last_errors:
            result += " · Lesefehler"
        self.overview_view.agent_channel_status.setText(
            f"Automatisch alle {self.store.status_refresh_interval} s · Prüfung {checked}: {result}"
        )
        self.overview_view.agent_channel_status.setToolTip(service.directory_summary)
        reservation_changed = self._adopt_reported_reservations() or reservation_changed
        # Offene Aufschaltmeldungen nachreichen. Muss vor _learn_reported_account
        # stehen: Dieses meldet nach, was der Agent tatsächlich sieht, und dabei
        # soll der frische Stand aus dem gerade gelesenen Snapshot gelten.
        self._claim_reporter.flush(self.workstations, self.current_user)
        if any(self._learn_reported_account(ws) for ws in self.workstations):
            self._saved_user = deepcopy(self.current_user)
            reservation_changed = True
        if not changed and not reservation_changed:
            return
        # Heartbeats are transient. They must not save unsaved form changes or
        # cause competing writes to the shared machine configuration.
        self._refresh_status_views()

    @Slot()
    def _scheduled_status_update(self) -> None:
        """Recurring heartbeat: never read the fallback folders on this thread."""
        if self._automatic_live_status_enabled:
            self._run_status_update_cycle(blocking=False)
        else:
            self._poll_agent_status(blocking=False)

    @Slot()
    def _run_status_update_cycle(
        self,
        workstations: list[Workstation] | None = None,
        *,
        force: bool = False,
        blocking: bool = True,
    ) -> None:
        """Refresh file fallback, then start bounded direct status requests."""
        self._poll_agent_status(blocking=blocking)
        targets = self.workstations if workstations is None else workstations
        # Der Agent hat genau eine Pipe-Instanz und bedient sie seriell. Eine
        # Abmeldung belegt sie, bis Windows die Sitzung abgebaut hat -- dafuer
        # steht LOGOFF_TIMEOUT_MS. Jede STATUS/1-Abfrage dorthin muss in dieser
        # Zeit in den Timeout laufen. Sie trotzdem zu stellen haette die Maschine
        # als "Agent nicht erreichbar" gezeigt, genau waehrend der Benutzer der
        # Abmeldung zusieht, und danach noch den Backoff der Live-Abfrage geerbt.
        if self._logoff_in_progress:
            targets = [
                item
                for item in targets
                if item.workstation_id not in self._logoff_in_progress
            ]
        started = self.live_status_poller.request_many(
            targets,
            self.store.status_refresh_interval,
            force=force,
        )
        if started:
            self.overview_view.agent_channel_status.setText(
                f"Live-Status wird für {started} Maschine(n) im Hintergrund aktualisiert …"
            )

    @Slot(str, object, object, int)
    def _on_live_status_succeeded(
        self,
        workstation_id: str,
        route: object,
        snapshot: object,
        elapsed: int,
    ) -> None:
        workstation = next(
            (item for item in self.workstations if item.workstation_id == workstation_id),
            None,
        )
        if workstation is None:
            return
        try:
            if workstation.get_agent_status_target() != route:
                return
            self.agent_status_service.accept_live_snapshot(workstation, snapshot, elapsed)
        except ValueError as exc:
            self.agent_status_service.record_live_failure(workstation, str(exc))
        self._schedule_live_apply()

    @Slot(str, object, str)
    def _on_live_status_failed(
        self,
        workstation_id: str,
        route: object,
        message: str,
    ) -> None:
        workstation = next(
            (item for item in self.workstations if item.workstation_id == workstation_id),
            None,
        )
        if workstation is None:
            return
        if route is not None:
            try:
                if workstation.get_agent_status_target() != route:
                    return
            except ValueError:
                return
        self.agent_status_service.record_live_failure(workstation, message)
        self._schedule_live_apply()

    def _schedule_live_apply(self) -> None:
        """Apply live answers once per burst instead of once per machine."""
        if not self._live_apply_timer.isActive():
            self._live_apply_timer.start()

    @Slot()
    def _apply_live_results(self) -> None:
        """Re-apply the last folder scan together with the new live answers.

        Reads no folder: the file fallback is refreshed by the heartbeat in the
        background. Only without any scan yet is one requested there.
        """
        if self._last_fallback_scans is None:
            self._poll_agent_status(blocking=False)
            return
        reservation_changed = apply_reservations(
            self.workstations, self.reservations, self.current_user.upn
        )
        try:
            self._apply_fallback_scans(self._last_fallback_scans, reservation_changed)
        except (OSError, ValueError) as exc:
            self._report_agent_status_failure(exc)

    @Slot(int)
    def _set_status_refresh_interval(self, seconds: int) -> None:
        try:
            seconds = self.store.save_status_refresh_interval(seconds, self._saved_user)
        except (OSError, ValueError) as exc:
            self.settings_view.set_status_refresh_interval(
                self.store.status_refresh_interval
            )
            QMessageBox.warning(self, "Statusintervall nicht gespeichert", str(exc))
            return
        self.agent_poll_timer.setInterval(seconds * 1000)
        self.live_status_poller.set_interval(seconds)
        self._run_status_update_cycle(force=True)

    @Slot()
    def _show_agent_diagnostics(self) -> None:
        self.nav_buttons[self.PAGE_SETTINGS].setChecked(True)
        self._on_navigation_clicked(self.nav_buttons[self.PAGE_SETTINGS])
        self.settings_view.scroll.verticalScrollBar().setValue(0)
        self._poll_agent_status()

    def _on_navigation_clicked(self, button: QPushButton) -> None:
        page_index = int(button.property("pageIndex"))
        if page_index == self.PAGE_ADMIN and not self._admin_unlocked:
            if not self._request_admin_access():
                current_page = self.stack.currentIndex()
                fallback_page = current_page if 0 <= current_page < self.PAGE_DETAIL else self.PAGE_MACHINES
                self.nav_buttons[fallback_page].setChecked(True)
                return
        if page_index == self.PAGE_ADMIN and self.directory_mode == "active_directory":
            self._update_active_directory_status()
        self.stack.setCurrentIndex(page_index)
        if page_index == self.PAGE_CALENDAR:
            self.calendar_view.set_workstations(self.workstations)
        elif page_index == self.PAGE_ADMIN:
            self.admin_view.set_workstations(self.workstations)
        pages = (
            ("ARBEITSPLATZÜBERSICHT", "Maschinen", "Verfügbare Arbeitsplätze und aktive Sitzungen auf einen Blick."),
            ("PLANUNG", "Reservierungen", "Maschinen über mehrere Tage und Zeiträume reservieren."),
            ("AKTIVITÄTEN", "Logs", "Verbindungen, Sitzungen und Systemereignisse nachvollziehen."),
            ("VERWALTUNG", "Administration", "Maschinenstammdaten zentral verwalten."),
            ("KONFIGURATION", "Einstellungen", "Allgemeine Benutzer- und RDP-Einstellungen."),
        )
        eyebrow, title, subtitle = pages[page_index]
        self.page_eyebrow.setText(eyebrow)
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        machines_page = page_index == self.PAGE_MACHINES
        self.page_eyebrow.setVisible(not machines_page)
        self.page_subtitle.setVisible(not machines_page)
        self.summary.setVisible(machines_page)
        self.overview_refresh_button.setVisible(machines_page)
        if page_index == self.PAGE_MACHINES and self._automatic_live_status_enabled:
            self._run_status_update_cycle(force=True)

    def _request_admin_access(self) -> bool:
        if self.directory_mode != "active_directory":
            return self._request_global_admin_access()
        authorization = check_windows_admin_authorization()
        if authorization.authorized:
            self._unlock_admin(f"Admin per Windows-Gruppe: {authorization.group_name}")
            return True
        if not test_password_fallback_allowed():
            QMessageBox.warning(
                self,
                "Admin-Zugang verweigert",
                f"{authorization.message}\n\nDie Passwort-Freigabe ist im AD-Modus deaktiviert.",
            )
            return False
        return self._request_global_admin_access()

    def _request_global_admin_access(self) -> bool:
        password, accepted = QInputDialog.getText(
            self,
            "Admin-Zugang",
            "Globales Portal-Admin-Passwort:",
            QLineEdit.Password,
        )
        if not accepted:
            return False
        try:
            correct = self.admin_password_verifier.verify_password(password)
        except AdminLockoutError as exc:
            QMessageBox.warning(self, "Adminzugang gesperrt", str(exc))
            return False
        if not correct:
            QMessageBox.warning(self, "Zugriff verweigert", "Das eingegebene Admin-Passwort ist nicht korrekt.")
            return False
        self._unlock_admin("Globales Portal-Admin-Passwort bestätigt")
        return True

    def _unlock_admin(self, access_label: str) -> None:
        self._admin_unlocked = True
        self.admin_view.set_access_status(True, access_label)
        self.nav_buttons[self.PAGE_ADMIN].setText("Admin · offen")

    def _lock_admin(self) -> None:
        self._admin_unlocked = False
        self.admin_view.set_access_status(False)
        self.nav_buttons[self.PAGE_ADMIN].setText("Admin")
        self._show_machines()

    @Slot()
    def _update_active_directory_status(self) -> None:
        readiness = check_active_directory_readiness()
        self.admin_view.set_active_directory_status(readiness.message)

    @Slot(str)
    def _change_agent_directory(self, directory: str) -> None:
        try:
            self.store.set_agent_status_directory(directory)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Agent-Statusordner nicht gespeichert", str(exc))
            return
        self._apply_local_agent_fallbacks()
        self._poll_agent_status()

    @Slot()
    def _save_admin_settings(self) -> None:
        if not self._admin_unlocked:
            return
        self._saved_workstations = deepcopy(self.workstations)
        self.admin_view.save_button.setEnabled(False)
        try:
            if self._persist():
                self._sync_shared_store()
                self._update_storage_status("Maschineneinstellungen gespeichert")
        finally:
            self.admin_view.save_button.setEnabled(self._admin_unlocked)

    def _has_unsaved_machine_settings(self) -> bool:
        """Ignore live session updates when checking for unsaved machine edits."""
        transient = {
            "agent_status", "agent_last_seen_utc", "agent_version",
            "current_session_state", "current_session_user", "current_windows_session_id",
            "last_session_event_utc", "etag",
        }

        def settings(workstations):
            return {
                ws.workstation_id: ws.to_schema().model_dump(exclude=transient)
                for ws in workstations
            }

        return settings(self.workstations) != settings(self._saved_workstations)

    @Slot(Workstation)
    def on_workstation_selected(self, workstation: Workstation) -> None:
        self.workstation_selected.emit(workstation)
        self.detail_view.account_selector.set_preferred_account(
            self.store.preferred_login_accounts.get(workstation.workstation_id)
        )
        events = [
            event for event in self.session_events if event.workstation_id == workstation.workstation_id
        ]
        self.detail_view.set_session_events(events)
        self.stack.setCurrentIndex(self.PAGE_DETAIL)
        self.page_eyebrow.setText("MASCHINENDETAILS")
        self.page_title.setText(workstation.display_name)
        self.page_subtitle.setText(workstation.get_connection_target_display())
        self.page_eyebrow.show()
        self.page_subtitle.show()
        self.summary.setVisible(False)
        self.overview_refresh_button.hide()

    def _show_machines(self) -> None:
        self.nav_buttons[self.PAGE_MACHINES].setChecked(True)
        self._on_navigation_clicked(self.nav_buttons[self.PAGE_MACHINES])

    def _next_workstation_id(self) -> str:
        numbers = []
        for ws in self.workstations:
            try:
                numbers.append(int(ws.workstation_id.rsplit("-", 1)[-1]))
            except ValueError:
                continue
        return f"WS-{max(numbers, default=0) + 1:03d}"

    def _add_workstation(self) -> None:
        self._run_connection_wizard()

    @Slot(Workstation)
    def _edit_workstation(self, workstation: Workstation) -> None:
        dialog = WorkstationDialog(workstation=workstation, parent=self)
        if dialog.exec() != QDialog.Accepted or not dialog.workstation:
            return
        dialog.workstation.agent_fallback_directory = workstation.agent_fallback_directory
        dialog.workstation.agent_fallback_is_explicit = workstation.agent_fallback_is_explicit
        index = self.workstations.index(workstation)
        self.workstations[index] = dialog.workstation
        self._refresh_workstation_views()
        if self.stack.currentIndex() == self.PAGE_DETAIL:
            self.on_workstation_selected(dialog.workstation)
        if dialog.should_save:
            self._commit_workstation(dialog.workstation)
            self._persist()

    @Slot(Workstation)
    def _on_workstation_updated(self, workstation: Workstation) -> None:
        previous = next((ws for ws in self._saved_workstations if ws.workstation_id == workstation.workstation_id), None)
        flag_changed = previous is not None and (
            previous.manual_flag_type != workstation.manual_flag_type
            or previous.manual_flag_set_at_utc != workstation.manual_flag_set_at_utc
        )
        self._refresh_workstation_views()
        self.detail_view.set_workstation(workstation)
        self._commit_workstation(workstation)
        if self._persist() and flag_changed:
            event_type = EventType.MANUAL_FLAG_CLEARED if workstation.manual_flag_type == ManualFlagType.NONE else EventType.MANUAL_FLAG_SET
            self._record_event(workstation, event_type, EventResult.SUCCESS, workstation.manual_flag_reason)

    @Slot(Workstation)
    def _force_disconnect_workstation(self, workstation: Workstation) -> None:
        from portal_app.rdp import disconnect_rdp_session, has_active_rdp_session

        if not has_active_rdp_session(workstation.workstation_id):
            QMessageBox.information(
                self,
                "Kein lokales RDP-Fenster",
                f"Für {workstation.display_name} läuft kein von diesem Portal gestartetes RDP-Fenster.\n\n"
                "Eine möglicherweise auf dem Zielrechner verbliebene Windows-Sitzung kann ohne "
                "administrativen Remotezugriff oder Agent nicht zuverlässig abgemeldet werden.",
            )
            return
        answer = QMessageBox.warning(
            self,
            "RDP-Verbindung trennen",
            f"Das RDP-Fenster für {workstation.display_name} wird sofort beendet.\n\n"
            "Die Programme auf dem Zielrechner laufen weiter; die Windows-Sitzung kann dort als "
            "„Getrennt“ angemeldet bleiben. Verbindung wirklich trennen?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        self._record_event(
            workstation,
            EventType.ADMIN_DISCONNECT_REQUESTED,
            EventResult.PENDING,
            source=EventSource.ADMIN,
        )
        disconnected, failures = disconnect_rdp_session(workstation.workstation_id)
        if failures or disconnected == 0:
            self._record_event(
                workstation,
                EventType.ADMIN_DISCONNECT_FAILED,
                EventResult.FAILED,
                "Lokales RDP-Fenster konnte nicht beendet werden",
                EventSource.ADMIN,
            )
            QMessageBox.critical(
                self,
                "Trennen fehlgeschlagen",
                f"Das RDP-Fenster für {workstation.display_name} konnte nicht beendet werden.",
            )
            return
        self._record_event(
            workstation,
            EventType.ADMIN_DISCONNECT_COMPLETED,
            EventResult.SUCCESS,
            source=EventSource.ADMIN,
        )
        self._poll_rdp_sessions()
        QMessageBox.information(
            self,
            "RDP getrennt",
            f"Das lokale RDP-Fenster für {workstation.display_name} wurde beendet. "
            "Dies ist kein vollständiges Windows-Logoff.",
        )

    @Slot(Workstation)
    def _admin_logoff_workstation(self, workstation: Workstation) -> None:
        """Offer a separate emergency WTS action; Windows remains the authority."""
        from portal_app.ui.widgets.session_logoff_dialog import SessionLogoffDialog

        if not self._admin_unlocked:
            return
        sessions = [
            dict(item)
            for item in workstation.agent_sessions
            if is_active_session(item)
            and type(item.get("session_id")) is int
            and item["session_id"] > 0
            and item.get("login_time")
        ]
        if not sessions:
            QMessageBox.warning(
                self,
                "Keine prüfbare Sitzung",
                "Für die Notfall-Abmeldung wird eine aktuelle Agent-Meldung mit Benutzer, "
                "Sitzungsnummer und Anmeldezeit benötigt.",
            )
            return
        labels = []
        for item in sessions:
            username = session_username(item)
            labels.append(
                f"{username} · Sitzung {item['session_id']} · {item.get('session_state')} · {item['login_time']}"
            )
        selected_index = 0
        if len(sessions) > 1:
            label, accepted = QInputDialog.getItem(
                self,
                "Administrative Notfall-Abmeldung",
                "Welche Windows-Sitzung soll nach erneuter Live-Prüfung abgemeldet werden?",
                labels,
                0,
                False,
            )
            if not accepted:
                return
            selected_index = labels.index(label)
        try:
            target, _ = workstation.get_connection_target()
        except ValueError as exc:
            QMessageBox.warning(self, "Ziel fehlt", str(exc))
            return
        dialog = SessionLogoffDialog(
            target,
            workstation.display_name,
            sessions[selected_index],
            self,
            administrative=True,
            expected_agent_id=workstation.agent_workstation_id or workstation.workstation_id,
            status_target=workstation.get_agent_status_target(),
            hostnames=None if workstation.agent_workstation_id else machine_hostnames(workstation),
        )
        dialog.request_finished.connect(
            lambda success, message, ws=workstation: self._admin_logoff_finished(
                ws, success, message
            )
        )
        self._logoff_in_progress.add(workstation.workstation_id)
        try:
            dialog.exec()
        finally:
            self._logoff_in_progress.discard(workstation.workstation_id)
        dialog.deleteLater()

    def _admin_logoff_finished(
        self,
        workstation: Workstation,
        success: bool,
        message: str,
    ) -> None:
        # Der Agent antwortet wieder, sobald die Anfrage zurueck ist -- nicht erst,
        # wenn der Dialog geschlossen wird.
        self._logoff_in_progress.discard(workstation.workstation_id)
        self._record_event(
            workstation,
            EventType.ADMIN_LOGOFF_COMPLETED if success else EventType.ADMIN_LOGOFF_FAILED,
            EventResult.SUCCESS if success else EventResult.FAILED,
            message,
            EventSource.ADMIN,
        )
        if success:
            self._run_status_update_cycle([workstation], force=True)

    @Slot(Workstation)
    def _delete_workstation(self, workstation: Workstation) -> None:
        from portal_app.rdp import has_active_rdp_session

        active_note = ""
        if has_active_rdp_session(workstation.workstation_id):
            active_note = (
                "\n\nFür diese Maschine läuft noch ein lokales RDP-Fenster. "
                "Es wird durch das Löschen nicht beendet."
            )
        answer = QMessageBox.warning(
            self,
            "Maschine löschen",
            f"{workstation.display_name} ({workstation.workstation_id}) wirklich aus dem Portal entfernen?\n\n"
            "Das entfernt auch ihre Reservierungen. Die Maschine selbst und eine vorhandene "
            f"Windows-Sitzung bleiben unverändert.{active_note}",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        self.workstations = [
            candidate
            for candidate in self.workstations
            if candidate.workstation_id != workstation.workstation_id
        ]
        self.reservations = [
            reservation
            for reservation in self.reservations
            if reservation.workstation_id != workstation.workstation_id
        ]
        self._saved_workstations = deepcopy(self.workstations)
        self.calendar_view.reservations = list(self.reservations)
        self._refresh_workstation_views()
        if (
            self.detail_view.workstation is not None
            and self.detail_view.workstation.workstation_id == workstation.workstation_id
        ):
            self._show_machines()
        self._persist()

    def _refresh_workstation_views(self) -> None:
        apply_reservations(self.workstations, self.reservations, self.current_user.upn)
        self.overview_view.set_workstations(self.workstations)
        self.calendar_view.set_workstations(self.workstations)
        self.admin_view.set_workstations(self.workstations)
        self._update_summary()
        if self.detail_view.workstation is not None:
            selected = next((ws for ws in self.workstations if ws.workstation_id == self.detail_view.workstation.workstation_id), None)
            if selected is not None:
                self.detail_view.set_workstation(selected)

    def _refresh_status_views(self) -> None:
        """Update live information without repainting hidden tables on each poll."""
        apply_reservations(self.workstations, self.reservations, self.current_user.upn)
        self.overview_view.set_workstations(self.workstations)
        if self.stack.currentWidget() is self.calendar_view:
            self.calendar_view.set_workstations(self.workstations)
        if self.stack.currentWidget() is self.admin_view:
            self.admin_view.set_workstations(self.workstations)
        self._update_summary()
        if self.detail_view.workstation is not None:
            selected = next(
                (ws for ws in self.workstations
                 if ws.workstation_id == self.detail_view.workstation.workstation_id),
                None,
            )
            if selected is not None:
                self.detail_view.set_workstation(selected)

    def _edit_user(self) -> None:
        dialog = UserSettingsDialog(self.current_user, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._update_user_header()
        self.settings_view.set_user(self.current_user)
        self.calendar_view.set_user(self.current_user)
        self.detail_view.set_user(self.current_user)
        if dialog.should_save:
            self._saved_user = deepcopy(self.current_user)
            self._persist()

    @Slot(Workstation)
    def _manage_rdp_access(self, workstation: Workstation) -> None:
        """Edit desired RDP group membership without handling any credentials."""
        lookup = discover_windows_domain_accounts()
        current_account = self.current_user.get_rdp_username() or self.current_user.upn
        known_accounts = self.directory_accounts + lookup.accounts + [current_account]
        dialog = RDPAccessDialog(workstation, known_accounts, lookup.message, self)
        if dialog.exec() != QDialog.Accepted:
            return
        previous = {account.casefold(): account for account in workstation.rdp_access_users}
        updated = {account.casefold(): account for account in dialog.selected_members}
        granted = [updated[key] for key in sorted(updated.keys() - previous.keys())]
        revoked = [previous[key] for key in sorted(previous.keys() - updated.keys())]
        self.directory_accounts = self.store.save_directory_accounts(dialog.known_accounts)
        if not granted and not revoked:
            if dialog.sync_to_active_directory:
                self._sync_rdp_access_to_active_directory(workstation)
            return
        workstation.rdp_access_users = dialog.selected_members
        self._commit_workstation(workstation)
        self._refresh_workstation_views()
        if not self._persist():
            return
        for account in granted:
            self._record_event(
                workstation,
                EventType.RDP_ACCESS_GRANTED,
                EventResult.SUCCESS,
                f"RDP-{workstation.workstation_id}: {account}",
                EventSource.ADMIN,
            )
        for account in revoked:
            self._record_event(
                workstation,
                EventType.RDP_ACCESS_REVOKED,
                EventResult.SUCCESS,
                f"RDP-{workstation.workstation_id}: {account}",
                EventSource.ADMIN,
            )
        if dialog.sync_to_active_directory:
            self._sync_rdp_access_to_active_directory(workstation)

    def _sync_rdp_access_to_active_directory(self, workstation: Workstation) -> None:
        """Apply the explicitly saved membership to one AD group after confirmation."""
        group_name = f"RDP-{workstation.workstation_id}"
        members = workstation.rdp_access_users
        preview = "\n".join(f"• {account}" for account in members) or "• Keine Benutzer (direkte Benutzer werden entfernt)"
        answer = QMessageBox.warning(
            self,
            "RDP-Gruppe in Active Directory übernehmen",
            f"Die direkten Benutzer der AD-Gruppe {group_name} werden auf diesen Stand gesetzt:\n\n{preview}\n\n"
            "Die Ausführung verwendet Ihr aktuell angemeldetes Windows-Konto. Fortfahren?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        result = sync_rdp_group_members(group_name, members)
        event_type = EventType.RDP_ACCESS_SYNC_COMPLETED if result.success else EventType.RDP_ACCESS_SYNC_FAILED
        self._record_event(workstation, event_type, EventResult.SUCCESS if result.success else EventResult.FAILED, result.message, EventSource.ADMIN)
        if result.success:
            QMessageBox.information(self, "RDP-Gruppe abgeglichen", result.message)
        else:
            QMessageBox.warning(self, "AD-Übernahme nicht möglich", result.message)

    def _update_user_header(self) -> None:
        if not hasattr(self, "user_button"):
            return
        self.user_button.setText(f"{self.current_user.display_name}\n{self.current_user.get_rdp_username() or 'RDP-Anmeldung festlegen'}")
        initials = "".join(part[0] for part in self.current_user.display_name.split()[:2]).upper() or "U"
        self.avatar_button.setText(initials)

    @staticmethod
    def _system_prefers_dark() -> bool:
        """Read the Windows app color preference, with a Qt fallback."""
        if sys.platform == "win32":
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                ) as key:
                    apps_use_light_theme, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return int(apps_use_light_theme) == 0
            except OSError:
                pass
        try:
            return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except AttributeError:
            return False

    def _resolve_dark_mode(self) -> bool:
        if self.theme_mode == "dark":
            return True
        if self.theme_mode == "light":
            return False
        return self._system_prefers_dark()

    @Slot(str)
    def _set_theme_mode(self, theme_mode: str) -> None:
        theme_mode = theme_mode if theme_mode in {"system", "light", "dark"} else "system"
        if self.theme_mode == theme_mode:
            return
        self.theme_mode = theme_mode
        self.dark_mode = self._resolve_dark_mode()
        self._apply_theme()
        self.settings_view.set_theme_mode(theme_mode, self.dark_mode)
        self._persist()

    def _set_dark_mode(self, dark_mode: bool) -> None:
        """Compatibility helper retained for internal callers and tests."""
        self._set_theme_mode("dark" if dark_mode else "light")

    def _apply_theme(self) -> None:
        self.setStyleSheet(scale_stylesheet(self._application_style(self.dark_mode)))
        self._update_logo()
        # Der Kalender faerbt seine Zellen selbst; ein Stylesheet erreicht
        # einzelne Tabellenfelder nicht.
        if hasattr(self, "calendar_view"):
            self.calendar_view.set_dark_mode(self.dark_mode)

    def _update_logo(self) -> None:
        if not hasattr(self, "logo_label"):
            return
        pixmap = QPixmap(str(self.logo_path))
        if pixmap.isNull():
            self.logo_label.setText("KIRSCHKE")
            return
        if self.dark_mode:
            image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(image.rect(), QColor("#ffffff"))
            painter.end()
            pixmap = QPixmap.fromImage(image)
        self.logo_label.setPixmap(
            pixmap.scaled(
                scaled(285), scaled(48), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    @Slot(list)
    def _on_reservations_changed(self, reservations: list[Reservation]) -> None:
        previous = self.reservations
        self.reservations = list(reservations)
        if not self._persist():
            self.reservations = previous
            return
        self.calendar_view.reservations = list(self.reservations)
        self._push_reservations_to_agents(previous, self.reservations)
        self._refresh_workstation_views()

    def _push_reservations_to_agents(
        self,
        previous: list[Reservation],
        current: list[Reservation],
    ) -> None:
        """Hand the changed machines' bookings to their own agents.

        This is what lets a portal on another PC see the booking at all. A
        machine that cannot be reached is reported once and not retried: the
        reservation is saved here either way, and the next portal that edits
        this machine pushes the full list again.
        """
        from portal_app.services.reservation_sync import affected_machines, push_for_machine

        changed = affected_machines(previous, current)
        if not changed:
            return
        problems = [
            message
            for ws in self.workstations
            if ws.workstation_id in changed
            and (message := push_for_machine(ws, current))
        ]
        if problems:
            QMessageBox.information(
                self,
                "Reservierung nur lokal gespeichert",
                "Die Reservierung ist gespeichert, konnte aber nicht an alle Agenten "
                "übergeben werden. Andere Portale sehen sie erst, wenn die Maschine "
                "wieder erreichbar ist.\n\n" + "\n".join(problems),
            )

    def _adopt_reported_reservations(self) -> bool:
        """Take over what the agents reported and tell the caller whether it changed."""
        from portal_app.services.reservation_sync import merge_reported

        merged, changed = merge_reported(self.reservations, self.workstations)
        if not changed:
            return False
        self.reservations = merged
        self.calendar_view.reservations = list(self.reservations)
        if self.stack.currentWidget() is self.calendar_view:
            self.calendar_view.refresh()
        return True

    @Slot()
    def _setup_event_log_directory(self) -> None:
        """Den gemeinsamen Protokollordner eintragen, nachdem er beschreibbar war.

        Geprüft wird durch einen echten Schreibversuch und nicht durch das
        Verbinden allein: Die Agentenfreigaben sind mit Leserecht eingerichtet,
        und dort *hineinzukommen* sagt noch nicht, dass man hineinschreiben
        darf. Ohne diese Prüfung fiele das erst beim ersten Ereignis auf -- also
        genau dann, wenn niemand mehr an die Einstellung denkt.
        """
        from portal_app.services.share_connection import connect_status_share
        from portal_app.ui.widgets.share_setup_dialog import ShareSetupDialog

        current = str(self.store.event_log_directory or "")
        dialog = ShareSetupDialog(
            current,
            self,
            suggested_path=current or r"\\SERVER\RDP-Protokoll",
            suggested_username="",
            workstation_name="das gemeinsame Protokoll",
            require_write=True,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        target = dialog.connected_path
        connect_status_share(target)
        try:
            stored = self.store.set_event_log_directory(target)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Protokollordner nicht gespeichert", str(exc))
            return
        self._refresh_event_log_location()
        self._reload_events()
        QMessageBox.information(
            self,
            "Gemeinsames Protokoll aktiv",
            f"Neue Ereignisse werden nach\n{stored}\ngeschrieben. Das bisherige lokale "
            "Protokoll bleibt erhalten, wird hier aber nicht mehr angezeigt.",
        )

    @Slot()
    def _setup_inventory_directory(self) -> None:
        """Das gemeinsame Inventar auf einer Netzwerkfreigabe einrichten.

        Wie beim Protokoll wird vorher wirklich geschrieben: Ohne Schreibrecht
        fiele das sonst erst beim ersten Speichern auf.
        """
        from portal_app.services.share_connection import connect_status_share
        from portal_app.ui.widgets.share_setup_dialog import ShareSetupDialog

        if self._pending_save or self._has_unsaved_machine_settings():
            QMessageBox.information(
                self,
                "Erst speichern",
                "Bitte zuerst die offenen Maschineneinstellungen speichern oder "
                "verwerfen. Sonst ginge nicht eindeutig hervor, welcher Stand auf "
                "die Freigabe kommt.",
            )
            return
        current = str(self.store.inventory_directory or "")
        dialog = ShareSetupDialog(
            current,
            self,
            suggested_path=current or r"\\SERVER\RDP-Portal",
            suggested_username="",
            workstation_name="das gemeinsame Inventar",
            require_write=True,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        target = dialog.connected_path
        connect_status_share(target)
        try:
            adopted = self.store.use_shared_inventory(target)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Gemeinsames Inventar nicht eingerichtet", str(exc))
            return
        self.on_refresh()
        QMessageBox.information(
            self,
            "Gemeinsames Inventar aktiv",
            (
                f"Auf der Freigabe lag bereits ein Inventar:\n{target}\n\nDieses gilt "
                "jetzt. Der bisherige eigene Stand bleibt unverändert auf diesem PC liegen."
                if adopted
                else f"Die eigenen Maschinen und Reservierungen liegen jetzt unter\n{target}\n\n"
                "Alle Portale, die diese Freigabe eintragen, arbeiten mit demselben Stand."
            ),
        )

    @Slot()
    def _clear_inventory_directory(self) -> None:
        """Das gemeinsame Inventar verlassen und wieder lokal führen."""
        answer = QMessageBox.question(
            self,
            "Inventar wieder lokal führen",
            "Der aktuelle gemeinsame Stand wird als eigener übernommen und ab dann "
            "nur noch auf diesem PC geführt. Änderungen anderer Portale kommen "
            "nicht mehr an.\n\nDie gemeinsame Datei auf der Freigabe bleibt "
            "unverändert erhalten.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.store.use_local_inventory()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Einstellung nicht gespeichert", str(exc))
            return
        self.on_refresh()

    @Slot()
    def _clear_event_log_directory(self) -> None:
        """Das Protokoll wieder lokal führen."""
        answer = QMessageBox.question(
            self,
            "Protokoll wieder lokal führen",
            "Neue Ereignisse werden dann wieder neben dem eigenen Stand abgelegt und "
            "nicht mehr mit den Kollegen geteilt.\n\nDie gemeinsame Datei bleibt "
            "unverändert erhalten.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.store.set_event_log_directory(None)
        except OSError as exc:
            QMessageBox.warning(self, "Einstellung nicht gespeichert", str(exc))
            return
        self._refresh_event_log_location()
        self._reload_events()

    def _refresh_event_log_location(self) -> None:
        directory = self.store.event_log_directory
        self.admin_view.set_event_log_location(
            str(directory) if directory else "", str(self.store.events_path)
        )

    def _report_session_claim(self, workstation: Workstation, account: str | None) -> None:
        """Dem Agenten melden, dass diese Person sich gerade aufschaltet.

        Der Punkt, an dem die Workstation aufhört, bei allen als "von dir
        belegt" zu erscheinen: Auf ihr meldet sich jeder unter demselben
        gemeinsamen Windows-Konto an, und ohne diese Meldung erkennt jedes
        Portal den Kontonamen als den eigenen wieder.

        Eine misslungene Meldung bleibt im Protokoll und stört sonst nicht --
        die Verbindung läuft bereits.
        """
        problem = self._claim_reporter.report(workstation, self.current_user, account)
        if problem:
            # Nicht angekommen, aber vorgemerkt: Der naechste Statuslauf
            # versucht es erneut, solange die Sitzung besteht.
            logger.info(
                "Aufschaltung für %s vorgemerkt: %s", workstation.display_name, problem
            )

    def _fresh_reservation_block_reason(self, workstation: Workstation) -> str:
        """Der aktuellste Grund, warum diese Maschine für jemand anderen gebucht ist.

        Der gemeinsame Stand wird noch einmal frisch gelesen, weil zwischen dem
        letzten Abgleich und diesem Klick jemand gebucht haben kann. Ist er
        nicht lesbar, gilt der zuletzt bekannte Stand: Eine Reservierung ist
        eine Absprache unter Kollegen, und eine unlesbare Datei ist kein Grund,
        jemanden von einer Maschine fernzuhalten.
        """
        try:
            reservations = self.store.read_reservations()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Reservierungsstand nicht lesbar: %s", exc)
            reservations = self.reservations
        probe = copy(workstation)
        apply_reservations([probe], reservations, self.current_user.upn)
        return probe.reservation_block_reason

    def _confirm_connection(self, workstation: Workstation) -> tuple[bool, str]:
        """Bei belegter oder fremd gebuchter Maschine warnen und entscheiden lassen.

        Früher wurde hier abgebrochen. Zusammen mit dem gesperrten Knopf war das
        der Zustand, aus dem niemand mehr herauskam: Wer reserviert hatte, kam
        wegen der laufenden fremden Sitzung nicht auf die Maschine, und wer
        angemeldet war, kam wegen der Reservierung nicht zurück auf seine eigene.

        Gibt zurück, ob gestartet werden darf, und welchen Reservierungsgrund
        die Person dabei gesehen hat.
        """
        from portal_app.ui.machine_actions import connection_warning

        reason = self._fresh_reservation_block_reason(workstation)
        warning = connection_warning(
            workstation, self.current_user, reservation_block_reason=reason
        )
        if warning is None:
            return True, reason
        question = QMessageBox(self)
        question.setIcon(QMessageBox.Warning)
        question.setWindowTitle(f"{workstation.display_name} ist belegt")
        question.setText(warning)
        proceed = question.addButton("Trotzdem verbinden", QMessageBox.DestructiveRole)
        cancel = question.addButton(QMessageBox.Cancel)
        # Abbrechen ist die Vorgabe: Wer hier landet, hat den Knopf gedrückt,
        # ohne die Belegung unbedingt schon gekannt zu haben.
        question.setDefaultButton(cancel)
        question.exec()
        return question.clickedButton() is proceed, reason

    def _record_event(
        self,
        workstation: Workstation,
        event_type: EventType,
        result: EventResult,
        reason: str | None = None,
        source: EventSource = EventSource.PORTAL,
    ) -> None:
        """Persist one credential-free event in the shared append-only log."""
        event = SessionEvent(
            event_id=f"EVT-{uuid.uuid4().hex}",
            timestamp_utc=datetime.now(),
            event_type=event_type,
            workstation_id=workstation.workstation_id,
            workstation_hostname=workstation.hostname or workstation.fqdn,
            session_user_upn=rdp_profile(workstation, self.current_user).username_hint,
            actor_entra_object_id=self.current_user.object_id,
            actor_upn=self.current_user.upn,
            result=result,
            reason=reason,
            source=source,
        )
        try:
            self.store.append_event(event)
        except OSError as exc:
            logger.warning("Could not write portal event: %s", exc)
            return
        self.session_events.append(event)
        self.session_log_view.add_event(event)
        if self.detail_view.workstation is workstation:
            self.detail_view.set_session_events(
                [item for item in self.session_events if item.workstation_id == workstation.workstation_id]
            )

    @Slot(Workstation)
    def on_connect_requested(self, workstation: Workstation) -> None:
        from portal_app.rdp import focus_rdp_session, has_active_rdp_session, launch_rdp_session

        if has_active_rdp_session(workstation.workstation_id):
            # Raising the window is what the user actually wanted; the old message
            # was correct and useless, because the window is usually just minimised.
            if focus_rdp_session(workstation.workstation_id):
                return
            QMessageBox.warning(
                self,
                "RDP-Start oder Fenster noch aktiv",
                f"Für {workstation.display_name} läuft noch ein RDP-Start oder ein sichtbares "
                "RDP-Fenster. Windows konnte kein Fenster in den Vordergrund holen. "
                "Prüfe auch offene Anmelde- und Fehlermeldungen. Falls kein Fenster erscheint, "
                "versuche es nach 30 Sekunden erneut; ein Prozess ohne Fenster blockiert dann nicht mehr.",
            )
            return
        # Das Konto aus "Anmelden als" gilt unverändert. Früher wurde es hier bei
        # einer fremden Sitzung still durch das Sitzungskonto ersetzt -- wer
        # sein eigenes Konto gewählt hatte, landete unter dem eines anderen.
        # Wer die laufende Sitzung übernehmen will, wählt sie im Dropdown
        # ("Angemeldet · …"); dass eine fremde Sitzung getrennt wird, sagt die
        # Warnung in _confirm_connection.
        if not workstation.enabled or workstation.is_blocked():
            # Nach der Rückfrage bleiben nur die Gründe übrig, die eine Person
            # nicht überstimmen kann: im Portal deaktiviert oder von jemandem
            # bewusst als gesperrt bzw. in Wartung gekennzeichnet.
            QMessageBox.warning(
                self,
                "Verbindung nicht möglich",
                f"{workstation.display_name} ist momentan nicht verfügbar: {workstation.get_status_display()}",
            )
            return
        proceed, confirmed_reason = self._confirm_connection(workstation)
        if not proceed:
            return
        try:
            profile = rdp_launch_profile(workstation, self.current_user)
            target, _ = profile.resolve_connection_target()
            # Auf einer freien Maschine startet ein Klick die Verbindung ohne
            # eigene Rückfrage. Die Serveridentität prüft Windows selbst und
            # warnt nur, wenn das Zertifikat nicht passt; die Ausnahme dafür
            # bleibt eine bewusste Einstellung unter "Bearbeiten". Dass das
            # Webkonto bei einer IP-Adresse entfällt, steht in der Detailansicht.
            if profile.entra_sso_enabled and not profile.effective_entra_sso_enabled():
                logger.info(
                    "Webkonto für %s entfällt, Ziel ist die IP-Adresse %s",
                    workstation.display_name,
                    target,
                )
            # Zwischen der Rückfrage und diesem Punkt können Dialoge lange offen
            # gestanden haben. Noch einmal gefragt wird nur, wenn in dieser Zeit
            # eine Buchung dazugekommen ist -- sonst wäre es zweimal dieselbe Frage.
            if self._fresh_reservation_block_reason(workstation) != confirmed_reason:
                proceed, confirmed_reason = self._confirm_connection(workstation)
                if not proceed:
                    return
            if not _saved_credentials_allow_launch(self, profile, target):
                return
            success, message = launch_rdp_session(
                profile,
                workstation.workstation_id,
                workstation.display_name,
            )
            if success:
                self._record_event(workstation, EventType.LAUNCH_REQUESTED, EventResult.SUCCESS)
                self._report_session_claim(workstation, profile.username_hint)
                # Neue Verbindung, neue Nachmeldung: _learn_reported_account
                # meldet die Aufschaltung unter der Schreibweise des Agenten
                # nach, bisher aber nur einmal pro Programmlauf. Ab der zweiten
                # Verbindung blieb die Meldung des Vorgängers an der Sitzung.
                self._reported_claims -= {
                    key for key in self._reported_claims
                    if key[0] == workstation.workstation_id
                }
                # Remember which Windows account this person connects as, so the
                # resulting session is recognised as theirs next time instead of
                # showing up as somebody else's and locking them out.
                #
                # This records the spelling the portal connects *with*. For an
                # Entra account that is the UPN, while the agent reports the
                # session under the profile name -- two forms that cannot be
                # derived from one another. _learn_reported_account closes that
                # gap once the session actually shows up.
                if self.current_user.claim_account(profile.username_hint):
                    self._saved_user = deepcopy(self.current_user)
                    self._persist()
                    self._refresh_workstation_views()
                # Keine Bestätigung: Das Remotedesktopfenster ist die Rückmeldung.
                self._poll_rdp_sessions()
            else:
                self._record_event(workstation, EventType.LAUNCH_REQUESTED, EventResult.FAILED, message)
                QMessageBox.critical(self, "Verbindung fehlgeschlagen", message)
        except Exception as exc:  # pragma: no cover - platform integration
            logger.exception("Failed to launch RDP")
            self._record_event(workstation, EventType.LAUNCH_REQUESTED, EventResult.FAILED, str(exc))
            QMessageBox.critical(self, "Fehler", f"Die Verbindung konnte nicht gestartet werden: {exc}")

    @Slot(Workstation)
    def _query_live_status(self, workstation: Workstation) -> None:
        current = next(
            (ws for ws in self.workstations if ws.workstation_id == workstation.workstation_id),
            None,
        )
        if current is None:
            return
        self._run_status_update_cycle([current], force=True)

    def _offer_console_logoff_routes(self, workstation: Workstation) -> None:
        """Offer the two ways a local console session can still be ended.

        The agent cannot authorize this directly -- a console session has no RDP
        client, so Windows can attest nothing about who is asking.  Taking the
        session over by RDP removes that obstacle rather than working around it:
        afterwards the session *is* an RDP session of this machine, and the very
        same check that refuses now will accept.
        """
        from portal_app.ui.machine_actions import CONSOLE_LOGOFF_HINT

        choice = QMessageBox(self)
        choice.setIcon(QMessageBox.Question)
        choice.setWindowTitle("Konsolensitzung abmelden")
        choice.setText(CONSOLE_LOGOFF_HINT)
        choice.setInformativeText(
            "„Übernehmen und abmelden“ verbindet dich kurz per RDP — Windows fragt "
            "dabei die Anmeldung ab — und meldet die Sitzung danach ab, sobald sie "
            "als Sitzung dieses Rechners gemeldet wird."
        )
        takeover = choice.addButton("Übernehmen und abmelden", QMessageBox.AcceptRole)
        administrative = choice.addButton("Administrativ abmelden", QMessageBox.ActionRole)
        choice.addButton(QMessageBox.Cancel)
        choice.setDefaultButton(takeover)
        choice.exec()
        clicked = choice.clickedButton()
        if clicked == takeover:
            self._takeover_then_logoff(workstation)
        elif clicked == administrative and (
            self._admin_unlocked or self._request_admin_access()
        ):
            self._admin_logoff_workstation(workstation)

    def _takeover_then_logoff(self, workstation: Workstation) -> None:
        """Connect by RDP, wait for the session to become ours, then log it off."""
        from portal_app.rdp import has_active_rdp_session
        from portal_app.ui.widgets.session_takeover_dialog import SessionTakeoverDialog

        self.on_connect_requested(workstation)
        if not has_active_rdp_session(workstation.workstation_id):
            return
        waiting = SessionTakeoverDialog(
            workstation,
            self.current_user.windows_accounts(),
            self,
        )
        taken_over = waiting.exec() == QDialog.Accepted
        waiting.deleteLater()
        self._run_status_update_cycle([workstation], force=True)
        if taken_over:
            self._logoff_session(workstation)

    @Slot(Workstation)
    def _logoff_session(self, workstation: Workstation) -> None:
        from portal_app.ui.widgets.session_logoff_dialog import SessionLogoffDialog

        if workstation.reservation_block_reason:
            QMessageBox.warning(
                self,
                "Fremde Reservierung",
                "Während einer fremden Reservierung wird keine normale Abmeldung angeboten.",
            )
            return
        from portal_app.ui.machine_actions import logoff_candidates

        owned = workstation.owned_sessions(self.current_user.windows_accounts())
        sessions = logoff_candidates(owned)
        if not sessions:
            QMessageBox.warning(self, "Keine passende Sitzung", "Wähle das Konto deiner Sitzung und warte auf eine aktuelle Agent-Meldung mit Anmeldezeitpunkt.")
            return
        sessions = [item for item in sessions if not is_console_session(item)]
        if not sessions:
            self._offer_console_logoff_routes(workstation)
            return
        if len(sessions) > 1:
            labels = [f"Sitzung {item['session_id']} · {item.get('session_state')} · {item['login_time']}" for item in sessions]
            label, accepted = QInputDialog.getItem(self, "Sitzung auswählen", "Welche Sitzung abmelden?", labels, 0, False)
            if not accepted:
                return
            session = sessions[labels.index(label)]
        else:
            session = sessions[0]
        try:
            target, _ = workstation.get_connection_target()
        except ValueError as exc:
            QMessageBox.warning(self, "Ziel fehlt", str(exc))
            return
        dialog = SessionLogoffDialog(
            target,
            workstation.display_name,
            dict(session),
            self,
            expected_agent_id=workstation.agent_workstation_id or workstation.workstation_id,
            status_target=workstation.get_agent_status_target(),
            hostnames=None if workstation.agent_workstation_id else machine_hostnames(workstation),
            claimed_accounts=self.current_user.own_accounts,
        )
        dialog.request_finished.connect(
            lambda success, _message, ws=workstation: self._own_logoff_finished(ws, success)
        )
        self._logoff_in_progress.add(workstation.workstation_id)
        try:
            dialog.exec()
        finally:
            # Auch bei Abbruch oder Fehler wieder freigeben, sonst bliebe die
            # Maschine dauerhaft von der Live-Abfrage ausgenommen.
            self._logoff_in_progress.discard(workstation.workstation_id)
        dialog.deleteLater()
        self._poll_agent_status()

    def _own_logoff_finished(self, workstation: Workstation, success: bool) -> None:
        """Release the polling pause, then refresh this machine if it worked.

        The pause is lifted here rather than only after the dialog closes: the
        agent answers again as soon as the request returns, and the refresh below
        is the one that shows the session is gone.
        """
        self._logoff_in_progress.discard(workstation.workstation_id)
        if success:
            self._run_status_update_cycle([workstation], force=True)

    @Slot(Workstation)
    def _run_rdp_diagnostics(self, workstation: Workstation) -> None:
        """Show a credential-free RDP preflight report for one workstation."""
        from portal_app.services.rdp_diagnostics import (
            clear_saved_rdp_credentials,
            run_rdp_diagnostics,
        )

        try:
            profile = rdp_profile(workstation, self.current_user)
            result = run_rdp_diagnostics(profile)
        except Exception as exc:
            logger.exception("RDP diagnostics failed")
            QMessageBox.critical(self, "RDP-Diagnose fehlgeschlagen", str(exc))
            return
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Information if result.port_open else QMessageBox.Warning)
        message.setWindowTitle("RDP-Verbindungsdiagnose")
        message.setText(
            "Der RDP-Port ist erreichbar." if result.port_open else "Der RDP-Port konnte nicht erreicht werden."
        )
        message.setInformativeText(
            f"Der vollständige, passwortfreie Report wurde gespeichert unter:\n{result.log_path}"
        )
        message.setDetailedText(result.report)
        copy_button = message.addButton("Report kopieren", QMessageBox.ActionRole)
        clear_button = None
        if result.saved_credentials_present:
            clear_button = message.addButton(
                "Gespeicherte Anmeldedaten entfernen", QMessageBox.DestructiveRole
            )
            clear_button.setObjectName("dangerButton")
        message.addButton(QMessageBox.Ok)
        message.exec()
        if message.clickedButton() == copy_button:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(result.report)
        elif message.clickedButton() == clear_button:
            answer = QMessageBox.warning(
                self,
                "Gespeicherte RDP-Anmeldedaten entfernen",
                f"Der gespeicherte Windows-Eintrag für {result.target} wird entfernt.\n\n"
                "Das Kennwort bleibt unbekannt; beim nächsten RDP-Start fragt Windows erneut nach den Anmeldedaten.\n\n"
                "Eintrag wirklich entfernen?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return
            success, detail = clear_saved_rdp_credentials(result.target)
            if success:
                QMessageBox.information(self, "RDP-Anmeldedaten entfernt", detail)
            else:
                QMessageBox.warning(self, "Entfernen fehlgeschlagen", detail)

    def on_refresh(self) -> None:
        try:
            loaded = self.store.load(self.workstations, self.current_user)
        except OSError as exc:
            self._update_storage_status(f"Aktualisierung fehlgeschlagen: {exc}")
            logger.warning("Could not refresh portal storage: %s", exc)
            return
        self.workstations, self.current_user, self.reservations = loaded
        self._apply_local_agent_fallbacks()
        self._pending_save = False
        self._poll_agent_status()
        self.session_events = self.store.load_events()
        self.directory_accounts = self.store.load_directory_accounts()
        self.theme_mode = self.store.theme_mode
        self.dark_mode = self._resolve_dark_mode()
        self._saved_workstations = deepcopy(self.workstations)
        self._saved_user = deepcopy(self.current_user)
        self.calendar_view.reservations = list(self.reservations)
        self.session_log_view.set_events(self.session_events)
        self.admin_view.set_storage_directory(
            str(self.store.directory), self.store.uses_shared_inventory
        )
        self._update_storage_status("Gemeinsame Änderungen übernommen")
        self.calendar_view.set_user(self.current_user)
        self.settings_view.set_user(self.current_user)
        self.settings_view.set_theme_mode(self.theme_mode, self.dark_mode)
        self.settings_view.set_status_refresh_interval(
            self.store.status_refresh_interval
        )
        self.overview_view.set_machine_order(self.store.machine_order)
        self.overview_view.set_favorites(self.store.favorite_workstations)
        self.overview_view.set_preferred_accounts(self.store.preferred_login_accounts)
        self.overview_view.set_machine_view(self.store.machine_view)
        self.agent_poll_timer.setInterval(self.store.status_refresh_interval * 1000)
        self.live_status_poller.set_interval(self.store.status_refresh_interval)
        self.detail_view.set_user(self.current_user)
        self._update_user_header()
        self._apply_theme()
        self._refresh_workstation_views()
        if self.detail_view.workstation is not None:
            selected_id = self.detail_view.workstation.workstation_id
            selected = next((ws for ws in self.workstations if ws.workstation_id == selected_id), None)
            if selected is not None:
                self.detail_view.set_workstation(selected)
            else:
                self._show_machines()

    def _sync_shared_store(self, *, blocking: bool = True) -> None:
        """Nachladen, nachdem ein anderes Portal das gemeinsame Inventar geändert hat.

        Ein gemeinsames Ereignisprotokoll wächst ständig -- jeder Kollege
        schreibt hinein. Das allein darf keinen vollständigen Neuaufbau des
        Inventars auslösen; es genügt, die neuen Einträge nachzuladen.

        Der Takt übergibt ``blocking=False``: Die Signaturen werden dann im
        Hintergrund ermittelt, weil schon ein ``stat`` auf einer Freigabe hängen
        kann. Ein direkter Aufruf prüft sofort.
        """
        if self._pending_save or self._has_unsaved_machine_settings():
            return
        paths = self.store.change_probe_paths()
        if not blocking:
            self.store_probe.request(paths)
            return
        self._on_store_probe(paths, file_signatures(paths))

    @Slot(object, object)
    def _on_store_probe(
        self,
        paths: tuple[Path, Path, Path],
        signatures: tuple[tuple[int, int] | None, ...],
    ) -> None:
        if self._pending_save or self._has_unsaved_machine_settings():
            return
        inventory_changed, events_changed = self.store.changes_from(paths, signatures)
        if inventory_changed:
            self.on_refresh()
            return
        if events_changed:
            self._reload_events()

    def _reload_events(self) -> None:
        """Nur das Ereignisprotokoll neu einlesen und anzeigen."""
        try:
            self.session_events = self.store.load_events()
        except OSError as exc:
            logger.warning("Ereignisprotokoll nicht lesbar: %s", exc)
            return
        self.session_log_view.set_events(self.session_events)
        if self.detail_view.workstation is not None:
            selected = self.detail_view.workstation.workstation_id
            self.detail_view.set_session_events(
                [item for item in self.session_events if item.workstation_id == selected]
            )

    def _persist(self) -> bool:
        try:
            self.store.save(
                self._saved_workstations,
                self._saved_user,
                self.reservations,
                theme_mode=self.theme_mode,
            )
            self._update_storage_status("Gemeinsamer Stand gespeichert")
            self._pending_save = False
            return True
        except StoreConflictError as exc:
            QMessageBox.warning(
                self,
                "Paralleländerung erkannt",
                f"Die gemeinsame Konfiguration wurde auf einem anderen Portal geändert.\n\n{exc}",
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Speichern fehlgeschlagen", f"Die Portaldaten konnten nicht gespeichert werden: {exc}")
        self._update_storage_status("Änderungen NICHT gespeichert – bitte erneut speichern oder aktualisieren")
        self._pending_save = True
        return False

    def _update_storage_status(self, action: str) -> None:
        """Zeigen, wo der Stand liegt und mit wem er geteilt wird."""
        if not hasattr(self, "admin_view"):
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        from shared.agent_paths import is_private_program_location

        # Drei ehrliche Fälle statt zwei. Der mittlere sagt "wenn" und nicht
        # "wird": Ob ein Ordner tatsächlich synchronisiert wird, kann das
        # Portal nicht wissen, und eine Zusage, die es nicht halten kann, hat
        # hier schon einmal jemanden auf eine Verteilung warten lassen, die nie
        # kam. Siehe shared.agent_paths.is_private_program_location.
        inventory = self.store.inventory_directory
        if self.store.uses_shared_inventory:
            location = (
                "Gemeinsames Inventar auf der Netzwerkfreigabe · alle Portale mit "
                "diesem Eintrag sehen dieselben Maschinen und Reservierungen"
            )
        elif inventory is not None:
            location = (
                f"NOTBETRIEB · Das gemeinsame Inventar {inventory} ist nicht "
                "erreichbar. Änderungen hier werden nicht geteilt."
            )
        elif is_private_program_location(self.store.directory):
            location = (
                "Lokale Installation · Maschinen und Protokoll gelten nur für dich auf "
                "diesem PC. Reservierungen und Aufschaltungen laufen über die Agenten "
                "und bleiben gemeinsam."
            )
        elif str(self.store.directory).startswith("\\\\"):
            location = "Netzwerkpfad · gemeinsam für alle, die die Portal-EXE von dort starten"
        else:
            location = "Eigener Stand auf diesem PC · nicht geteilt"
        self.admin_view.set_storage_status(
            f"{action} · {timestamp}\n{self.store.directory}\n{location}"
        )

    def _commit_workstation(self, workstation: Workstation) -> None:
        """Update only the explicitly saved machine in the persistent snapshot."""
        saved = deepcopy(workstation)
        for index, existing in enumerate(self._saved_workstations):
            if existing.workstation_id == workstation.workstation_id:
                self._saved_workstations[index] = saved
                return
        self._saved_workstations.append(saved)

    def _update_summary(self) -> None:
        online = sum(ws.agent_status.value == "online" for ws in self.workstations)
        occupied = sum(ws.has_active_session() for ws in self.workstations)
        self.summary.setText(f"{online} online · {occupied} belegt · {len(self.workstations)} Maschinen")

    def closeEvent(self, event) -> None:  # noqa: N802
        from portal_app.rdp import cleanup_rdp_files, get_active_rdp_sessions

        active = get_active_rdp_sessions()
        if active:
            machine_names = ", ".join(sorted({session.display_name for session in active}))
            answer = QMessageBox.question(
                self,
                "RDP-Verbindung noch aktiv",
                f"Es läuft noch mindestens ein RDP-Fenster für {machine_names}.\n\n"
                "Das Portal beendet diese Verbindung beim Schließen nicht. Auch die entfernte "
                "Windows-Sitzung kann angemeldet bleiben. Portal trotzdem schließen?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return

        self.rdp_poll_timer.stop()
        self.agent_poll_timer.stop()
        self.live_status_poller.stop()
        self.fallback_scanner.stop()
        self._claim_reporter.stop()
        self.store_probe.stop()
        # Its pool waits for a running reconnect on destruction, so a slow SMB
        # host would otherwise hold the closing portal open with no window left.
        self.share_reconnector.stop()
        cleanup_rdp_files()
        event.accept()

    @staticmethod
    def _application_style(dark_mode: bool = False) -> str:
        light_style = """
            QMainWindow, QWidget#appBackground { background: #eef1f3; color: #17212b; }
            QFrame#appShell { background: #ffffff; border: 1px solid #d9e0e5; border-radius: 14px; }
            QWidget#header { background: #ffffff; border-top-left-radius: 14px; border-top-right-radius: 14px; }
            QLabel#brandLogo { background: transparent; }
            QLabel#productName { color: #526876; border-left: 1px solid #ccd5dc; padding-left: 14px; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }
            QPushButton#userButton { background: transparent; color: #1f3444; border: none; text-align: right; padding: 4px 8px; font-weight: 600; }
            QPushButton#userButton:hover { color: #315e80; background: #eef4f8; border-radius: 7px; }
            QPushButton#avatarButton { background: #e8f0f6; color: #3c6687; border: none; border-radius: 21px; font-weight: 700; }
            QPushButton#avatarButton:hover { background: #d9e8f2; }
            QPushButton#themeButton { background: #ffffff; color: #315e80; border: 1px solid #c8d4dc; border-radius: 8px; padding: 8px 12px; font-weight: 600; }
            QPushButton#themeButton:hover { background: #eef4f8; border-color: #7899af; }
            QWidget#navigation { background: #f8fafb; border-top: 1px solid #e3e8ec; border-bottom: 1px solid #dce3e8; }
            QPushButton#navButton { background: transparent; color: #425c70; border: none; border-bottom: 3px solid transparent; padding: 10px 18px 8px 18px; font-weight: 600; }
            QPushButton#navButton:hover { color: #315e80; background: #eef4f8; }
            QPushButton#navButton:checked { color: #315e80; border-bottom-color: #567f9e; }
            QWidget#content { background: #f7f9fa; }
            QLabel#eyebrow { color: #62839a; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }
            QLabel#pageTitle { color: #17232d; }
            QLabel#pageSubtitle { color: #516170; font-size: 9pt; }
            QLabel#summaryBadge { background: #e8f1eb; color: #3d6f4d; border: 1px solid #cfe0d3; border-radius: 14px; padding: 6px 12px; font-weight: 600; font-size: 8pt; }
            QFrame#sessionWarning { background: #fff7e6; border: 1px solid #e4c47d; border-radius: 9px; }
            QLabel#sessionWarningIcon { background: #d89a28; color: #ffffff; border: none; border-radius: 14px; font-size: 12pt; font-weight: 800; }
            QLabel#sessionWarningTitle { color: #684a12; border: none; font-weight: 700; }
            QLabel#sessionWarningText { color: #7a5d26; border: none; font-size: 8pt; }
            QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QSpinBox, QTextEdit, QPlainTextEdit {
                background: #ffffff;
                color: #17212b;
                border: 1px solid #b9c7d0;
                border-radius: 7px;
                padding: 7px 10px;
                selection-background-color: #4f7897;
                selection-color: #ffffff;
            }
            QComboBox:hover, QDateEdit:hover, QDateTimeEdit:hover { border-color: #6d91aa; }
            QComboBox::drop-down, QDateEdit::drop-down, QDateTimeEdit::drop-down { border: none; width: 28px; }
            QComboBox QAbstractItemView, QDateEdit QAbstractItemView, QDateTimeEdit QAbstractItemView {
                background: #ffffff;
                color: #17212b;
                border: 1px solid #9fb2bf;
                selection-background-color: #dceaf3;
                selection-color: #17212b;
            }
            QLineEdit#dashboardSearch, QComboBox#dashboardFilter { background: #ffffff; color: #17212b; border: 1px solid #b9c7d0; border-radius: 8px; padding: 10px 13px; min-height: 20px; }
            QLineEdit#dashboardSearch { padding: 7px 10px; }
            QLineEdit#dashboardSearch:focus, QComboBox#dashboardFilter:focus { border-color: #5e87a5; }
            QFrame#pingTool { background: #ffffff; border: 1px solid #d5dde3; border-radius: 9px; }
            QLabel#pingTitle { color: #334d60; font-weight: 700; }
            QLineEdit#pingInput { background: #f8fafb; color: #283641; border: 1px solid #ccd6dd; border-radius: 6px; padding: 7px 10px; }
            QLineEdit#pingInput:focus { background: #ffffff; border-color: #5e87a5; }
            QLabel#pingResult { color: #73828d; font-size: 8pt; }
            QLabel#pingResult[pingOk="true"] { color: #39704a; font-weight: 700; }
            QLabel#pingResult[pingOk="false"] { color: #9b4144; font-weight: 700; }
            QPushButton#toolbarButton { background: #ffffff; color: #385d77; border: 1px solid #c8d4dc; border-radius: 8px; padding: 9px 14px; font-weight: 600; }
            QPushButton#toolbarButton:hover { background: #eef4f8; border-color: #7899af; }
            QPushButton#toolbarButton:checked, QPushButton#viewSwitchButton:checked { background: #dceaf3; color: #183d55; border-color: #5e87a5; }
            QPushButton#viewSwitchButton { background: #ffffff; color: #385d77; border: 1px solid #c8d4dc; border-radius: 8px; padding: 7px 12px; min-width: 22px; font-size: 13pt; }
            QPushButton#viewSwitchButton:hover, QPushButton#favoriteButton:hover { border-color: #7899af; background: #eef4f8; }
            QPushButton#favoriteButton { background: transparent; color: #385d77; border: 1px solid transparent; border-radius: 7px; font-size: 17pt; }
            QPushButton#favoriteButton:checked { color: #8b5a00; }
            QPushButton#favoriteButton:focus, QPushButton#viewSwitchButton:focus { border: 2px solid #385d77; }
            QPushButton#cardPrimaryButton { background: #4f7897; color: #ffffff; border: 1px solid #4f7897; border-radius: 7px; padding: 9px 14px; font-weight: 600; }
            QPushButton#cardPrimaryButton:hover { background: #416985; }
            QPushButton#cardPrimaryButton:disabled { background: #e8ecef; color: #87939c; border-color: #d8dfe4; }
            QPushButton#dangerButton { background: #fff4f3; color: #953f43; border: 1px solid #e0b6b8; border-radius: 7px; padding: 8px 12px; }
            QScrollArea#machineScroll, QWidget#gridHost, QScrollArea#detailScroll, QWidget#detailContent { background: transparent; }
            QScrollArea#settingsScroll, QWidget#settingsContent, QScrollArea#adminScroll, QWidget#adminContent { background: transparent; }
            QScrollBar:vertical { background: transparent; width: 12px; margin: 4px 0; }
            QScrollBar::handle:vertical { background: #9db0bd; border-radius: 5px; min-height: 36px; }
            QScrollBar::handle:vertical:hover { background: #6f8b9e; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QFrame#workstationCard { background: #ffffff; border: 1px solid #d5dde3; border-radius: 11px; }
            QFrame#workstationListRow { background: #ffffff; border: 1px solid #d5dde3; border-radius: 9px; }
            QFrame#workstationListRow:hover { border-color: #7799b0; }
            QFrame#workstationCard:hover { border: 1px solid #7799b0; background: #fbfdfe; }
            QLabel#cardTitle { color: #1d2b36; }
            QLabel#cardStatus { color: #344652; font-size: 9pt; font-weight: 600; }
            QLabel#cardMeta { color: #526572; font-size: 8pt; }
            /* Der Griff zum Verschieben: zurueckhaltend, bis der Zeiger darauf steht. */
            QLabel#cardDragHandle { color: #aab8c2; font-size: 10pt; letter-spacing: 2px; }
            QLabel#cardDragHandle:hover { color: #4f7897; }
            QPushButton#cardSecondaryButton { background: #ffffff; color: #526673; border: 1px solid #d3dbe1; border-radius: 7px; padding: 8px 12px; }
            QPushButton#cardSecondaryButton:hover { background: #f1f5f7; }
            QFrame#detailCard { background: #ffffff; border: 1px solid #d8e0e5; border-radius: 10px; }
            QPlainTextEdit#networkOutput { background: #18232c; color: #dce7ee; border: 1px solid #31434f; border-radius: 7px; padding: 10px; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 8pt; selection-background-color: #4f7897; }
            QLabel#detailCardTitle { color: #263844; font-size: 11pt; font-weight: 700; }
            QLabel#detailLabel { color: #536774; font-size: 8pt; }
            QLabel#detailValue { color: #263844; font-weight: 600; }
            QLabel#detailMuted { color: #536774; font-size: 8pt; }
            QLabel#detailMuted[pingOk="true"] { color: #39704a; font-weight: 700; }
            QLabel#detailMuted[pingOk="false"] { color: #9b4144; font-weight: 700; }
            QFrame#detailDivider { color: #e2e7ea; }
            QLabel#dialogTitle { color: #20323f; font-size: 13pt; font-weight: 700; }
            QLabel#dialogNote { color: #536774; font-size: 8pt; }
            QLabel#dialogFormLabel { color: #263844; font-weight: 600; }
            QLabel#dialogWarning { color: #825b1a; font-weight: 600; }
            QLabel#calendarRange { color: #38566c; font-weight: 600; }
            QLabel#adminAccessStatus { background: #eef1f3; color: #6f7d87; border-radius: 11px; padding: 5px 9px; font-size: 8pt; font-weight: 600; }
            QLabel#adminAccessStatus[unlocked="true"] { background: #e4f0e7; color: #39704a; }
            QLabel#logTitle { color: #20323f; font-size: 13pt; font-weight: 700; }
            QFrame#filterBar { background: #eef3f6; border: 1px solid #cad6de; border-radius: 8px; }
            QTableWidget#calendarTable::item { padding: 6px; }
            QTableView, QTableWidget { background: #ffffff; color: #17212b; alternate-background-color: #f8fafb; border: 1px solid #d6dfe5; border-radius: 8px; gridline-color: #e6ebee; selection-background-color: #dceaf3; selection-color: #1e3545; }
            QTableCornerButton::section { background: #e8eff3; border: 1px solid #cbd7df; }
            QHeaderView::section { background: #e8eff3; color: #365466; border: none; border-bottom: 1px solid #cbd7df; padding: 9px 10px; font-weight: 600; }
            QCheckBox { color: #263844; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #9db4c2; background: #ffffff; border-radius: 3px; }
            QCheckBox::indicator:checked { background: #4a7f9f; border-color: #35607a; }
            QCheckBox::indicator:disabled { background: #eef2f5; border-color: #cbd7df; }
            QDialog { background: #f7f9fa; }
            QDialog QLabel, QDialog QCheckBox, QDialog QRadioButton, QDialog QGroupBox {
                color: #263844;
            }
            QMessageBox { background: #f7f9fa; color: #17212b; }
            QMessageBox QLabel { color: #17212b; }
            QMessageBox QPushButton, QDialogButtonBox QPushButton {
                background: #ffffff;
                color: #263f52;
                border: 1px solid #aebfca;
                border-radius: 7px;
                font-size: 9pt;
                min-height: 22px;
                padding: 7px 16px;
                min-width: 82px;
                font-weight: 600;
            }
            QMessageBox QPushButton:hover, QDialogButtonBox QPushButton:hover { background: #edf4f8; border-color: #6389a4; }
            QMessageBox QPushButton:default, QDialogButtonBox QPushButton:default { background: #4f7897; color: #ffffff; border-color: #4f7897; }
            QMessageBox QPushButton:default:hover, QDialogButtonBox QPushButton:default:hover { background: #416985; border-color: #416985; }
            QDialog QLineEdit, QDialog QComboBox, QDialog QDateEdit, QDialog QDateTimeEdit,
            QDialog QSpinBox, QDialog QTextEdit, QDialog QPlainTextEdit {
                background: #ffffff;
                color: #17212b;
                font-size: 9pt;
                min-height: 22px;
                placeholder-text-color: #7a8994;
                border: 1px solid #cbd6dd;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QDialog QLineEdit:read-only, QDialog QLineEdit:disabled {
                background: #eef2f4;
                color: #5e6d77;
            }
            QDialog QTabWidget::pane { background: #ffffff; border: 1px solid #d4dde3; border-radius: 7px; }
            QDialog QTabBar::tab { background: #eaf0f3; padding: 9px 16px; border: 1px solid #d4dde3; }
            QDialog QTabBar::tab:selected { background: #ffffff; color: #315e80; }
            QDialog QListWidget { background: #ffffff; color: #17212b; border: 1px solid #cbd6dd; border-radius: 7px; selection-background-color: #d9e8f1; selection-color: #17212b; }
            QDialog QListWidget::item { padding: 6px 9px; }
            QDialog QListWidget::item:hover { background: #edf4f8; }
            QDialog QListWidget::indicator { width: 14px; height: 14px; border: 1px solid #7f96a6; border-radius: 3px; background: #ffffff; margin-right: 6px; }
            QDialog QListWidget::indicator:checked { background: #4f7897; border-color: #37627f; }
            QDialog QListWidget::indicator:hover { border-color: #4f7897; }
            QWizard#machineRegistrationWizard, QWizard#machineRegistrationWizard > QWidget,
            QWizard#machineRegistrationWizard QFrame, QWizardPage#machineWizardPage { background: #f7f9fa; color: #263844; }
            QWizard QLabel, QWizard QCheckBox, QWizard QRadioButton { color: #263844; }
            QWizard QLineEdit { background: #ffffff; color: #17212b; font-size: 9pt; min-height: 22px; placeholder-text-color: #7a8994; border: 1px solid #aebfca; border-radius: 6px; padding: 6px 10px; }
            QWizard QPushButton { background: #ffffff; color: #263f52; font-size: 9pt; min-height: 22px; border: 1px solid #aebfca; border-radius: 6px; padding: 7px 13px; min-width: 82px; font-weight: 600; }
            QWizard QPushButton:hover { background: #edf4f8; border-color: #6389a4; }
            QWizard QPushButton:default { background: #4f7897; color: #ffffff; border-color: #4f7897; }
            QWizard QPushButton:disabled { background: #edf1f3; color: #8a99a3; border-color: #d3dce1; }
            QWizard QComboBox { background: #ffffff; color: #17212b; font-size: 9pt; min-height: 22px; border: 1px solid #aebfca; border-radius: 6px; padding: 5px 9px; }
            QWizard QComboBox QAbstractItemView { background: #ffffff; color: #17212b; selection-background-color: #4f7897; selection-color: #ffffff; border: 1px solid #aebfca; }
            QWizard QListWidget, QWizard QTableWidget { background: #ffffff; color: #17212b; border: 1px solid #aebfca; border-radius: 6px; }
            QWizard QListWidget::item { padding: 5px 4px; }
            QWizard QListWidget::indicator { width: 14px; height: 14px; border: 1px solid #7f96a6; border-radius: 3px; background: #ffffff; margin-right: 4px; }
            QWizard QListWidget::indicator:checked { background: #4f7897; border-color: #37627f; }
            QWizard QListWidget::indicator:hover { border-color: #4f7897; }
            QWizard QListWidget::item:hover, QWizard QTableWidget::item:hover { background: #edf4f8; }
            QWizard QHeaderView::section { background: #edf1f3; color: #3c5567; border: 0; border-bottom: 1px solid #aebfca; padding: 6px 8px; font-weight: 600; }
            QWizard QProgressBar { background: #edf1f3; color: #263844; border: 1px solid #aebfca; border-radius: 6px; min-height: 18px; text-align: center; }
            QWizard QProgressBar::chunk { background: #4f7897; border-radius: 5px; }
        """
        if not dark_mode:
            return light_style
        return light_style + """
            QMainWindow, QWidget#appBackground { background: #101820; color: #edf3f8; }
            QWidget#content { background: #15212b; }
            QFrame#appShell, QWidget#header { background: #192833; border-color: #36505f; }
            QWidget#navigation { background: #1d2d38; border-color: #3b5565; }
            QLabel#productName { color: #a9c2d2; border-left-color: #486172; }
            QPushButton#themeButton { background: #263c4c; color: #f4f8fb; border: 1px solid #537386; border-radius: 8px; padding: 8px 12px; font-weight: 600; }
            QPushButton#themeButton:hover { background: #304b5e; border-color: #83abc2; }
            QPushButton#userButton { color: #f4f8fb; }
            QPushButton#userButton:hover { color: #ffffff; background: #293e4e; }
            QPushButton#avatarButton { background: #29495f; color: #e8f4fb; }
            QPushButton#avatarButton:hover { background: #35617d; }
            QPushButton#navButton { color: #c4d5e0; }
            QPushButton#navButton:hover { color: #ffffff; background: #293e4e; }
            QPushButton#navButton:checked { color: #ffffff; border-bottom-color: #79abc9; }
            QLabel#eyebrow { color: #9fc5db; }
            QLabel#pageTitle { color: #f4f8fb; }
            QLabel#pageSubtitle { color: #b8c8d3; }
            QLabel#summaryBadge { background: #1d473c; color: #c4f0d1; border-color: #3c7861; }
            QFrame#sessionWarning { background: #413516; border-color: #a98438; }
            QLabel#sessionWarningTitle { color: #ffdf9b; }
            QLabel#sessionWarningText { color: #f4d59a; }
            QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QSpinBox, QPlainTextEdit, QTextEdit { background: #1a2a35; color: #f1f6fa; border-color: #4c697a; selection-background-color: #4f7897; selection-color: #ffffff; }
            QLineEdit#dashboardSearch, QComboBox#dashboardFilter, QLineEdit#pingInput { background: #1a2a35; color: #f1f6fa; border-color: #4c697a; }
            QLineEdit#dashboardSearch:focus, QLineEdit#pingInput:focus { background: #1a2a35; color: #f1f6fa; border-color: #8fc1dd; }
            QComboBox QAbstractItemView, QDateEdit QAbstractItemView, QDateTimeEdit QAbstractItemView { background: #1c2d38; color: #f1f6fa; border-color: #59788b; selection-background-color: #3a6884; selection-color: #ffffff; }
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDateTimeEdit:focus, QTextEdit:focus { border-color: #8fc1dd; }
            QFrame#pingTool, QFrame#workstationCard, QFrame#workstationListRow, QFrame#detailCard { background: #1c2d38; border-color: #3d5868; }
            QFrame#workstationCard:hover { background: #213642; border-color: #79a6bf; }
            QFrame#workstationListRow:hover { background: #213642; border-color: #79a6bf; }
            QLabel#pingTitle, QLabel#cardTitle, QLabel#cardStatus, QLabel#detailCardTitle, QLabel#detailValue, QLabel#dialogTitle { color: #f3f7fa; }
            QLabel#logTitle, QLabel#dialogFormLabel { color: #f3f7fa; }
            QLabel#pingResult, QLabel#cardMeta, QLabel#detailLabel, QLabel#detailMuted, QLabel#dialogNote, QLabel#calendarRange { color: #b9cad5; }
            QLabel#cardDragHandle { color: #5d7382; }
            QLabel#cardDragHandle:hover { color: #9fc4db; }
            QLabel#dialogWarning { color: #ffda89; font-weight: 600; }
            QLabel#adminAccessStatus { background: #2b3b46; color: #d3dee5; }
            QLabel#adminAccessStatus[unlocked="true"] { background: #1c4b3a; color: #c4f0d1; }
            QPushButton#toolbarButton, QPushButton#cardSecondaryButton { background: #223743; color: #eaf3f8; border-color: #527082; }
            QPushButton#toolbarButton:hover, QPushButton#cardSecondaryButton:hover { background: #2d4758; border-color: #86b0c8; }
            QPushButton#viewSwitchButton { background: #223743; color: #eaf3f8; border-color: #527082; }
            QPushButton#viewSwitchButton:checked, QPushButton#toolbarButton:checked { background: #3a6884; color: #ffffff; border-color: #8fc1dd; }
            QPushButton#favoriteButton { color: #c7d6df; }
            QPushButton#favoriteButton:checked { color: #ffcf70; }
            QPushButton#favoriteButton:focus, QPushButton#viewSwitchButton:focus { border-color: #8fc1dd; }
            QPushButton#cardPrimaryButton { background: #477896; border-color: #477896; color: #ffffff; }
            QPushButton#cardPrimaryButton:hover { background: #5c91b1; border-color: #5c91b1; }
            QPushButton#dangerButton { background: #482a30; color: #ffd7d9; border-color: #9d6268; }
            QPushButton#dangerButton:hover { background: #60343b; border-color: #d1878c; }
            QTableView, QTableWidget { background: #1a2a35; color: #f0f5f8; alternate-background-color: #203440; border-color: #456172; gridline-color: #35505f; selection-background-color: #3a6884; selection-color: #ffffff; }
            QTableCornerButton::section { background: #263b48; border: 1px solid #456172; }
            QDialog QListWidget { background: #1a2a35; color: #f0f5f8; border: 1px solid #456172; border-radius: 7px; selection-background-color: #3a6884; selection-color: #ffffff; }
            QDialog QListWidget::item { padding: 6px 9px; }
            QDialog QListWidget::item:hover { background: #263f4e; }
            QDialog QListWidget::indicator { width: 14px; height: 14px; border: 1px solid #8fa6b5; border-radius: 3px; background: #22343f; margin-right: 6px; }
            QDialog QListWidget::indicator:checked { background: #5b91b1; border-color: #9ac3da; }
            QDialog QListWidget::indicator:hover { border-color: #9ac3da; }
            QScrollBar::handle:vertical { background: #557386; }
            QScrollBar::handle:vertical:hover { background: #83abc2; }
            QFrame#filterBar { background: #1c2d38; border: 1px solid #3d5868; border-radius: 8px; }
            QHeaderView::section { background: #263b48; color: #edf4f8; border-bottom-color: #456172; }
            QTableWidget#calendarTable::item { color: #eef4f8; }
            QDialog, QMessageBox { background: #192833; color: #edf3f8; }
            QDialog QLabel, QDialog QCheckBox, QDialog QRadioButton, QDialog QGroupBox {
                color: #e7f0f5;
            }
            QMessageBox QLabel { color: #edf3f8; }
            QMessageBox QPushButton, QDialogButtonBox QPushButton { background: #263d4b; color: #f3f8fb; font-size: 9pt; min-height: 22px; border-color: #628196; }
            QMessageBox QPushButton:hover, QDialogButtonBox QPushButton:hover { background: #315164; border-color: #9ac3da; }
            QMessageBox QPushButton:default, QDialogButtonBox QPushButton:default { background: #5b91b1; color: #ffffff; border-color: #8cc0db; }
            QMessageBox QPushButton:default:hover, QDialogButtonBox QPushButton:default:hover { background: #6ca6c7; border-color: #b5d9ea; }
            QDialog QLineEdit, QDialog QComboBox, QDialog QDateEdit, QDialog QDateTimeEdit,
            QDialog QSpinBox, QDialog QTextEdit, QDialog QPlainTextEdit {
                background: #1a2a35;
                color: #f1f6fa;
                font-size: 9pt;
                min-height: 22px;
                placeholder-text-color: #8fa6b5;
                border-color: #557386;
                selection-background-color: #4f7897;
                selection-color: #ffffff;
                padding: 6px 10px;
            }
            QDialog QLineEdit:read-only, QDialog QLineEdit:disabled {
                background: #22343f;
                color: #aebfca;
                border-color: #456172;
            }
            QDialog QTabWidget::pane { background: #1a2a35; border-color: #456172; }
            QDialog QTabBar::tab { background: #263b48; color: #c8d8e2; border-color: #456172; }
            QDialog QTabBar::tab:selected { background: #1a2a35; color: #ffffff; }
            QWizard#machineRegistrationWizard, QWizard#machineRegistrationWizard > QWidget,
            QWizard#machineRegistrationWizard QFrame, QWizardPage#machineWizardPage { background: #192833; color: #e7f0f5; }
            QWizard QLabel, QWizard QCheckBox, QWizard QRadioButton { color: #e7f0f5; }
            QWizard QLineEdit { background: #1a2a35; color: #f1f6fa; font-size: 9pt; min-height: 22px; placeholder-text-color: #8fa6b5; border: 1px solid #557386; border-radius: 6px; padding: 6px 10px; }
            QWizard QLineEdit:disabled { background: #22343f; color: #aebfca; border-color: #456172; }
            QWizard QPushButton { background: #263d4b; color: #f3f8fb; font-size: 9pt; min-height: 22px; border: 1px solid #628196; border-radius: 6px; padding: 7px 13px; min-width: 82px; font-weight: 600; }
            QWizard QPushButton:hover { background: #315164; border-color: #9ac3da; }
            QWizard QPushButton:default { background: #5b91b1; color: #ffffff; border-color: #8cc0db; }
            QWizard QPushButton:disabled { background: #22343f; color: #8095a3; border-color: #3d5868; }
            QWizard QComboBox { background: #1a2a35; color: #f1f6fa; font-size: 9pt; min-height: 22px; border: 1px solid #557386; border-radius: 6px; padding: 5px 9px; }
            QWizard QComboBox QAbstractItemView { background: #1a2a35; color: #f1f6fa; selection-background-color: #5b91b1; selection-color: #ffffff; border: 1px solid #557386; }
            QWizard QListWidget, QWizard QTableWidget { background: #1a2a35; color: #f1f6fa; border: 1px solid #557386; border-radius: 6px; }
            QWizard QListWidget::item { padding: 5px 4px; }
            QWizard QListWidget::indicator { width: 14px; height: 14px; border: 1px solid #8fa6b5; border-radius: 3px; background: #22343f; margin-right: 4px; }
            QWizard QListWidget::indicator:checked { background: #5b91b1; border-color: #9ac3da; }
            QWizard QListWidget::indicator:hover { border-color: #9ac3da; }
            QWizard QListWidget::item:hover, QWizard QTableWidget::item:hover { background: #274050; }
            QWizard QHeaderView::section { background: #22343f; color: #cfe0ea; border: 0; border-bottom: 1px solid #557386; padding: 6px 8px; font-weight: 600; }
            QWizard QProgressBar { background: #22343f; color: #e7f0f5; border: 1px solid #557386; border-radius: 6px; min-height: 18px; text-align: center; }
            QWizard QProgressBar::chunk { background: #5b91b1; border-radius: 5px; }
            QCheckBox { color: #e7f0f5; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #789bae; background: #1a2a35; border-radius: 3px; }
            QCheckBox::indicator:checked { background: #5f96b8; border-color: #8fc1dd; }
            QCheckBox::indicator:disabled { background: #22343f; border-color: #3d5868; }
            QToolTip { background: #101820; color: #f3f7fa; border: 1px solid #5b788a; }
        """


__all__ = ["MainWindow"]
