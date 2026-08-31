# RDP-Portal: Anleitung zum Pilotbetrieb

Diese Anleitung trennt bewusst zwischen Aufgaben im Portal, Aufgaben in Active
Directory (AD) und Aufgaben auf den Zielrechnern. Zuerst mit **einer**
Testmaschine und **einem** Testnutzer arbeiten.

## 1. Vorab klären

- Ist das Firmennetz eine klassische Windows-Domäne mit Active Directory?
- Welcher Rechner ist ein AD-Verwaltungsrechner oder Domain Controller?
- Wer darf dort Gruppen und Gruppenrichtlinien ändern?
- Welche Maschine soll zuerst getestet werden, zum Beispiel `WS-001`?
- Welcher Nutzer darf testweise RDP-Zugriff erhalten?

Nicht in KI-Chats teilen: Kennwörter, Zugangstoken, vollständige `ipconfig`-
Ausgaben, interne IP-Listen, Screenshots mit personenbezogenen Daten oder
AD-Strukturen.

### Sichere KI-Hilfe

Diese Prompts sind unkritisch, wenn Namen und Domänen anonymisiert werden:

> Wir verwenden Windows Active Directory. Erkläre mir, wie ich einer
> Sicherheitsgruppe ausschließlich Rechte zur Verwaltung einer anderen
> Sicherheitsgruppe delegiere.

> Erkläre mir in deutscher Windows Server-Verwaltung, wie ich eine
> AD-Sicherheitsgruppe per Gruppenrichtlinie zur lokalen Gruppe
> „Remotedesktopbenutzer“ eines einzelnen PCs hinzufüge.

> Prüfe diese PowerShell-Ausgabe auf fehlende RSAT-Komponenten. Entferne dabei
> alle Benutzernamen, Servernamen und IP-Adressen.

## 2. AD-Werkzeuge vorbereiten

Diese Schritte auf einem AD-Verwaltungsrechner ausführen, nicht auf einem
beliebigen Arbeitsplatz. PowerShell als Administrator starten und im
Projektordner ausführen:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deployment\setup-active-directory.ps1 -InstallRsat
```

Danach einmal prüfen, ohne etwas anzulegen:

```powershell
.\deployment\setup-active-directory.ps1 -CreateGroups -WhatIf
```

Wenn die Vorschau korrekt ist, Gruppen für die aktuell bekannten Maschinen
anlegen:

```powershell
.\deployment\setup-active-directory.ps1 -CreateGroups
```

Das erzeugt zum Beispiel `RDP-WS-001` und `RDP-WS-002`. Bei einer eigenen
Organisationseinheit den Pfad vorher mit der IT abstimmen:

```powershell
.\deployment\setup-active-directory.ps1 -CreateGroups `
  -OrganizationalUnit "OU=Gruppen,DC=beispiel,DC=local"
```

## 3. Adminrechte sauber vergeben

1. In AD die Sicherheitsgruppe `RDP-Portal-Admins` anlegen.
2. Nur die Personen aufnehmen, die Portalrechte verwalten dürfen.
3. Dieser Gruppe ausschließlich Änderungsrechte für die Gruppen `RDP-WS-*`
   delegieren — keine pauschalen Domain-Adminrechte vergeben.
4. Den späteren Portal-Admin in `RDP-Portal-Admins` aufnehmen.
5. Danach am Windows-Arbeitsplatz ab- und wieder anmelden, damit die neue
   Gruppenmitgliedschaft im Windows-Anmeldetoken vorhanden ist.

Das Portal prüft diese Mitgliedschaft beim Öffnen des Admin-Reiters. Das
Passwort `Kirschke` ist nur ein Test-Fallback und darf nicht als echte
Sicherheitsgrenze betrachtet werden.

Nach erfolgreichem Pilot die Testfreigabe für den angemeldeten Portalrechner
abschalten und das Portal neu starten:

```powershell
[Environment]::SetEnvironmentVariable("RDP_PORTAL_ALLOW_TEST_ADMIN_PASSWORD", "false", "User")
```

Danach öffnet ausschließlich die Windows-Gruppe `RDP-Portal-Admins` den
Admin-Reiter. Für die Rückkehr zur Testfreigabe den Wert wieder auf `true`
setzen oder die Umgebungsvariable entfernen.

## 4. Zielrechner für RDP berechtigen

Für jede Maschine wird genau ihre Gruppe verwendet:

| Zielrechner | AD-Gruppe |
|---|---|
| `WS-001` | `RDP-WS-001` |
| `WS-002` | `RDP-WS-002` |

In der Gruppenrichtlinienverwaltung (GPMC) eine Richtlinie für den jeweiligen
Zielrechner bzw. die passende Computer-OU erstellen. Die zugehörige
`RDP-WS-...`-Gruppe der lokalen Gruppe **Remotedesktopbenutzer** hinzufügen.
Zusätzlich prüfen, dass die Windows-Richtlinie „Anmelden über
Remotedesktopdienste zulassen“ die Gruppe nicht ausschließt.

Auf dem Zielrechner anschließend ausführen oder neu starten:

```powershell
gpupdate /force
```

## 5. Pilot im Portal durchführen

1. Portal starten und in **Admin** wechseln.
2. Prüfen, ob die Statusanzeige die Windows-Gruppe bestätigt.
3. Testmaschine auswählen → **RDP-Zugriff**.
4. Testnutzer aus der Liste wählen oder manuell im Format
   `DOMÄNE\benutzer` beziehungsweise `benutzer@firma.de` eingeben.
5. Zuerst **Nur speichern** wählen und die Mitgliedschaft prüfen.
6. Danach erneut öffnen → **In AD übernehmen** → Zielmitgliedschaft prüfen →
   bestätigen.
7. Mit dem Testnutzer eine RDP-Verbindung aufbauen.
8. Im **Logs**-Reiter den Eintrag zum erteilten Zugriff und zum AD-Abgleich
   kontrollieren.
9. Zum Rücktest den Nutzer wieder entfernen, erneut in AD übernehmen und den
   fehlenden RDP-Zugriff bestätigen.

## 6. Häufige Probleme

| Meldung / Verhalten | Wahrscheinliche Ursache | Nächster Schritt |
|---|---|---|
| „ActiveDirectory-Modul fehlt“ | RSAT fehlt | Schritt 2 auf Verwaltungsrechner ausführen. |
| „Zugriff verweigert“ beim AD-Abgleich | Windows-Konto hat keine delegierten Gruppenrechte | Schritt 3 mit der IT prüfen. |
| Portaladmin wird nicht erkannt | Neues Gruppentoken noch nicht geladen | Windows ab- und wieder anmelden. |
| AD-Abgleich erfolgreich, RDP scheitert | Zielrechner-GPO fehlt oder ist noch nicht angewendet | Schritt 4 und `gpupdate /force` prüfen. |
| Nur Passwort `Kirschke` öffnet Admin | AD-Gruppe ist noch nicht eingerichtet | Pilot nur kontrolliert fortsetzen, danach Test-Fallback deaktivieren. |

## 7. Abnahme vor breiter Nutzung

- Testnutzer kann nur auf die vorgesehene Maschine zugreifen.
- Entfernen eines Nutzers entzieht den Zugriff nachvollziehbar.
- Portal-Log und `portal-events.jsonl` enthalten die Änderungen.
- Zwei berechtigte Admins können den Ablauf nachvollziehen.
- Der Test-Fallback ist deaktiviert und der Admin-Zugang basiert nur auf
  `RDP-Portal-Admins`.
