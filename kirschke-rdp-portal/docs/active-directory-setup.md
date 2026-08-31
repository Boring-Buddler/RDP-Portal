# Active-Directory-Einrichtung

Die Portal-App speichert den gewünschten RDP-Zugriff zentral und kann ihn auf
explizite Bestätigung in eine AD-Gruppe `RDP-<Maschinen-ID>` übernehmen.

## Einmalige Vorbereitung

Auf einem AD-Verwaltungsrechner PowerShell als Administrator starten und RSAT
installieren:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deployment\setup-active-directory.ps1 -InstallRsat
```

Anschließend Gruppen zunächst ohne Änderungen prüfen und danach anlegen:

```powershell
.\deployment\setup-active-directory.ps1 -CreateGroups -WhatIf
.\deployment\setup-active-directory.ps1 -CreateGroups
```

Für eine bestimmte Organisationseinheit kann `-OrganizationalUnit` mit dem
Distinguished Name verwendet werden. Beispiel:

```powershell
.\deployment\setup-active-directory.ps1 -CreateGroups -OrganizationalUnit "OU=Gruppen,DC=kirschke,DC=local"
```

## Rechte und Zielrechner

Dem späteren Portal-Admin nur Änderungsrechte für die Gruppen `RDP-WS-*`
delegieren. Die jeweilige Gruppe muss anschließend auf dem passenden
Zielrechner Mitglied von **Remotedesktopbenutzer** sein, idealerweise über eine
Gruppenrichtlinie. Der Portal-Admin benötigt keine lokalen Administratorrechte
auf den Zielrechnern.

## Anwendung im Portal

Im Admin-Reiter Maschine auswählen, **RDP-Zugriff** öffnen und Benutzer wählen
oder manuell eintragen. **Nur speichern** ändert ausschließlich den gemeinsamen
Portalstand; **In AD übernehmen** zeigt die Zielmitgliedschaft nochmals an und
gleicht erst nach Bestätigung die direkte AD-Gruppenmitgliedschaft ab.
