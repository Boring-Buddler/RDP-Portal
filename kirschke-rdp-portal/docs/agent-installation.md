# Kirschke RDP-Agent installieren

Stand 11.09.2026: Portal 0.2.12, Agent 1.3.0. Siehe auch
[Prüfbericht und Pilotabnahme](code-review-testbetrieb.md).

Der Agent liest auf dem Ziel-PC die Windows-Sitzungen über die WTS-API. Er läuft
rechnerweit als SYSTEM in einer geplanten Aufgabe, startet beim Hochfahren und
benötigt keinen angemeldeten Benutzer. Der direkte Kanal akzeptiert Statusabfragen
und eng geprüfte Abmeldungen einer exakt identifizierten aktuellen Sitzung.

## Voraussetzungen

- Windows-Zielrechner mit aktiviertem Remotedesktop;
- lokale Administratorrechte für die Installation;
- feste Maschinen-ID im Portal, zum Beispiel `WS-004`;
- lokaler Statuspfad, standardmäßig `C:\RDP-Portal-Daten\agenten-status`.

Das Agent-Setup erstellt bei der ersten Installation standardmäßig:

- `C:\RDP-Portal-Daten\agenten-status` für den SYSTEM-Agenten;
- `\\ZIELRECHNER\RDP-Status` als lesbare Freigabe;
- das lokale reine Lesekonto `ZIELRECHNER\PortalLeser`.

Das Setup verleiht `PortalLeser` weder Administrator- noch RDP-Rechte. Wenn eine
Unternehmensrichtlinie Skripte oder unsignierte EXE-Dateien blockiert, ist eine
reguläre IT-Freigabe erforderlich. Setup und Hilfsskripte setzen keine
`ExecutionPolicy Bypass`.

Agent 1.3.0 führt die eigentliche Installation nativ aus. Die Setup-EXE startet
intern kein `Install-Agent.ps1` mehr und funktioniert daher auch bei einer
PowerShell-Ausführungsrichtlinie, die lokale Skripte sperrt. Administratorrechte
und eine mögliche Freigabe der unsignierten Setup-EXE durch die
Anwendungssteuerung bleiben erforderlich. Das Setup verändert keine Richtlinie.
`Statusfreigabe-einrichten.ps1` bleibt nur als separates Werkzeug für eine
administrativ vorab eingerichtete Freigabe im Testpaket enthalten.

## Agent installieren

`Kirschke-RDP-Agent-Setup.exe` auf den Zielrechner kopieren, als Administrator
starten und eintragen:

1. **Maschinen-ID im Portal:** exakt die ID der Portalmaschine, z. B. `WS-004`.
2. **Lokaler Statusordner auf diesem Zielrechner:**
   `C:\RDP-Portal-Daten\agenten-status`.
3. **SMB-Fallback und Lesekonto einrichten:** aktiviert lassen.
4. **Kennwort für PortalLeser:** bei der ersten Einrichtung ein neues, ausreichend
   komplexes Kennwort zweimal eingeben und im Passwortmanager aufbewahren.
5. **Aktualisierung:** normalerweise 30 Sekunden.

Mit **Jetzt installieren** prüft das Setup die Schreibberechtigung, installiert
nach `%ProgramFiles%\KirschkeRDPAgent`, speichert Konfiguration und Verlauf unter
`%ProgramData%\KirschkeRDPAgent`, ersetzt bekannte Altinstallationen und startet
die Aufgabe `Kirschke RDP Agent - Machine` als SYSTEM.

Bei der ersten Einrichtung erzeugt es zusätzlich das lokale Konto
`ZIELRECHNER\PortalLeser`, setzt dessen Kennwort als nicht ablaufend und erstellt
`\\ZIELRECHNER\RDP-Status`. Auf Freigabe und Ordner besitzt PortalLeser nur
Leserechte; SYSTEM und lokale Administratoren besitzen Vollzugriff. Das Kennwort
wird weder in der Agent-Konfiguration noch in einer Befehlszeile gespeichert.

Sind Konto und passende Freigabe bei einem Update bereits vollständig vorhanden,
bleiben die Kennwortfelder leer und beide Objekte werden unverändert weiterverwendet.
Ein nur teilweise vorhandener oder auf einen anderen Ordner zeigender Bestand wird
bewusst nicht automatisch überschrieben.

Das entpackte Agentpaket enthält für verwaltete, bereits freigegebene
PowerShell-Umgebungen weiterhin die optionale unbeaufsichtigte Installation:

```powershell
.\Install-Agent.ps1 -NoUi -WorkstationId "WS-004" `
  -StatusDirectory "C:\RDP-Portal-Daten\agenten-status" `
  -SourceDirectory "C:\Pfad\zum\Agent-Paket" -StartNow
```

Ist die Skriptausführung gesperrt, nicht mit einer Umgehungsoption starten, sondern
die neue Setup-EXE verwenden oder die Richtlinie regulär durch die IT freigeben lassen.

## Portal pro Maschine verbinden

Im Portal die betreffende Maschine öffnen und **Details → Datei-Fallback
einrichten …** wählen. Für NB12KI beispielsweise:

- Netzwerkordner: `\\NB12KI\RDP-Status`
- Freigabebenutzer: `NB12KI\PortalLeser`
- Kennwort: das bei der Freigabeeinrichtung gesetzte Kennwort

Der Pfad gilt nur für diese Maschine und wird clientlokal gespeichert. Das
Kennwort verbleibt auf Wunsch in der Windows-Anmeldeinformationsverwaltung und
wird nicht in Portaldateien geschrieben. Die Liveabfrage bleibt vorrangig; die
JSON dient nur bei einem Ausfall des direkten Kanals als Fallback.

Nach der Verbindung muss die Karte **Live** oder **Datei-Fallback** mit Alter
anzeigen. Eine grüne Karte ist online und frei, eine blaue online und belegt. Grau
bedeutet, dass kein aktueller Agentstatus bestätigt ist; ein erfolgreicher Ping
allein genügt nicht.

## Deinstallieren

```powershell
.\Kirschke-RDP-Agent-Setup.exe --uninstall
```

Die Deinstallation entfernt Aufgabe, Programmdateien und Konfiguration. Konto,
Freigabe und Statusdaten bleiben zum Schutz vorhandener Zugänge und Daten bestehen.
Statusdaten werden nicht als Fernbefehl verarbeitet oder zur Abmeldung verwendet.
