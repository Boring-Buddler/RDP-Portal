"""Atomic file replacement and cooperative locking for local and SMB storage.

Die Sperre ist eine Byte-Sperre, die der SMB-Server für alle Clients
durchsetzt; sie schützt damit auch Portale auf verschiedenen PCs, die dieselbe
Freigabe beschreiben. Für OneDrive-Kopien gilt das nicht -- jede Kopie hätte
ihre eigene Sperre --, deshalb lehnt :mod:`shared.sync_guard` solche Ordner ab.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

#: Wie lange ein Ersetzen wiederholt wird, das an einem gerade lesenden Client
#: scheitert. Ein Lesevorgang dauert Millisekunden.
REPLACE_RETRY_SECONDS = 2.0


def _replace_with_retry(source: str, target: Path) -> None:
    """``os.replace``, das einen kurz offenen Leser auf der Freigabe abwartet.

    Liest ein anderes Portal die Datei genau in diesem Moment, verweigert
    Windows das Ersetzen mit einer Freigabeverletzung. Das ist kein Konflikt,
    sondern ein Augenblick -- nach wenigen Millisekunden ist die Datei frei.
    """
    deadline = time.monotonic() + REPLACE_RETRY_SECONDS
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as stream:
            name = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_with_retry(name, path)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


@contextmanager
def file_lock(path: Path, timeout: float = 3.0):
    """Lock a permanent sidecar; the OS releases its byte lock after a crash."""
    import msvcrt

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Gemeinsamer Speicher ist durch einen anderen Schreibvorgang belegt.") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
