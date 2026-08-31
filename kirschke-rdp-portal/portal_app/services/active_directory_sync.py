"""Explicit, credential-free Active Directory synchronization for RDP groups."""

from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveDirectorySyncResult:
    success: bool
    added: list[str]
    removed: list[str]
    message: str


def sync_rdp_group_members(group_name: str, accounts: list[str]) -> ActiveDirectorySyncResult:
    """Make direct user members of one AD group match the selected accounts.

    PowerShell uses the current Windows logon token.  No password is accepted,
    persisted, or written to the event log.  Nested groups are not touched.
    """
    payload = base64.b64encode(
        json.dumps({"group": group_name, "accounts": accounts}, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory -ErrorAction Stop
$payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json
$group = Get-ADGroup -Identity $payload.group -ErrorAction Stop
$desired = @()
foreach ($account in @($payload.accounts)) {{
    $account = [string]$account
    if ($account -like '*@*') {{
        $upn = $account.Replace("'", "''")
        $matches = @(Get-ADUser -Filter "UserPrincipalName -eq '$upn'" -ErrorAction Stop)
        if ($matches.Count -ne 1) {{ throw "Benutzerkonto nicht eindeutig gefunden: $account" }}
        $desired += $matches[0]
    }} else {{
        $sam = ($account -split '\\')[-1]
        $desired += Get-ADUser -Identity $sam -ErrorAction Stop
    }}
}}
$current = @(Get-ADGroupMember -Identity $group -ErrorAction Stop | Where-Object {{ $_.objectClass -eq 'user' }})
$desiredById = @{{}}
foreach ($user in $desired) {{ $desiredById[$user.ObjectGUID.ToString()] = $user }}
$currentById = @{{}}
foreach ($member in $current) {{ $currentById[$member.ObjectGUID.ToString()] = $member }}
$toAdd = @($desiredById.Keys | Where-Object {{ -not $currentById.ContainsKey($_) }} | ForEach-Object {{ $desiredById[$_] }})
$toRemove = @($currentById.Keys | Where-Object {{ -not $desiredById.ContainsKey($_) }} | ForEach-Object {{ $currentById[$_] }})
foreach ($user in $toAdd) {{ Add-ADGroupMember -Identity $group -Members $user -ErrorAction Stop }}
foreach ($user in $toRemove) {{ Remove-ADGroupMember -Identity $group -Members $user -Confirm:$false -ErrorAction Stop }}
[PSCustomObject]@{{
    added = @($toAdd | ForEach-Object {{ $_.SamAccountName }})
    removed = @($toRemove | ForEach-Object {{ $_.SamAccountName }})
}} | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ActiveDirectorySyncResult(False, [], [], f"AD-Übernahme konnte nicht gestartet werden: {exc}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unbekannter PowerShell-Fehler").strip()
        return ActiveDirectorySyncResult(False, [], [], f"AD-Übernahme fehlgeschlagen: {detail}")
    try:
        data = json.loads(result.stdout.strip() or "{}")
        added = [str(value) for value in data.get("added", [])]
        removed = [str(value) for value in data.get("removed", [])]
    except (TypeError, ValueError, AttributeError) as exc:
        return ActiveDirectorySyncResult(False, [], [], f"AD-Übernahme lieferte keine gültige Antwort: {exc}")
    return ActiveDirectorySyncResult(
        True,
        added,
        removed,
        f"AD-Gruppe {group_name} abgeglichen: {len(added)} hinzugefügt, {len(removed)} entfernt.",
    )


__all__ = ["ActiveDirectorySyncResult", "sync_rdp_group_members"]
