"""PowerShell-independent Windows setup for the packaged workstation agent."""

from __future__ import annotations

import ctypes
import json
import ntpath
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import winreg
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
from xml.sax.saxutils import escape

import ntsecuritycon
import pywintypes
import win32net
import win32netcon
import win32security

from shared.version import AGENT_VERSION  # noqa: E402 - single source of truth

TASK_NAME = "Kirschke RDP Agent - Machine"
INSTALL_FOLDER = "KirschkeRDPAgent"
AGENT_EXE = "Kirschke-RDP-Agent.exe"
SETUP_EXE = "Kirschke-RDP-Agent-Setup.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\KirschkeRDPAgent"
READER_NAME = "PortalLeser"
SHARE_NAME = "RDP-Status"
#: Freigabe fuer das gemeinsame Ereignisprotokoll. Eine pro Testbetrieb genuegt;
#: sie liegt auf irgendeiner erreichbaren Maschine, nicht auf jeder.
LOG_SHARE_NAME = "RDP-Protokoll"
#: Wie lange auf die erste Statusmeldung des frisch gestarteten Agenten gewartet
#: wird. Er veroeffentlicht direkt beim Start, noch vor seiner ersten
#: Warteschleife -- ueblich ist also eine Sekunde, nicht zwanzig. Die Frist ist
#: der Puffer fuer einen langsamen Rechner, nicht der Regelfall.
SNAPSHOT_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class SetupPaths:
    install: Path
    data: Path
    config: Path


#: Schritte, die jede Einrichtung durchläuft. Die Freigaben kommen als
#: Einzelne dazu, je nachdem, was angekreuzt ist.
BASE_INSTALL_STEPS = 6


def install_step_count(*, configure_share: bool, launch_now: bool = True) -> int:
    """Wie viele Schritte diese Einrichtung hat, für die Anzeige ``x/y``."""
    return BASE_INSTALL_STEPS + int(configure_share) + int(launch_now)


class SetupProgress:
    """Zählt die Schritte einer laufenden Einrichtung mit und meldet sie weiter.

    Warum es das gibt: Das Setup stand am Ende bis zu zwanzig Sekunden auf einer
    einzigen Zeile -- "wird eingerichtet und anschließend als SYSTEM geprüft" --
    und war von einem Absturz nicht zu unterscheiden. Es tat in Wahrheit genau
    das Richtige, nämlich abwarten, ob der Agent wirklich anläuft.

    ``sink`` wird aus dem Arbeitsthread gerufen und darf deshalb nichts an der
    Oberfläche anfassen; das Fenster holt sich die Meldungen über eine Queue ab.
    """

    def __init__(self, total: int, sink: object = None) -> None:
        self.total = max(1, total)
        self._sink = sink
        self._step = 0
        self._text = ""

    def step(self, text: str) -> str:
        """Den nächsten Schritt beginnen."""
        self._step = min(self._step + 1, self.total)
        return self._announce(text)

    def detail(self, text: str) -> str:
        """Denselben Schritt mit neuem Text melden, etwa einem Countdown."""
        return self._announce(text)

    def line(self) -> str:
        return f"Schritt {self._step}/{self.total}: {self._text}"

    def _announce(self, text: str) -> str:
        self._text = text
        message = self.line()
        if self._sink is not None:
            self._sink(message)
        return message


def bundle_payload(root: Path | None = None) -> Path:
    base = root or Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    payload = base / "payload"
    if not (payload / AGENT_EXE).is_file():
        raise FileNotFoundError(
            "Das Setup enthält keine vollständigen Agent-Dateien. "
            "Bitte das vollständige Setup neu erstellen."
        )
    return payload


def setup_paths() -> SetupPaths:
    install = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / INSTALL_FOLDER
    data = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / INSTALL_FOLDER
    return SetupPaths(install, data, data / "agent-config.json")


def is_administrator() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def _hidden_startupinfo() -> subprocess.STARTUPINFO:
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo


def system32_tool(name: str) -> str:
    """Resolve a Windows tool to its absolute System32 path.

    The setup runs elevated.  A bare executable name would let CreateProcess
    search the application and working directory before System32, so a planted
    schtasks.exe next to the extracted setup would run as Administrator.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.exe", name):
        raise ValueError(f"Kein zulässiger Windows-Werkzeugname: {name}")
    tool = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / name
    if not tool.is_file():
        raise RuntimeError(f"Windows-Werkzeug nicht gefunden: {tool}")
    return str(tool)


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    # The caller passes a bare tool name; it is resolved to System32 here so no
    # call site can reintroduce a relative executable lookup.
    resolved = [system32_tool(command[0]), *command[1:]]
    result = subprocess.run(  # noqa: S603 - argv[0] is an absolute System32 path
        resolved,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        startupinfo=_hidden_startupinfo(),
        check=False,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"Windows-Befehl fehlgeschlagen ({result.returncode}).")
    return result


def validate_workstation_id(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 128 or not value[0].isalnum():
        raise ValueError("Bitte die Maschinen-ID exakt wie im Portal eingeben.")
    if any(
        not (character.isascii() and (character.isalnum() or character in "_.-"))
        for character in value
    ):
        raise ValueError(
            "Die Maschinen-ID darf nur Buchstaben, Zahlen, Punkt, Unterstrich und Bindestrich enthalten."
        )
    return value


def normalize_status_directory(value: str) -> Path:
    expanded = os.path.expandvars(value.strip())
    if not expanded or not ntpath.isabs(expanded) or "%" in expanded:
        raise ValueError(
            "Bitte einen vollständigen lokalen oder Netzwerkpfad ohne unbekannte Umgebungsvariable angeben."
        )
    return Path(expanded)


def _local_user_exists(name: str) -> bool:
    try:
        win32net.NetUserGetInfo(None, name, 1)
        return True
    except pywintypes.error as exc:
        if exc.winerror == 2221:  # NERR_UserNotFound
            return False
        raise


def _share_info(name: str) -> dict[str, object] | None:
    try:
        info: dict[str, object] = win32net.NetShareGetInfo(None, name, 2)
        return info
    except pywintypes.error as exc:
        if exc.winerror == 2310:  # NERR_NetNameNotFound
            return None
        raise


def _same_windows_path(first: Path | str, second: Path | str) -> bool:
    return ntpath.normcase(ntpath.abspath(str(first))) == ntpath.normcase(
        ntpath.abspath(str(second))
    )


def _assert_local_share_path(path: Path) -> None:
    text = str(path)
    drive, _ = ntpath.splitdrive(text)
    if not drive or text.startswith("\\\\") or any(part == ".." for part in path.parts):
        raise ValueError(
            "Für die Statusfreigabe ist ein vollständiger lokaler Laufwerkspfad erforderlich."
        )
    ancestor = path
    while str(ancestor) != ancestor.anchor:
        if ancestor.exists() and (
            ancestor.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(ancestor)
        ):
            raise ValueError(f"Verknüpfung im Statuspfad; Einrichtung abgebrochen: {ancestor}")
        ancestor = ancestor.parent


def _deny_interactive_logon(reader_sid: pywintypes.SIDType, reader_name: str) -> None:
    """Restrict the read-only share account to network access.

    The folder ACL already limits what the account may read, but as a member of
    Users it could otherwise sign in at the console or over RDP.  It only ever
    needs to reach the SMB share, so local and remote interactive logon and batch
    and service logon are denied.
    """
    # Only the two rights LsaAddAccountRights needs, not POLICY_ALL_ACCESS.
    policy = win32security.LsaOpenPolicy(
        None,
        win32security.POLICY_CREATE_ACCOUNT | win32security.POLICY_LOOKUP_NAMES,
    )
    try:
        win32security.LsaAddAccountRights(
            policy,
            reader_sid,
            (
                "SeDenyInteractiveLogonRight",
                "SeDenyRemoteInteractiveLogonRight",
                "SeDenyBatchLogonRight",
                "SeDenyServiceLogonRight",
            ),
        )
    except pywintypes.error as exc:
        # The share still works without this; surface it instead of failing the
        # install, because the account's read-only ACL is the primary control.
        raise RuntimeError(
            f"Die Anmelderechte für {reader_name} konnten nicht eingeschränkt werden "
            f"(Windows-Fehler {exc.winerror}). Die Einrichtung wurde abgebrochen, "
            "damit kein anmeldefähiges Konto zurückbleibt."
        ) from exc
    finally:
        win32security.LsaClose(policy)


def _share_directory_acl(
    path: Path, reader_sid: pywintypes.SIDType, *, writable: bool = False
) -> None:
    """Set the folder ACL for a share the portal reaches through ``reader_name``.

    ``writable`` unterscheidet die beiden Zwecke. Der Statusordner bleibt
    lesend: Dort schreibt der Agent, das Portal schaut nur zu. Der gemeinsame
    Protokollordner muss beschreibbar sein, weil dort jedes Portal seine
    Ereignisse anhängt -- und ``DELETE`` gehört dazu, sonst scheitert die
    Rotation, die die gekürzte Datei über die alte schiebt.

    Die Schreibrechte gelten nur für den Ordner, der sie braucht. Der
    Statusordner derselben Maschine bleibt davon unberührt.
    """
    acl = win32security.ACL()
    inheritance = win32security.CONTAINER_INHERIT_ACE | win32security.OBJECT_INHERIT_ACE
    system_sid = win32security.ConvertStringSidToSid("S-1-5-18")
    administrators_sid = win32security.ConvertStringSidToSid("S-1-5-32-544")
    acl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION_DS,
        inheritance,
        ntsecuritycon.FILE_ALL_ACCESS,
        system_sid,
    )
    acl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION_DS,
        inheritance,
        ntsecuritycon.FILE_ALL_ACCESS,
        administrators_sid,
    )
    reader_access = ntsecuritycon.FILE_GENERIC_READ | ntsecuritycon.FILE_GENERIC_EXECUTE
    if writable:
        reader_access |= ntsecuritycon.FILE_GENERIC_WRITE | ntsecuritycon.DELETE
    acl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION_DS,
        inheritance,
        reader_access,
        reader_sid,
    )
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        acl,
        None,
    )


def _share_security_descriptor(
    reader_sid: pywintypes.SIDType, *, writable: bool = False
) -> pywintypes.SECURITY_DESCRIPTORType:
    acl = win32security.ACL()
    system_sid = win32security.ConvertStringSidToSid("S-1-5-18")
    administrators_sid = win32security.ConvertStringSidToSid("S-1-5-32-544")
    acl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, system_sid)
    acl.AddAccessAllowedAce(
        win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, administrators_sid
    )
    reader_access = ntsecuritycon.FILE_GENERIC_READ
    if writable:
        reader_access |= ntsecuritycon.FILE_GENERIC_WRITE | ntsecuritycon.DELETE
    acl.AddAccessAllowedAce(win32security.ACL_REVISION, reader_access, reader_sid)
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorDacl(True, acl, False)
    return descriptor


def _restore_directory_security(path: Path, descriptor: pywintypes.SECURITY_DESCRIPTORType) -> None:
    control, _ = descriptor.GetSecurityDescriptorControl()
    protection = (
        win32security.PROTECTED_DACL_SECURITY_INFORMATION
        if control & win32security.SE_DACL_PROTECTED
        else win32security.UNPROTECTED_DACL_SECURITY_INFORMATION
    )
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | protection,
        None,
        None,
        descriptor.GetSecurityDescriptorDacl(),
        None,
    )


def ensure_status_share(
    status_directory: Path,
    password: str,
    password_confirmation: str,
    *,
    reader_name: str = READER_NAME,
    share_name: str = SHARE_NAME,
) -> tuple[str, bool]:
    """Create or safely reuse the local read-only status share."""
    _assert_local_share_path(status_directory)
    user_exists = _local_user_exists(reader_name)
    existing_share = _share_info(share_name)
    if user_exists or existing_share is not None:
        if not user_exists or existing_share is None:
            raise RuntimeError(
                f"{reader_name} und {share_name} sind nur teilweise vorhanden. "
                "Aus Sicherheitsgründen wurde nichts verändert."
            )
        existing_path = str(existing_share.get("path", ""))
        if not _same_windows_path(existing_path, status_directory):
            raise RuntimeError(
                f"Die vorhandene Freigabe {share_name} zeigt auf {existing_path}, "
                f"nicht auf {status_directory}. Es wurde nichts verändert."
            )
        return f"{os.environ.get('COMPUTERNAME', '')}\\{reader_name}", False

    if not password:
        raise ValueError("Für das neue Lesekonto muss ein Kennwort vergeben werden.")
    if password != password_confirmation:
        raise ValueError("Die beiden Kennworteingaben stimmen nicht überein.")

    status_directory.mkdir(parents=True, exist_ok=True)
    old_security = win32security.GetNamedSecurityInfo(
        str(status_directory),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION,
    )
    user_created = False
    acl_changed = False
    try:
        win32net.NetUserAdd(
            None,
            1,
            {
                "name": reader_name,
                "password": password,
                "priv": win32netcon.USER_PRIV_USER,
                "home_dir": None,
                "comment": "Lesekonto für RDP-Agent-Status",
                "flags": (
                    win32netcon.UF_SCRIPT
                    | win32netcon.UF_NORMAL_ACCOUNT
                    | win32netcon.UF_DONT_EXPIRE_PASSWD
                ),
                "script_path": None,
            },
        )
        user_created = True
        reader_sid, _, _ = win32security.LookupAccountName(None, reader_name)
        _deny_interactive_logon(reader_sid, reader_name)
        _share_directory_acl(status_directory, reader_sid)
        acl_changed = True
        win32net.NetShareAdd(
            None,
            502,
            {
                "netname": share_name,
                "type": win32netcon.STYPE_DISKTREE,
                "remark": "Kirschke RDP-Agent Status (nur Lesen)",
                "permissions": 0,
                "max_uses": -1,
                "current_uses": 0,
                "path": str(status_directory),
                "passwd": None,
                "reserved": 0,
                "security_descriptor": _share_security_descriptor(reader_sid),
            },
        )
    except Exception as exc:
        rollback_failed = False
        if acl_changed:
            try:
                _restore_directory_security(status_directory, old_security)
            except pywintypes.error:
                rollback_failed = True
        if user_created:
            try:
                win32net.NetUserDel(None, reader_name)
            except pywintypes.error:
                rollback_failed = True
        code = getattr(exc, "winerror", None)
        if code == 2245:
            raise ValueError(
                "Das Kennwort erfüllt die Kennwortrichtlinie dieses Rechners nicht. "
                "Bitte ein längeres, komplexes Kennwort verwenden."
            ) from exc
        suffix = " Die automatische Rücknahme war unvollständig." if rollback_failed else ""
        code_text = str(code) if code is not None else type(exc).__name__
        raise RuntimeError(
            f"Lesekonto oder Statusfreigabe konnte nicht erstellt werden ({code_text}).{suffix}"
        ) from exc
    return f"{os.environ.get('COMPUTERNAME', '')}\\{reader_name}", True


def ensure_log_share(
    log_directory: Path,
    password: str,
    password_confirmation: str,
    *,
    reader_name: str = READER_NAME,
    share_name: str = LOG_SHARE_NAME,
) -> tuple[str, str, bool]:
    """Create or safely reuse the writable folder for the shared event log.

    Wozu das gebraucht wird: Installiert jeder das Portal über sein Setup, liegt
    der gemeinsame Stand in seinem eigenen Profil, und jeder führt sein eigenes
    Inventar. Das Ereignisprotokoll ist der Teil, den man trotzdem zusammen
    sehen will -- dafür braucht es genau einen Ordner, in den alle Portale
    schreiben dürfen.

    Bewusst dasselbe Konto wie für den Statusordner. Ein zweites brächte ein
    zweites Kennwort in Umlauf, und das Portal müsste lernen, welches wohin
    gehört; es probiert heute für jeden Server dasselbe. Geschrieben werden darf
    deshalb nur hier: Der Statusordner behält seine Leserechte.

    Anders als beim Statusordner ist ein bereits vorhandenes Konto hier der
    Normalfall -- die Maschine, die das Protokoll beherbergt, ist meist selbst
    eine Zielmaschine mit Agent. Vorhanden heißt dann wiederverwenden, nicht
    abbrechen.

    Gibt Konto, UNC-Pfad und zurück, ob die Freigabe neu angelegt wurde.
    """
    _assert_local_share_path(log_directory)
    computer = os.environ.get("COMPUTERNAME", "")
    account = f"{computer}\\{reader_name}"
    unc = f"\\\\{_network_host_name()}\\{share_name}"
    existing_share = _share_info(share_name)
    if existing_share is not None:
        existing_path = str(existing_share.get("path", ""))
        if not _same_windows_path(existing_path, log_directory):
            raise RuntimeError(
                f"Die vorhandene Freigabe {share_name} zeigt auf {existing_path}, "
                f"nicht auf {log_directory}. Es wurde nichts verändert."
            )
        return account, unc, False

    user_exists = _local_user_exists(reader_name)
    if not user_exists:
        if not password:
            raise ValueError(
                f"{reader_name} besteht auf diesem Rechner noch nicht. "
                "Bitte ein Kennwort für das neue Konto vergeben."
            )
        if password != password_confirmation:
            raise ValueError("Die beiden Kennworteingaben stimmen nicht überein.")

    log_directory.mkdir(parents=True, exist_ok=True)
    old_security = win32security.GetNamedSecurityInfo(
        str(log_directory),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION,
    )
    user_created = False
    acl_changed = False
    try:
        if not user_exists:
            win32net.NetUserAdd(
                None,
                1,
                {
                    "name": reader_name,
                    "password": password,
                    "priv": win32netcon.USER_PRIV_USER,
                    "home_dir": None,
                    "comment": "Lesekonto für RDP-Agent-Status",
                    "flags": (
                        win32netcon.UF_SCRIPT
                        | win32netcon.UF_NORMAL_ACCOUNT
                        | win32netcon.UF_DONT_EXPIRE_PASSWD
                    ),
                    "script_path": None,
                },
            )
            user_created = True
        reader_sid, _, _ = win32security.LookupAccountName(None, reader_name)
        if user_created:
            _deny_interactive_logon(reader_sid, reader_name)
        _share_directory_acl(log_directory, reader_sid, writable=True)
        acl_changed = True
        win32net.NetShareAdd(
            None,
            502,
            {
                "netname": share_name,
                "type": win32netcon.STYPE_DISKTREE,
                "remark": "Kirschke RDP-Portal: gemeinsames Ereignisprotokoll",
                "permissions": 0,
                "max_uses": -1,
                "current_uses": 0,
                "path": str(log_directory),
                "passwd": None,
                "reserved": 0,
                "security_descriptor": _share_security_descriptor(reader_sid, writable=True),
            },
        )
    except Exception as exc:
        rollback_failed = False
        if acl_changed:
            try:
                _restore_directory_security(log_directory, old_security)
            except pywintypes.error:
                rollback_failed = True
        # Ein Konto, das es vorher schon gab, wird nie entfernt: Daran hängt der
        # Statuszugang dieser Maschine.
        if user_created:
            try:
                win32net.NetUserDel(None, reader_name)
            except pywintypes.error:
                rollback_failed = True
        code = getattr(exc, "winerror", None)
        if code == 2245:
            raise ValueError(
                "Das Kennwort erfüllt die Kennwortrichtlinie dieses Rechners nicht. "
                "Bitte ein längeres, komplexes Kennwort verwenden."
            ) from exc
        suffix = " Die automatische Rücknahme war unvollständig." if rollback_failed else ""
        code_text = str(code) if code is not None else type(exc).__name__
        raise RuntimeError(
            f"Die Protokollfreigabe konnte nicht erstellt werden ({code_text}).{suffix}"
        ) from exc
    return account, unc, True


def _same_or_below(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _assert_safe_agent_directory(path: Path) -> None:
    resolved = path.resolve(strict=False)
    expected = setup_paths().install.resolve(strict=False)
    if resolved != expected or resolved.name.casefold() != INSTALL_FOLDER.casefold():
        raise RuntimeError(f"Ungültiger Agent-Installationspfad: {resolved}")
    if not path.exists():
        return
    entries = [path, *path.rglob("*")]
    if any(
        entry.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(entry)
        for entry in entries
    ):
        raise RuntimeError(
            f"Verknüpfung im Installationsordner; keine automatische Löschung: {resolved}"
        )


def _remove_agent_directory(path: Path) -> None:
    _assert_safe_agent_directory(path)
    for attempt in range(20):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.25)


def _task_xml(agent: Path, config: Path, workstation_id: str) -> str:
    command = escape(str(agent))
    arguments = escape(f'--config "{config}" --run')
    description = escape(
        f"Kirschke RDP-Agent: veröffentlicht den Sitzungsstatus von {workstation_id}."
    )
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{description}</Description></RegistrationInfo>
  <Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowHardTerminate>true</AllowHardTerminate>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>{command}</Command><Arguments>{arguments}</Arguments></Exec></Actions>
</Task>"""


def _delete_task() -> bool:
    query = _run(["schtasks.exe", "/Query", "/TN", TASK_NAME], check=False)
    if query.returncode:
        return False
    _run(["schtasks.exe", "/End", "/TN", TASK_NAME], check=False)
    _run(["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"])
    return True


def _register_task(agent: Path, config: Path, workstation_id: str) -> None:
    xml_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as temporary:
            xml_path = Path(temporary.name)
        xml_path.write_text(_task_xml(agent, config, workstation_id), encoding="utf-16")
        _run(["schtasks.exe", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"])
    finally:
        if xml_path is not None:
            xml_path.unlink(missing_ok=True)


def _write_uninstall_registration(paths: SetupPaths) -> None:
    installed_setup = paths.install / SETUP_EXE
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, access=winreg.KEY_WRITE
    ) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Kirschke RDP Agent")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, AGENT_VERSION)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(paths.install / AGENT_EXE))
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Kirschke")
        winreg.SetValueEx(
            key, "UninstallString", 0, winreg.REG_SZ, f'"{installed_setup}" --uninstall'
        )


def _delete_uninstall_registration() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY)
    except FileNotFoundError:
        pass


def _secure_data_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            "icacls.exe",
            str(directory),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        ],
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Das Agent-Datenverzeichnis konnte nicht abgesichert werden.")


def _copy_setup_executable(destination: Path) -> None:
    source = Path(sys.executable).resolve()
    target = destination / SETUP_EXE
    if source != target.resolve(strict=False):
        shutil.copy2(source, target)


def _network_host_name() -> str:
    """Der Rechnername, wie ihn der Agent meldet und das Netzwerk ihn auflöst.

    Nicht ``%COMPUTERNAME%``: Das ist der NetBIOS-Name, auf 15 Zeichen gekürzt
    und großgeschrieben. Auf ``Remote-Ettlingen`` stand dort ``REMOTE-ETTLINGE``,
    und die Statusprüfung lehnte den laufenden Agenten deshalb jedes Mal ab.
    """
    return socket.gethostname() or os.environ.get("COMPUTERNAME", "")


def _local_host_names() -> set[str]:
    """Jede Schreibweise, unter der dieser Rechner sich selbst kennt."""
    names = {socket.gethostname(), os.environ.get("COMPUTERNAME", "")}
    return {name.casefold() for name in names if name}


def _confirm_snapshot(
    status_directory: Path,
    workstation_id: str,
    started_at: datetime,
    progress: SetupProgress | None = None,
) -> None:
    """Warten, bis der Agent als SYSTEM seinen ersten Status geschrieben hat.

    Der ehrliche Nachweis, dass die Einrichtung nicht nur Dateien kopiert hat.
    Normalerweise ist das nach ein bis zwei Sekunden vorbei -- der Agent
    veröffentlicht direkt beim Start, noch vor seiner ersten Warteschleife --,
    aber es kann dauern, und dann muss man sehen, dass gewartet wird und nicht
    gehangen.
    """
    snapshot_path = status_directory / f"{workstation_id}.json"
    deadline = time.monotonic() + SNAPSHOT_TIMEOUT_SECONDS
    reason = f"Die Statusdatei {snapshot_path} ist nicht entstanden."
    while time.monotonic() < deadline:
        if progress is not None:
            remaining = max(1, int(deadline - time.monotonic()) + 1)
            progress.detail(
                f"Auf die erste Statusmeldung des Agenten warten … (noch {remaining} s)"
            )
        time.sleep(0.5)
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
            observed = datetime.fromisoformat(
                str(snapshot["observed_at_utc"]).replace("Z", "+00:00")
            )
        except FileNotFoundError:
            continue
        except (OSError, ValueError, KeyError, TypeError) as exc:
            reason = f"Die Statusdatei {snapshot_path} ist nicht lesbar ({exc})."
            continue
        hostname = str(snapshot.get("hostname", ""))
        if snapshot.get("workstation_id") != workstation_id:
            reason = (
                f"Die Statusdatei meldet die Maschinen-ID "
                f"{snapshot.get('workstation_id')!r} statt {workstation_id!r}."
            )
        elif hostname.casefold() not in _local_host_names():
            reason = (
                f"Die Statusdatei stammt vom Rechner {hostname!r}, "
                f"nicht von {_network_host_name()!r}."
            )
        elif snapshot.get("agent_status") != "online":
            reason = f"Der Agent meldet {snapshot.get('agent_status')!r} statt 'online'."
        elif observed.astimezone(UTC) < started_at:
            reason = "Die Statusdatei ist älter als der Start des Agenten."
        else:
            return
    raise RuntimeError(
        "Der System-Agent wurde eingerichtet, hat aber keinen aktuellen Online-Status geschrieben.\n"
        f"{reason}\n"
        "Prüfe die Aufgabenplanung, die Ordnerrechte und "
        f"{setup_paths().data / 'agent.log'}."
    )


def install_agent(
    payload: Path,
    workstation_id: str,
    status_directory: str,
    poll_interval: int,
    *,
    configure_share: bool = True,
    reader_password: str = "",
    reader_password_confirmation: str = "",
    launch_now: bool = True,
    progress: SetupProgress | None = None,
) -> SetupPaths:
    steps = progress or SetupProgress(
        install_step_count(configure_share=configure_share, launch_now=launch_now)
    )
    steps.step("Eingaben und Administratorrechte prüfen …")
    if not is_administrator():
        raise PermissionError(
            "Die rechnerweite Agent-Installation muss als Administrator gestartet werden."
        )
    workstation_id = validate_workstation_id(workstation_id)
    if poll_interval < 5 or poll_interval > 60:
        raise ValueError("Das Aktualisierungsintervall muss zwischen 5 und 60 Sekunden liegen.")
    source = payload.resolve(strict=True)
    if not (source / AGENT_EXE).is_file():
        raise FileNotFoundError("Kirschke-RDP-Agent.exe wurde im Setup nicht gefunden.")
    status = normalize_status_directory(status_directory)
    paths = setup_paths()
    for checked in (source, status):
        if _same_or_below(checked, paths.install):
            raise ValueError(
                "Installationsquelle und Statusordner müssen außerhalb der "
                f"Agent-Installation liegen: {paths.install}"
            )
    if configure_share:
        steps.step(f"Freigabe {SHARE_NAME} und Lesekonto {READER_NAME} einrichten …")
        ensure_status_share(
            status,
            reader_password,
            reader_password_confirmation,
        )
    steps.step("Statusordner anlegen und Schreibzugriff prüfen …")
    status.mkdir(parents=True, exist_ok=True)
    status = status.resolve(strict=True)
    probe = status / f".kirschke-agent-write-test-{uuid.uuid4().hex}.tmp"
    try:
        probe.write_text("ok", encoding="utf-8")
    except OSError as exc:
        raise PermissionError(
            f"Der Statusordner kann nicht beschrieben werden: {status}\n{exc}"
        ) from exc
    finally:
        probe.unlink(missing_ok=True)

    steps.step("Laufenden Agenten beenden und alte Dateien entfernen …")
    _delete_task()
    if paths.install.exists():
        _remove_agent_directory(paths.install)
    steps.step("Programmdateien kopieren …")
    paths.install.mkdir(parents=True)
    shutil.copytree(source, paths.install, dirs_exist_ok=True)
    _copy_setup_executable(paths.install)
    _secure_data_directory(paths.data)
    steps.step("Konfiguration schreiben …")
    config = {
        "workstation_id": workstation_id,
        "poll_interval": poll_interval,
        "publish_local_status": True,
        "live_status_enabled": True,
        "live_status_reader": "PortalLeser",
        "status_directory": str(status),
        "log_file": str(paths.data / "agent.log"),
        "agent_version": AGENT_VERSION,
    }
    paths.config.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    steps.step("Aufgabenplanung einrichten …")
    _register_task(paths.install / AGENT_EXE, paths.config, workstation_id)
    _write_uninstall_registration(paths)
    if launch_now:
        steps.step("Agent starten …")
        started_at = datetime.now(UTC)
        _run(["schtasks.exe", "/Run", "/TN", TASK_NAME])
        _confirm_snapshot(status, workstation_id, started_at, steps)
    return paths


def uninstall_agent() -> bool:
    if not is_administrator():
        raise PermissionError(
            "Die rechnerweite Agent-Deinstallation muss als Administrator gestartet werden."
        )
    paths = setup_paths()
    removed_task = _delete_task()
    _delete_uninstall_registration()
    paths.config.unlink(missing_ok=True)
    if paths.install.exists():
        _remove_agent_directory(paths.install)
    return removed_task


def _running_from_install_directory() -> bool:
    return _same_or_below(Path(sys.executable), setup_paths().install)


def _launch_temporary_uninstaller() -> None:
    temporary = Path(tempfile.gettempdir()) / f"Kirschke-RDP-Agent-Uninstall-{uuid.uuid4().hex}.exe"
    shutil.copy2(sys.executable, temporary)
    subprocess.Popen(  # noqa: S603 - launches the setup copy created above
        [str(temporary), "--uninstall-worker", str(os.getpid())],
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )


def _wait_for_process_exit(process_id: int) -> None:
    process = ctypes.windll.kernel32.OpenProcess(0x00100000, False, process_id)
    if process:
        ctypes.windll.kernel32.WaitForSingleObject(process, 30_000)
        ctypes.windll.kernel32.CloseHandle(process)


def _remove_temporary_executable_on_reboot() -> None:
    move_file_delay_until_reboot = 0x4
    ctypes.windll.kernel32.MoveFileExW(
        str(Path(sys.executable)), None, move_file_delay_until_reboot
    )


class InstallerWindow:
    def __init__(self, payload: Path) -> None:
        self.payload = payload
        self.root = Tk()
        self.root.title(f"Kirschke RDP-Agent {AGENT_VERSION} installieren")
        # Keine feste Größe mehr: Das Fenster misst seinen Inhalt. Ein festes
        # Maß hält nur, solange nichts dazukommt und niemand eine größere
        # Windows-Schrift eingestellt hat -- beides ist eingetreten.
        self.root.resizable(True, True)
        # An update must not silently rewrite what the previous run configured.
        # Defaulting the machine ID to COMPUTERNAME cost an afternoon once: a
        # machine registered as WS-005 in the portal had its agent reset to the
        # host name by a later click-through, and every logoff was refused because
        # the two no longer matched.
        existing = self._existing_configuration()
        self.workstation_id = StringVar(
            value=existing.get("workstation_id") or os.environ.get("COMPUTERNAME", "")
        )
        self.status_directory = StringVar(
            value=existing.get("status_directory") or r"C:\RDP-Portal-Daten\agenten-status"
        )
        self.interval = StringVar(value=self._interval_label(existing.get("poll_interval")))
        self.is_update = bool(existing)
        self.configure_share = BooleanVar(value=True)
        # Die Protokollfreigabe ist eine Sache fuer genau eine Maschine im
        # Testbetrieb, nicht fuer jede -- deshalb standardmaessig aus.
        self.configure_log_share = BooleanVar(value=False)
        self.log_directory = StringVar(
            value=str(Path(os.environ.get("ProgramData", r"C:\ProgramData"))
                      / "KirschkeRDPPortal" / LOG_SHARE_NAME)
        )
        self.reader_password = StringVar(value="")
        self.reader_password_confirmation = StringVar(value="")
        self.message = StringVar(value="")
        #: Ergebnis der optionalen Protokollfreigabe, für die Schlussmeldung.
        #: Muss hier stehen und nicht erst im Arbeitsthread gesetzt werden: Ohne
        #: angekreuzte Protokollfreigabe wurde es nie zugewiesen, und die
        #: Erfolgsmeldung lief in einen AttributeError -- mitten im Tk-Callback,
        #: also ohne Dialog und ohne Fehler. Das Fenster blieb mit gesperrten
        #: Knöpfen stehen und sah aus, als hinge die Installation.
        self.log_share_note = ""
        #: Zwischenstände aus dem Arbeitsthread. Über eine Queue, weil an der
        #: Oberfläche nur der Tk-Thread etwas ändern darf.
        self.progress_messages: queue.Queue[str] = queue.Queue()
        self.results: queue.Queue[tuple[bool, str, str]] = queue.Queue()
        self._build()
        self._fit_to_content()

    def _fit_to_content(self) -> None:
        """Das Fenster auf seinen Inhalt ziehen, aber nie über den Bildschirm hinaus.

        Zwei Grenzen, beide notwendig: Nach unten muss das Fenster gross genug
        sein, damit nichts abgeschnitten wird -- nach oben darf es den
        Bildschirm nicht überschreiten, sonst liegt der untere Rand samt
        Knopfzeile ausserhalb und man kommt erst recht nicht heran.

        ``minsize`` hält die Breite: Schmaler gezogen bräche der Text um und das
        Fenster würde wieder höher, statt kleiner zu werden.
        """
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        limit_width = int(self.root.winfo_screenwidth() * 0.95)
        limit_height = int(self.root.winfo_screenheight() * 0.90)
        width, height = min(width, limit_width), min(height, limit_height)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, min(height, 420))

    @staticmethod
    def _existing_configuration() -> dict:
        """Read the settings of an agent already installed here, or ``{}``.

        Best effort on purpose: a missing, unreadable or damaged file must leave
        the installer fully usable, it just falls back to the fresh defaults.
        """
        try:
            data = json.loads(setup_paths().config.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _interval_label(seconds: object) -> str:
        """The dropdown entry for a stored interval, or the recommended default."""
        labels = {30: "30 Sekunden (empfohlen)", 60: "60 Sekunden", 15: "15 Sekunden"}
        return labels.get(seconds if type(seconds) is int else 0, labels[30])

    def _build(self) -> None:
        # Die Knopfzeile hängt am Fenster und nicht im Inhaltsraster, und sie
        # wird zuerst gepackt: So bekommt sie ihren Platz vor allem anderen und
        # bleibt erreichbar, egal wie hoch der Inhalt wird. Genau daran ist es
        # schon gescheitert -- ein zusätzlicher Kasten schob "Jetzt
        # installieren" unter den unteren Rand, und weil das Fenster nicht
        # veränderbar war, kam man auch durch Aufziehen nicht daran.
        buttons = ttk.Frame(self.root, padding=(24, 0, 24, 16))
        buttons.pack(side="bottom", fill="x")
        self.install_button = ttk.Button(
            buttons, text="Jetzt installieren", command=self._start_install
        )
        ttk.Button(buttons, text="Abbrechen", command=self.root.destroy).pack(
            side="right"
        )
        self.install_button.pack(side="right", padx=(0, 10))
        ttk.Label(
            buttons, textvariable=self.message, foreground="#155a8a", wraplength=420
        ).pack(side="left", fill="x", expand=True)
        frame = ttk.Frame(self.root, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=f"RDP-Agent {AGENT_VERSION} auf diesem Ziel-PC einrichten",
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        introduction = (
            "Rechnerweiter Start beim Hochfahren als SYSTEM, auch ohne Benutzeranmeldung. "
            "Administratorrechte erforderlich. Die Windows-Ausführungsrichtlinie wird nicht verändert."
        )
        if self.is_update:
            introduction += (
                "\n\nEs ist bereits ein Agent eingerichtet. Die Felder sind mit dessen "
                "aktuellen Einstellungen vorbelegt — unverändert lassen heißt: Update "
                "ohne Änderung der Zuordnung."
            )
        ttk.Label(frame, text=introduction, wraplength=620).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 22)
        )
        ttk.Label(frame, text="Maschinen-ID im Portal").grid(
            row=2, column=0, columnspan=3, sticky="w"
        )
        ttk.Entry(frame, textvariable=self.workstation_id).grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(4, 16)
        )
        ttk.Label(frame, text="Lokaler Statusordner auf diesem Zielrechner").grid(
            row=4, column=0, columnspan=3, sticky="w"
        )
        ttk.Entry(frame, textvariable=self.status_directory).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=4
        )
        ttk.Button(frame, text="Auswählen …", command=self._browse).grid(
            row=5, column=2, padx=(10, 0), pady=4
        )
        ttk.Label(
            frame,
            text=(
                r"Empfohlen: C:\RDP-Portal-Daten\agenten-status. Der Agent schreibt lokal als SYSTEM. "
                r"Das Portal liest den SMB-Fallback unter \\RECHNER\RDP-Status; PortalLeser bleibt Lesekonto."
            ),
            wraplength=620,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 18))
        ttk.Separator(frame).grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        ttk.Checkbutton(
            frame,
            text=f"SMB-Fallback {SHARE_NAME} und Lesekonto {READER_NAME} einrichten",
            variable=self.configure_share,
            command=self._toggle_share_fields,
        ).grid(row=8, column=0, columnspan=3, sticky="w")
        ttk.Label(
            frame,
            text=(
                "Bei der ersten Einrichtung ein eigenes Kennwort vergeben und im Passwortmanager "
                "aufbewahren. Bei bereits vollständig vorhandener Freigabe bleiben beide Felder leer."
            ),
            wraplength=620,
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(4, 10))
        ttk.Label(frame, text=f"Kennwort für {READER_NAME}").grid(
            row=10, column=0, columnspan=3, sticky="w"
        )
        self.password_entry = ttk.Entry(frame, textvariable=self.reader_password, show="•")
        self.password_entry.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(4, 10))
        ttk.Label(frame, text="Kennwort wiederholen").grid(
            row=12, column=0, columnspan=3, sticky="w"
        )
        self.password_confirmation_entry = ttk.Entry(
            frame, textvariable=self.reader_password_confirmation, show="•"
        )
        self.password_confirmation_entry.grid(
            row=13, column=0, columnspan=3, sticky="ew", pady=(4, 16)
        )
        ttk.Label(frame, text="Aktualisierung").grid(row=14, column=0, sticky="w")
        ttk.Combobox(
            frame,
            textvariable=self.interval,
            values=("30 Sekunden (empfohlen)", "60 Sekunden", "15 Sekunden"),
            state="readonly",
            width=28,
        ).grid(row=14, column=1, sticky="w")
        # Eigener Kasten in einer einzigen Rasterzeile: Die Protokollfreigabe
        # gehoert nicht zur Agent-Installation, sondern wird bei der Gelegenheit
        # miterledigt -- und zwar auf genau einer Maschine im Testbetrieb.
        log_box = ttk.LabelFrame(frame, text="Gemeinsames Protokoll (optional, einmal pro Testbetrieb)")
        log_box.grid(row=15, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        log_box.columnconfigure(0, weight=1)
        ttk.Checkbutton(
            log_box,
            text=f"Beschreibbare Freigabe {LOG_SHARE_NAME} auf diesem Rechner anlegen",
            variable=self.configure_log_share,
            command=self._toggle_log_fields,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 2))
        ttk.Label(
            log_box,
            text=(
                "Nur auf einem Rechner nötig. Dort sammeln alle Portale ihre Ereignisse, "
                f"damit im Reiter Logs steht, wer wann welche Maschine benutzt hat. "
                f"{READER_NAME} bekommt hier — und nur hier — Schreibrecht; der Statusordner "
                "bleibt lesend."
            ),
            wraplength=580,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))
        self.log_directory_entry = ttk.Entry(log_box, textvariable=self.log_directory)
        self.log_directory_entry.grid(row=2, column=0, sticky="ew", padx=(8, 4), pady=(0, 8))
        self.log_browse_button = ttk.Button(log_box, text="Ordner wählen", command=self._browse_log)
        self.log_browse_button.grid(row=2, column=1, sticky="e", padx=(0, 8), pady=(0, 8))
        self._toggle_log_fields()
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

    def _browse(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.status_directory.get())
        if selected:
            self.status_directory.set(selected)

    def _browse_log(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.log_directory.get())
        if selected:
            self.log_directory.set(selected)

    def _toggle_log_fields(self) -> None:
        state = "normal" if self.configure_log_share.get() else "disabled"
        self.log_directory_entry.configure(state=state)
        self.log_browse_button.configure(state=state)

    def _toggle_share_fields(self) -> None:
        state = "normal" if self.configure_share.get() else "disabled"
        self.password_entry.configure(state=state)
        self.password_confirmation_entry.configure(state=state)

    def _start_install(self) -> None:
        self.install_button.configure(state="disabled")
        self.message.set("Einrichtung wird gestartet …")
        intervals = {"30 Sekunden (empfohlen)": 30, "60 Sekunden": 60, "15 Sekunden": 15}
        arguments = (
            self.workstation_id.get(),
            self.status_directory.get(),
            intervals[self.interval.get()],
            self.configure_share.get(),
            self.reader_password.get(),
            self.reader_password_confirmation.get(),
            self.configure_log_share.get(),
            self.log_directory.get(),
        )
        threading.Thread(target=self._install, args=arguments, daemon=True).start()
        self.root.after(100, self._poll_result)

    def _install(
        self,
        workstation_id: str,
        status_directory: str,
        poll_interval: int,
        configure_share: bool,
        reader_password: str,
        reader_password_confirmation: str,
        configure_log_share: bool,
        log_directory: str,
    ) -> None:
        steps = SetupProgress(
            install_step_count(configure_share=configure_share) + int(configure_log_share),
            self.progress_messages.put,
        )
        try:
            paths = install_agent(
                self.payload,
                workstation_id,
                status_directory,
                poll_interval,
                configure_share=configure_share,
                reader_password=reader_password,
                reader_password_confirmation=reader_password_confirmation,
                progress=steps,
            )
        except Exception as exc:  # noqa: BLE001 - shown to the local administrator
            self.results.put((False, str(exc), ""))
            return
        # Erst nach dem Agenten: Die Protokollfreigabe ist eine Zugabe, und ein
        # Fehler dabei darf eine gelungene Agent-Installation nicht als
        # gescheitert erscheinen lassen.
        if configure_log_share:
            steps.step(f"Protokollfreigabe {LOG_SHARE_NAME} anlegen …")
            try:
                _, unc, created = ensure_log_share(
                    normalize_status_directory(log_directory),
                    reader_password,
                    reader_password_confirmation,
                )
            except Exception as exc:  # noqa: BLE001 - shown to the local administrator
                self.log_share_note = (
                    f"Der Agent ist eingerichtet. Die Protokollfreigabe nicht: {exc}"
                )
            else:
                verb = "eingerichtet" if created else "war bereits vorhanden"
                self.log_share_note = (
                    f"Protokollfreigabe {verb}: {unc}\n"
                    "Diesen Pfad im Portal unter Admin → Gemeinsames Protokoll eintragen."
                )
        self.results.put((True, workstation_id.strip(), str(paths.config)))

    def _poll_result(self) -> None:
        # Erst die Zwischenstände leeren: Sonst bliebe die letzte Meldung
        # stehen, während der Arbeitsthread längst weiter ist.
        while True:
            try:
                self.message.set(self.progress_messages.get_nowait())
            except queue.Empty:
                break
        try:
            succeeded, first, second = self.results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_result)
            return
        self.reader_password.set("")
        self.reader_password_confirmation.set("")
        # Auch ein Fehler beim *Anzeigen* darf das Fenster nicht in der Schwebe
        # lassen. Genau das ist passiert: Eine fehlende Zuweisung liess die
        # Erfolgsmeldung scheitern, und zurueck blieb ein Fenster mit
        # gesperrten Knoepfen, dem niemand ansah, dass die Arbeit getan war.
        try:
            if succeeded:
                self._succeeded(first, second)
            else:
                self._failed(first)
        except Exception as exc:  # noqa: BLE001 - letzte Rettung fuer die Anzeige
            self.install_button.configure(state="normal")
            self.message.set("")
            messagebox.showwarning(
                "Ergebnis konnte nicht angezeigt werden",
                "Die Einrichtung ist beendet, die Rückmeldung dazu ist "
                f"fehlgeschlagen:\n{exc}\n\nBitte im Portal prüfen, ob die "
                "Maschine als Online gemeldet wird.",
                parent=self.root,
            )

    def _failed(self, detail: str) -> None:
        self.install_button.configure(state="normal")
        self.message.set("")
        messagebox.showerror("Installation nicht möglich", detail, parent=self.root)

    def _succeeded(self, workstation_id: str, config_path: str) -> None:
        computer = os.environ.get("COMPUTERNAME", "ZIELRECHNER")
        share_result = (
            f"\nFallback: \\\\{_network_host_name() or computer}\\{SHARE_NAME}"
            f"\nFreigabebenutzer: {computer}\\{READER_NAME}"
            if self.configure_share.get()
            else "\nSMB-Fallback wurde nicht eingerichtet."
        )
        messagebox.showinfo(
            "Installation abgeschlossen",
            "Der Agent wurde eingerichtet und als SYSTEM gestartet.\n\n"
            f"Maschinen-ID: {workstation_id}\nKonfiguration: {config_path}{share_result}"
            + (f"\n\n{self.log_share_note}" if self.log_share_note else ""),
            parent=self.root,
        )
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def _show_error(detail: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, detail, "Kirschke RDP-Agent – Setup", 0x10)


def main() -> int:
    try:
        if "--check" in sys.argv:
            bundle_payload()
            return 0
        if "--ui-check" in sys.argv:
            window = InstallerWindow(bundle_payload())
            window.root.after(1500, window.root.destroy)
            window.run()
            return 0
        if "--uninstall-worker" in sys.argv:
            index = sys.argv.index("--uninstall-worker")
            _wait_for_process_exit(int(sys.argv[index + 1]))
            uninstall_agent()
            _remove_temporary_executable_on_reboot()
            return 0
        if "--uninstall" in sys.argv:
            if _running_from_install_directory():
                _launch_temporary_uninstaller()
            else:
                uninstall_agent()
            return 0
        if not is_administrator():
            raise PermissionError(
                "Bitte das Setup als Administrator starten und die Windows-Abfrage bestätigen."
            )
        InstallerWindow(bundle_payload()).run()
        return 0
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        _show_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
