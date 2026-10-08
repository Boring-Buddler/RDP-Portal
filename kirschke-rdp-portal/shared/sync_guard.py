"""Hält das Portal aus OneDrive- und SharePoint-Ordnern heraus.

Das Portal schreibt seinen Stand, Sperrdateien, temporäre Dateien und das
Ereignisprotokoll im Sekundentakt. Liegt das in einem synchronisierten Ordner,
lädt OneDrive jede Zwischenstufe hoch, meldet Konflikte, legt Konfliktkopien
an und hält Dateien fest, die das Portal gerade ersetzen will. Gemeinsame
Daten gehen deshalb ausschließlich über das Netzwerk -- SMB-Freigaben und die
Pipe der Agenten --, und kein Pfad, den das Portal beschreibt, darf in einem
synchronisierten Ordner liegen.

Ob ein Ordner synchronisiert wird, verrät Windows an mehreren Stellen, und
keine davon ist für sich allein vollständig. Geprüft wird deshalb alles, was
sich ohne Zusatzsoftware feststellen lässt:

1. **Der Pfad selbst.** WebDAV-Pfade auf SharePoint (``\\\\firma.sharepoint.com@SSL\\
   DavWWWRoot\\…``), URLs und die Ordnernamen, die OneDrive selbst vergibt
   (``OneDrive``, ``OneDrive - Firma``).
2. **Die Umgebungsvariablen** ``OneDrive``, ``OneDriveCommercial`` und
   ``OneDriveConsumer`` -- die Wurzeln der persönlichen OneDrive-Ordner.
3. **Die OneDrive-Konten in der Registry.** Unter jedem Konto steht der
   ``UserFolder``; unter ``Tenants`` stehen die eingebundenen SharePoint-
   Bibliotheken, die gerade *nicht* im OneDrive-Ordner liegen (``C:\\Users\\x\\
   Firma GmbH\\Bibliothek - Dokumente``).
4. **Die Sync-Roots von Windows.** Jeder Cloud-Dateianbieter, auch ein anderer
   als OneDrive, meldet seine Ordner dort an.
5. **Die Dateiattribute.** Platzhalter und angeheftete Dateien eines
   Cloud-Anbieters tragen Attribute, die eine normale Datei nie hat. Das greift
   auch dann, wenn alle Registry-Einträge fehlen.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path, PureWindowsPath

logger = logging.getLogger(__name__)

#: Attribute, die nur Dateien und Ordner eines Cloud-Dateianbieters tragen.
FILE_ATTRIBUTE_PINNED = 0x00080000
FILE_ATTRIBUTE_UNPINNED = 0x00100000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
CLOUD_ATTRIBUTES = (
    FILE_ATTRIBUTE_PINNED
    | FILE_ATTRIBUTE_UNPINNED
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

#: Textmerkmale eines SharePoint-WebDAV-Pfads oder einer URL.
_SHAREPOINT_MARKERS = ("sharepoint.com", "davwwwroot", "@ssl", "://")

_ONEDRIVE_VARIABLES = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")


class SyncedFolderError(ValueError):
    """Ein Pfad liegt in einem von OneDrive oder SharePoint synchronisierten Ordner."""


def _normalise(value: str | Path) -> str:
    text = os.path.expandvars(str(value).strip())
    return str(PureWindowsPath(text)).rstrip("\\").casefold()


def _registry_roots() -> Iterator[tuple[str, str]]:
    """(Wurzel, Herkunft) aus OneDrive-Konten und Windows-Sync-Roots."""
    if sys.platform != "win32":
        return
    import winreg

    def values(key: winreg.HKEYType) -> Iterator[tuple[str, object]]:
        index = 0
        while True:
            try:
                name, data, _ = winreg.EnumValue(key, index)
            except OSError:
                return
            yield name, data
            index += 1

    def subkeys(key: winreg.HKEYType) -> Iterator[str]:
        index = 0
        while True:
            try:
                yield winreg.EnumKey(key, index)
            except OSError:
                return
            index += 1

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\OneDrive\Accounts"
        ) as accounts:
            for account in subkeys(accounts):
                try:
                    with winreg.OpenKey(accounts, account) as key:
                        for name, data in values(key):
                            if name == "UserFolder" and isinstance(data, str) and data:
                                yield data, f"OneDrive-Konto {account}"
                        try:
                            with winreg.OpenKey(key, "Tenants") as tenants:
                                for tenant in subkeys(tenants):
                                    with winreg.OpenKey(tenants, tenant) as entry:
                                        # Die Wertnamen *sind* die eingebundenen Ordner.
                                        for name, _ in values(entry):
                                            if name:
                                                yield name, f"SharePoint-Bibliothek ({tenant})"
                        except OSError:
                            pass
                except OSError:
                    continue
    except OSError:
        pass

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager",
        ) as manager:
            for root in subkeys(manager):
                try:
                    with winreg.OpenKey(manager, rf"{root}\UserSyncRoots") as user_roots:
                        for _, data in values(user_roots):
                            if isinstance(data, str) and data:
                                yield data, f"Cloud-Synchronisierung ({root})"
                except OSError:
                    continue
    except OSError:
        pass


def sync_roots() -> list[tuple[str, str]]:
    """Alle bekannten synchronisierten Wurzelordner dieses Benutzers."""
    roots: list[tuple[str, str]] = []
    for variable in _ONEDRIVE_VARIABLES:
        value = os.environ.get(variable)
        if value:
            roots.append((value, f"Umgebungsvariable {variable}"))
    roots.extend(_registry_roots())
    return roots


def _file_attributes(path: str) -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes

    get_attributes = ctypes.windll.kernel32.GetFileAttributesW
    get_attributes.argtypes = [ctypes.c_wchar_p]
    get_attributes.restype = ctypes.c_uint32
    value = int(get_attributes(path))
    return None if value == INVALID_FILE_ATTRIBUTES else value


def _cloud_attribute_reason(path: Path) -> str | None:
    """Ob der Pfad oder ein vorhandener Elternordner Cloud-Attribute trägt."""
    for candidate in (path, *path.parents):
        attributes = _file_attributes(str(candidate))
        if attributes is not None and attributes & CLOUD_ATTRIBUTES:
            return f"{candidate} ist ein Cloud-Ordner (Dateiattribute)"
    return None


def synced_folder_reason(path: str | Path) -> str | None:
    """Warum ``path`` in einem synchronisierten Ordner liegt, oder ``None``."""
    text = str(path or "").strip()
    if not text:
        return None
    lowered = text.casefold()
    for marker in _SHAREPOINT_MARKERS:
        if marker in lowered:
            return "SharePoint-/WebDAV-Pfad"
    target = _normalise(text)
    # Die Ordner, die OneDrive selbst anlegt, heißen "OneDrive" oder
    # "OneDrive - Firma". Greift auch ohne angemeldetes Konto, etwa bei einem
    # Pfad, der von einem anderen PC übernommen wurde.
    for part in PureWindowsPath(target).parts:
        if part == "onedrive" or part.startswith("onedrive - "):
            return f"Ordner {part!r} gehört zu OneDrive"
    for root, origin in sync_roots():
        normalised_root = _normalise(root)
        if normalised_root and (
            target == normalised_root or target.startswith(normalised_root + "\\")
        ):
            return f"liegt in {root} ({origin})"
    try:
        return _cloud_attribute_reason(Path(os.path.expandvars(text)))
    except (OSError, ValueError):
        return None


def is_synced_folder(path: str | Path) -> bool:
    return synced_folder_reason(path) is not None


def ensure_not_synced(path: str | Path, purpose: str) -> None:
    """Einen Pfad ablehnen, der in einem synchronisierten Ordner liegt."""
    reason = synced_folder_reason(path)
    if reason:
        raise SyncedFolderError(
            f"{purpose} darf nicht in einem OneDrive- oder SharePoint-Ordner liegen: "
            f"{path} ({reason}). Bitte eine Netzwerkfreigabe (\\\\SERVER\\Freigabe) "
            "oder einen lokalen Ordner außerhalb von OneDrive verwenden."
        )


__all__ = [
    "SyncedFolderError",
    "ensure_not_synced",
    "is_synced_folder",
    "sync_roots",
    "synced_folder_reason",
]
