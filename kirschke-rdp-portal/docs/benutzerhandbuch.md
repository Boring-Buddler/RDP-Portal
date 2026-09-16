# Kirschke RDP Workstation Portal - Benutzerhandbuch

**Version:** 0.6.1  
**Stand:** 16. September 2026  
**Zielgruppe:** Endbenutzer, Administratoren, IT-Support

---

## Inhaltsverzeichnis

1. [Einleitung](#1-einleitung)
2. [Systemvoraussetzungen](#2-systemvoraussetzungen)
3. [Installation](#3-installation)
4. [Erste Schritte](#4-erste-schritte)
5. [Benutzeroberfläche](#5-benutzeroberfläche)
6. [Maschinenverwaltung](#6-maschinenverwaltung)
7. [RDP-Verbindungen](#7-rdp-verbindungen)
8. [Sitzungsverwaltung](#8-sitzungsverwaltung)
9. [Reservierungssystem](#9-reservierungssystem)
10. [Agent-Status und Live-Überwachung](#10-agent-status-und-live-überwachung)
11. [Administrationsbereich](#11-administrationsbereich)
12. [Diagnose- und Hilfstools](#12-diagnose--und-hilfstools)
13. [Sicherheit](#13-sicherheit)
14. [Fehlerbehebung](#14-fehlerbehebung)
15. [Häufig gestellte Fragen](#15-häufig-gestellte-fragen)

---

## 1. Einleitung

Das **Kirschke RDP Workstation Portal** ist eine Windows-Anwendung zur Verwaltung von Arbeitsplatzrechnern mit RDP-Verbindungen, Sitzungsverfolgung und Administrationsfunktionen. Es wurde speziell für den Einsatz in Büroumgebungen mit Microsoft Active Directory oder lokaler Benutzerverwaltung entwickelt.

### Hauptfunktionen

- Übersicht aller Arbeitsstationen in einer zentralen Oberfläche
- Einfacher Aufbau von RDP-Verbindungen zu Zielmaschinen
- Sitzungsverfolgung und -protokollierung
- Reservierungssystem für Arbeitsplätze
- Echtzeit-Statusüberwachung durch Agenten
- Administrator-Funktionen für Benutzerverwaltung
- Diagnosetools für Netzwerk und Verbindungen

---

## 2. Systemvoraussetzungen

### Mindestanforderungen

| Komponente | Anforderung |
|------------|-------------|
| Betriebssystem | Windows 10/11 oder Windows Server 2019/2022 |
| Python-Version | 3.12 oder höher |
| RAM | 4 GB (empfohlen: 8 GB) |
| Festplattenspeicher | 500 MB frei |
| Bildschirmauflösung | 1280x720 (empfohlen: 1920x1080) |

### Optionale Komponenten

- **Active Directory:** Für die Integration in Domänenumgebungen
- **SMB-Freigaben:** Für den Zugriff auf Agenten-Statusdateien
- **PowerShell 5.1 oder höher:** Für einige Administrationsskripte

---

## 3. Installation

### Variante A: Portable Version (empfohlen für Testbetrieb)

1. Laden Sie das Installationspaket `Kirschke-RDP-Portal-Setup.exe` herunter
2. Führen Sie die Datei als Administrator aus
3. Folgen Sie den Anweisungen des Installationsassistenten
4. Starten Sie das Portal über die erstellte Verknüpfung

**Hinweis:** Die portable Version enthält alle benötigten Abhängigkeiten und erfordert keine separate Python-Installation.

### Variante B: Entwicklerinstallation

Für Entwickler oder fortgeschrittene Benutzer:

```powershell
# Projektverzeichnis öffnen
cd C:\Pfad\zum\kirschke-rdp-portal

# Virtuelle Umgebung erstellen
python -m venv .venv

# Virtuelle Umgebung aktivieren
.\.venv\Scripts\Activate.ps1

# Abhängigkeiten installieren
pip install --upgrade pip
pip install -e ".[dev]"

# Portal starten
python -m portal_app.app
```

### Agent-Installation

Der Agent wird auf den Zielrechnern benötigt, um Sitzungsinformationen bereitzustellen:

1. Führen Sie `Kirschke-RDP-Agent-Setup.exe` als Administrator auf dem Zielrechner aus
2. Der Assistent richtet automatisch:
   - Eine geplante Aufgabe für den Agenten-Dienst
   - Ein Lesekonto `PortalLeser` (optional)
   - Eine Freigabe `RDP-Status` (optional)
3. Der Agent startet automatisch und meldet Sitzungsstatus

**Wichtig:** Der Agent benötigt keine Python-Installation auf dem Zielrechner.

---

## 4. Erste Schritte

### Portal starten

Nach der Installation starten Sie das Portal durch:
- Doppelklick auf die Desktop-Verknüpfung "Kirschke RDP Portal"
- Oder Ausführen von `Kirschke-RDP-Portal.exe` im Installationsverzeichnis

### Anmeldung

Beim ersten Start:
1. Das Portal erkennt automatisch Ihr Windows-Konto
2. Für den Admin-Bereich müssen Sie sich authentifizieren:
   - Entweder über Active Directory-Gruppe `RDP-Portal-Admins`
   - Oder über das lokale Admin-Passwort (falls aktiviert)

### Passwort für lokalen Admin einrichten

1. Klicken Sie auf **Admin** in der oberen Navigationsleiste
2. Wählen Sie **Lokales Admin-Passwort einrichten**
3. Vergeben Sie ein sicheres Passwort
4. Das Passwort wird als Hash gespeichert (nicht im Klartext)

**Sicherheitshinweis:** Nach 5 Fehlversuchen ist der Zugriff für 15 Minuten gesperrt.

---

## 5. Benutzeroberfläche

### Hauptfenster

Das Portalfenster ist in folgende Bereiche unterteilt:

```
┌─────────────────────────────────────────────────────────────┐
│  [Kirschke Logo] Kirschke RDP Workstation Portal    [Admin] │
├─────────────────────────────────────────────────────────────┤
│  🔍 Suchleiste          [Standort ▼] [Status ▼] [Agent ▼]    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │
│  │  WS-001 │ │  WS-002 │ │  WS-003 │ │  WS-004 │          │
│  │ 🟢 Online │ │ 🟡 Warnung│ │ 🔴 Offline│ │ 🟢 Online│          │
│  │ Benutzer │ │ Berechn.│ │ -       │ │ Benutzer │          │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘          │
│                                                             │
│  [Kartenansicht] [Tabellenansicht]                           │
├─────────────────────────────────────────────────────────────┤
│  Status: 4 Maschinen online, 1 Warnung, 1 offline             │
└─────────────────────────────────────────────────────────────┘
```

### Navigationsleiste

| Symbol | Funktion | Beschreibung |
|--------|----------|--------------|
| 🏠 | Start | Zurück zur Übersicht |
| 💻 | Maschinen | Maschinenverwaltung |
| 📋 | Sitzungen | Sitzungsprotokoll |
| 📅 | Reservierungen | Reservierungskalender |
| 🔧 | Verwaltung | Einstellungen |
| 👤 | Admin | Administrationsbereich |

### Farbcodierung der Maschinen

| Farbe | Bedeutung |
|-------|----------|
| 🟢 Grün | Maschine online und verfügbar |
| 🟡 Gelb | Maschine online, aber Warnung (z.B. Berechnung läuft) |
| 🔴 Rot | Maschine offline |
| 🔵 Blau | Eigene Sitzung (durchgezogen oder gestrichelt) |
| 🟣 Violett | Fremde Reservierung oder Sitzung |
| 🟤 Braun | Maschine von jemand anderem belegt |
| ⚪ Grau | Unbekannter Status |

**Randstile:**
- **Durchgezogen (4px):** Eigene Maschine, auf die Sie zugreifen können
- **Gestrichelt (2px):** Maschine, auf die Sie nicht zugreifen können
- **Blau durchgezogen:** Ihre eigene aktive Sitzung
- **Blau gestrichelt:** Ihre eigene Sitzung ohne Fenster

---

## 6. Maschinenverwaltung

### Maschinenübersicht

Die Maschinen können in zwei Ansichten dargestellt werden:

1. **Kartenansicht:** Visuelle Übersicht mit Farbcodierung
2. **Tabellenansicht:** Detaillierte Liste mit allen Eigenschaften

#### Filterfunktionen

- **Standort:** Filtert nach Standort (z.B. Büro 1, Büro 2)
- **Status:** Filtert nach Maschinenstatus (Online, Offline, Warnung)
- **Agent-Status:** Filtert nach Agentenverfügbarkeit
- **Suche:** Volltextsuche nach Maschinenname, IP-Adresse, Benutzer

### Maschinen-Detailansicht

Klicken Sie auf eine Maschinenkarte oder Zeile, um die Detailansicht zu öffnen:

```
┌─────────────────────────────────────────────────────────────┐
│  WS-001 - Details                                          [X] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Grundinformationen                                        │
│  ├─ Name: WS-001                                          │
│  ├─ Standort: Büro 1                                       │
│  ├─ IP-Adresse: 192.168.1.101                             │
│  └─ MAC-Adresse: 00-1A-2B-3C-4D-5E                       │
│                                                             │
│  Aktueller Status                                         │
│  ├─ Online: ✅ Ja                                          │
│  ├─ Letzte Aktualisierung: 14:32:21                        │
│  ├─ Agent-Version: 1.5.0                                  │
│  └─ Sitzungen: 1 aktiv                                    │
│                                                             │
│  [RDP-Zugriff] [Ping testen] [Details bearbeiten]          │
└─────────────────────────────────────────────────────────────┘
```

### Maschinen bearbeiten

Administratoren können Maschineninformationen bearbeiten:

1. Klicken Sie auf **Details bearbeiten** in der Detailansicht
2. Ändern Sie die gewünschten Eigenschaften:
   - Maschinenname
   - Standort
   - IP-Adresse
   - MAC-Adresse
   - Beschreibung
   - Standard-RDP-Profil
3. Speichern Sie die Änderungen

### Neue Maschine hinzufügen

1. Wechseln Sie in den **Admin-Bereich**
2. Wählen Sie **Maschinenverwaltung**
3. Klicken Sie auf **+ Maschine hinzufügen**
4. Geben Sie die Maschineninformationen ein
5. Optional: Wechseln Sie zu **Agent zuordnen**, um einen Agenten zu verknüpfen

---

## 7. RDP-Verbindungen

### Verbindung herstellen

1. Wählen Sie eine Maschine aus der Übersicht
2. Klicken Sie auf **RDP-Zugriff** (oder doppelt auf die Maschinenkarte)
3. Wählen Sie ein Anmeldekonto aus oder fügen Sie ein neues hinzu
4. Wählen Sie eine Auflösung aus den Voreinstellungen:
   - 1280x720
   - 1366x768
   - 1600x900
   - 1920x1080
   - 2560x1440 (2K)
   - 3840x2160 (4K)
   - Alle Monitore
   - Benutzerdefiniert
5. Klicken Sie auf **Verbinden**

### Anmeldekonten verwalten

Jede Maschine kann mehrere Anmeldekonten speichern:

- **Standardkonto:** Wird automatisch vorgeschlagen
- **Weitere Konten:** Können manuell hinzugefügt werden
- **Format:** `DOMÄNE\Benutzername` oder `benutzer@firma.de` oder nur `Benutzername`

#### Neues Konto hinzufügen

1. In der RDP-Zugriffsmaske auf **+ Benutzer hinzufügen** klicken
2. Benutzername eingeben
3. Optional: Anzeigenamen für bessere Identifizierung
4. Speichern

**Hinweis:** Das Portal speichert **keine Passwörter**. Die Windows-Anmeldeinformationsverwaltung übernimmt die Passwortspeicherung auf Wunsch.

### RDP-Profile

Es gibt zwei Arten von RDP-Profilen:

1. **Maschinenprofile:** Spezifisch für eine Maschine
2. **Allgemeine Profile:** Für alle Maschinen verfügbar

#### Profile bearbeiten

1. Wechseln Sie zu **Verwaltung → RDP-Profile**
2. Wählen Sie ein Profil aus oder erstellen Sie ein neues
3. Passen Sie die Einstellungen an:
   - Auflösung
   - Farbtiefe
   - Sound
   - Lokale Ressourcen (Drucker, Clipboard)
   - Netzwerkperformance

---

## 8. Sitzungsverwaltung

### Aktive Sitzungen

In der Detailansicht einer Maschine sehen Sie:

- **Aktive Sitzungen:** Alle derzeit laufenden Sitzungen
- **Letzte Sitzungen:** Historische Sitzungen (filterbar)

```
┌─────────────────────────────────────────────────────────────┐
│  Aktive Sitzungen                                         [X] │
├─────────────────────────────────────────────────────────────┤
│  Benutzer    │ Sitzungs-ID │ Startzeit    │ Typ       │ │
│ ─────────────┼────────────┼──────────────┼───────────┤ │
│  mueller      │ 3           │ 13:45:21     │ RDP       │ │
│  schmidt      │ 1           │ 09:12:45     │ Console   │ │
└─────────────────────────────────────────────────────────────┘
```

### Sitzungsdetails

Klicken Sie auf eine Sitzung für detaillierte Informationen:

- **Benutzername:** Windows-Anmeldename
- **SID:** Windows-Sicherheits-ID
- **Sitzungs-ID:** Interne Windows-Sitzungsnummer
- **Startzeit:** Zeitpunkt der Anmeldung
- **Typ:** RDP, Console oder Disconnected
- **RDP-Client:** Welcher Client die Sitzung gestartet hat

### Sitzungsprotokoll

1. Wechseln Sie zu **Sitzungen** in der Navigationsleiste
2. Filtern Sie nach:
   - Maschine
   - Benutzer
   - Datum
   - Sitzungstyp
3. Exportieren Sie das Protokoll als CSV oder JSON

### Sitzung beenden

**Wichtig:** Das Beenden von Sitzungen ist eine Administrationsfunktion.

1. Wechseln Sie in den **Admin-Bereich**
2. Wählen Sie eine Maschine mit aktiver Sitzung
3. Klicken Sie auf **Sitzung beenden**
4. Wählen Sie die zu beendende Sitzung
5. Geben Sie einen Grund an (Pflichtfeld)
6. Bestätigen Sie mit Administrator-Berechtigungen

**Sicherheitsmechanismen:**
- Nur eigene Sitzungen können ohne Admin-Rechte beendet werden
- Für fremde Sitzungen sind Admin-Rechte erforderlich
- Der Agent prüft, dass die Anfrage vom korrekten Rechner kommt
- Sitzungs-ID, Benutzer und Anmeldezeit müssen übereinstimmen

---

## 9. Reservierungssystem

### Maschinen reservieren

1. Wählen Sie eine Maschine aus
2. Klicken Sie auf **Reservieren**
3. Wählen Sie Datum und Uhrzeit:
   - Reservierungen sind für 2 Wochen im Voraus möglich
   - Mindestdauer: 15 Minuten
   - Maximaldauer: 8 Stunden (konfigurierbar)
4. Optional: Geben Sie eine Notiz ein
5. Bestätigen Sie die Reservierung

### Reservierungskalender

1. Wechseln Sie zu **Reservierungen** in der Navigationsleiste
2. Der Kalender zeigt alle Reservierungen an:
   - **Blau:** Ihre eigenen Reservierungen
   - **Violett:** Reservierungen von anderen Benutzern
   - **Grau:** Vergangene Reservierungen

3. Klicken Sie auf einen Tag für detaillierte Informationen

### Reservierung bearbeiten

Administratoren können Reservierungen verwalten:

1. Wechseln Sie zu **Verwaltung → Reservierungen**
2. Wählen Sie eine Reservierung aus
3. Sie können:
   - Reservierung stornieren
   - Notiz bearbeiten
   - Dauer anpassen
   - Benutzer ändern

**Hinweis:** Der Agent synchronisiert Reservierungen zwischen Portalen. Eine Reservierung auf einem Rechner ist auch auf anderen Portalen sichtbar, die denselben Agenten nutzen.

---

## 10. Agent-Status und Live-Überwachung

### Agenten-Übersicht

Das Portal zeigt den Status jedes Agenten an:

- **🟢 Online:** Agent meldet sich regelmäßig (alle 5-60 Sekunden)
- **🟡 Stale:** Keine Meldung seit 90 Sekunden
- **🔴 Offline:** Keine Meldung seit 5 Minuten

### Live-Status polling

Der Live-Status wird automatisch abgefragt:

- **Standardintervall:** 5 Sekunden
- **Einstellbar:** 2 bis 60 Sekunden
- **Quelle:** Geschützter Agenten-Statuskanal (bevorzugt) oder Datei-Fallback

#### Statuskanal vs. Datei-Fallback

| Methode | Beschreibung | Priorität |
|---------|--------------|-----------|
| Statuskanal | Direkte Kommunikation mit dem Agenten | Hoch |
| Datei-Fallback | Lesen von SMB-Freigabe `\RECHNER\RDP-Status` | Niedrig |

### Agent-Diagnose

Für Administratoren:

1. Wechseln Sie zu **Verwaltung → Agent-Diagnose**
2. Wählen Sie eine Maschine aus
3. Sehen Sie:
   - Agent-Version
   - Letzte Meldung
   - Gelesener Ordnerpfad
   - Alle Statusdateien
   - Zuordnungen

### Agent zuordnen

Falls der Agent eine andere ID hat als die Maschine:

1. Wechseln Sie zur Maschinen-Detailansicht
2. Klicken Sie auf **Agent zuordnen**
3. Wählen Sie den passenden Agenten aus der Liste
4. Speichern Sie die Zuordnung

**Hinweis:** Die Zuordnung bleibt im Inventar gespeichert.

---

## 11. Administrationsbereich

### Zugriff auf den Admin-Bereich

Der Admin-Bereich ist durch folgende Mechanismen geschützt:

1. **Active Directory (empfohlen):**
   - Mitgliedschaft in der Gruppe `RDP-Portal-Admins`
   - Wird automatisch beim Start geprüft

2. **Lokales Passwort (Fallback):**
   - Muss explizit aktiviert sein
   - Passwort-Hash wird lokal gespeichert
   - Rate-Limiting: 5 Versuche, dann 15 Minuten Sperre

### Admin-Funktionen

| Funktion | Beschreibung |
|----------|--------------|
| Benutzerverwaltung | Lokale Benutzer und Rechte verwalten |
| Maschinenverwaltung | Maschinen hinzufügen, bearbeiten, löschen |
| RDP-Profile | Standard-RDP-Einstellungen verwalten |
| Reservierungen | Alle Reservierungen einsehen und verwalten |
| Sitzungsverwaltung | Aktive Sitzungen beenden |
| Agent-Verwaltung | Agenten-Status und -Zuordnungen |
| Diagnose-Tools | Netzwerk- und Systemdiagnose |
| Logs | Portal- und Agent-Logs einsehen |

### Benutzerverwaltung

1. Wechseln Sie zu **Admin → Benutzer**
2. Sie sehen alle lokalen Benutzer
3. Sie können:
   - Neue Benutzer hinzufügen
   - Benutzer bearbeiten
   - Benutzer löschen
   - Rechte zuweisen (Admin, Normaler Benutzer)

### Maschinenverwaltung

1. Wechseln Sie zu **Admin → Maschinen**
2. Sie sehen alle konfigurierten Maschinen
3. Sie können:
   - Neue Maschinen hinzufügen
   - Maschinen bearbeiten
   - Maschinen löschen
   - Agenten zuordnen
   - Standorte verwalten

### Einstellungen

1. Wechseln Sie zu **Admin → Einstellungen**
2. Konfigurieren Sie:
   - **Speicherort:** Lokales Verzeichnis oder SMB-Freigabe
   - **Polling-Intervall:** 2-60 Sekunden
   - **Standard-Resolution:** Voreinstellung für neue Verbindungen
   - **Fallback-Ordner:** Standardpfad für Agenten-Statusdateien

---

## 12. Diagnose- und Hilfstools

### Ping-Tool

1. Wählen Sie eine Maschine aus
2. Klicken Sie auf **Ping testen**
3. Das Tool führt aus:
   - ICMP-Ping
   - TCP-Port-Check (3389 für RDP)
   - Hostname-Auflösung
   - Netzwerkdiagnose

### ipconfig /all anzeigen

1. Wählen Sie eine Maschine aus
2. Klicken Sie auf **Netzwerkinformationen**
3. Das Portal zeigt asynchron die Ausgabe von `ipconfig /all`
4. Kopieren Sie die Ausgabe mit einem Klick

### Diagnose kopieren

1. Klicken Sie auf **Diagnose kopieren** in der Maschinen-Detailansicht
2. Es wird ein vollständiger Prüfbericht erstellt mit:
   - Maschineninformationen
   - Sitzungsstatus
   - Agentenstatus
   - Netzwerkdiagnose
   - Portal-Konfiguration
3. Der Bericht wird in die Zwischenablage kopiert

### Logs

Portal-Logs finden Sie unter:
```
%LOCALAPPDATA%\KirschkeRDPPortal\logs\portal.log
```

Agent-Logs (auf dem Zielrechner):
```
C:\RDP-Portal-Daten\agenten-status\agent.log
```

---

## 13. Sicherheit

### Sicherheitskonzept

Das Portal implementiert folgende Sicherheitsmaßnahmen:

#### Passwortspeicherung

- **Keine Klartextspeicherung:** Passwörter werden nie im Klartext gespeichert
- **Hashing:** Passwörter werden als PBKDF2-HMAC-SHA256 Hash gespeichert
  - 310.000 Iterationen
  - Zufälliger 16-Byte-Salt
- **Rate-Limiting:** 5 Versuche alle 15 Minuten

#### RDP-Dateigenerierung

- **Validierung:** Alle Eingaben werden validiert
- **Injectionschutz:** Steuerzeichen werden abgelehnt
- **Zielvalidierung:** Hostnames werden gegen eine Allowlist geprüft
- **Automatische Bereinigung:** Temporäre .rdp-Dateien werden beim Schließen gelöscht

#### Prozessstart

- **Absolut Pfade:** Alle Prozesse werden mit absoluten Pfaden gestartet
  - Beispiel: `C:\Windows\System32\mstsc.exe` (nicht nur `mstsc.exe`)
- **Kein shell=True:** Verhindert Path-Hijacking
- **Explizite Argumente:** Keine Shell-Interpretation

#### Sitzungsabmeldung

- **Echtheitsprüfung:** Abmeldung erfordert:
  - Übereinstimmende Sitzungs-ID
  - Übereinstimmender Benutzername
  - Übereinstimmende Anmeldezeit
  - Frische Agenten-Antwort (max. 30 Sekunden alt)
  - Einmalige Anfrage-ID
  - Entweder Sitzungsbesitz oder Admin-Rechte

#### Agenten-Kommunikation

- **Sicherheitsdeskriptor:** Der Statuskanal ist eingeschränkt auf:
  - SYSTEM
  - Lokale Administratoren
  - `PortalLeser`-Konto (nur Leserechte)
- **PortalLeser-Konto:**
  - Kein interaktiver Login
  - Kein Remote-Login
  - Kein Batch-Login
  - Kein Service-Login
  - Nur Leserechte auf den Statusordner

#### Datenschutz

- **Keine Protokollierung von Passwörtern** in Logs
- **Keine Speicherung von Benutzerdaten** ohne Zustimmung
- **Lokale Speicherung:** Alle Daten bleiben lokal (außer bei expliziter SharePoint-Integration)

---

## 14. Fehlerbehebung

### Häufige Probleme und Lösungen

| Problem | Ursache | Lösung |
|---------|---------|--------|
| Portal startet nicht | Fehlende Abhängigkeiten | Portable Version verwenden oder `pip install -e .[dev]` |
| Maschinen werden nicht angezeigt | Falscher Speicherort | Speicherort in Admin-Einstellungen prüfen |
| RDP-Verbindung schlägt fehl | Falsche Anmeldedaten | Anmeldekonto prüfen und neu speichern |
| Agent-Status bleibt offline | Agent nicht installiert | Agent auf Zielrechner installieren |
| "Zugriff verweigert" im Admin | Keine Admin-Rechte | AD-Gruppe prüfen oder lokales Passwort verwenden |
| Sitzung kann nicht beendet werden | Keine Berechtigung | Eigene Sitzung oder Admin-Rechte benötigt |
| Portal-language ist Englisch | Windows-Locale | Portal verwendet Windows-Systemsprache |

### Detaillierte Fehleranalyse

#### Problem: Portal startet nicht nach Installation

1. Prüfen Sie die Log-Datei: `%LOCALAPPDATA%\KirschkeRDPPortal\logs\portal.log`
2. Häufige Ursachen:
   - Fehlende Python-Version
   - Beschädigte Installation
   - Berechtigungsprobleme

**Lösung:**
```powershell
# Python-Version prüfen
python --version

# Abhängigkeiten neu installieren
pip install --upgrade --force-reinstall -e .

# Als Administrator starten
Start-Process -FilePath "Kirschke-RDP-Portal.exe" -Verb RunAs
```

#### Problem: Agent bleibt offline

1. Auf dem Zielrechner prüfen:
   ```powershell
   # Planned Task prüfen
   Get-ScheduledTask -TaskName "Kirschke RDP Agent"
   
   # Task-Status prüfen
   Get-ScheduledTaskInfo -TaskName "Kirschke RDP Agent"
   ```

2. Agent-Logs prüfen:
   ```
   C:\RDP-Portal-Daten\agenten-status\agent.log
   ```

3. Manuell starten:
   ```powershell
   # Task manuell ausführen
   Start-ScheduledTask -TaskName "Kirschke RDP Agent"
   ```

#### Problem: RDP-Verbindung scheitert

1. Netzwerkdiagnose durchführen:
   ```powershell
   # Ping-Test
   Test-NetConnection -ComputerName ZIELRECHNER -Port 3389
   ```

2. RDP-Zugriff prüfen:
   - Ist Remotedesktop auf dem Zielrechner aktiviert?
   - Hat der Benutzer Berechtigung für RDP?
   - Ist die Firewall für RDP (Port 3389) geöffnet?

3. Im Portal:
   - Anmeldekonto prüfen
   - Maschinen-IP/Hostname prüfen
   - RDP-Profil-Einstellungen prüfen

### Support kontaktieren

Bei Problemen, die Sie nicht selbst lösen können:

1. **Diagnose kopieren** aus dem Portal
2. **Logs sammeln:**
   - Portal-Logs
   - Agent-Logs (falls verfügbar)
   - Event-Viewer-Logs von Windows
3. **Kontakt:** it@prof-kirschke.de

**Wichtig:** Bitte keine Passwörter oder sensible Daten in Support-Anfragen angeben.

---

## 15. Häufig gestellte Fragen

### Q: Kann ich das Portal ohne Active Directory verwenden?
**A:** Ja, das Portal funktioniert auch ohne AD. In diesem Fall verwenden Sie den lokalen Passwort-Fallback für die Admin-Authentifizierung.

### Q: Wie viele Maschinen kann das Portal verwalten?
**A:** Es gibt keine technische Obergrenze. Die Performance hängt von Ihrer Hardware und Netzwerkverbindung ab. Getestet wurde mit bis zu 200 Maschinen.

### Q: Werden meine RDP-Passwörter im Portal gespeichert?
**A:** Nein, das Portal speichert keine Passwörter. Die Windows-Anmeldeinformationsverwaltung übernimmt die Speicherung auf Wunsch.

### Q: Kann ich das Portal auf mehreren Rechnern gleichzeitig nutzen?
**A:** Ja, aber:
- Bei lokaler JSON-Speicherung hat jeder Rechner sein eigenes Inventar
- Mit SMB-Freigabe oder SharePoint-Integration synchronisieren sich die Daten
- Agenten-Status wird von jedem Portal unabhängig abgefragt

### Q: Was passiert, wenn ich eine Verbindung schließe, ohne mich abzumelden?
**A:** Die Sitzung bleibt auf dem Zielrechner aktiv. Sie können:
- Sich später wieder verbinden (Disconnected Session)
- Die Sitzung über das Portal beenden (falls Admin-Rechte)
- Oder sich manuell am Zielrechner abmelden

### Q: Wie oft wird der Agenten-Status aktualisiert?
**A:** Standardmäßig alle 5 Sekunden. Dies kann in den Einstellungen auf 2-60 Sekunden angepasst werden.

### Q: Kann ich die Farben der Maschinenkarten anpassen?
**A:** Die Farben sind Teil des Kirschke Corporate Designs und können aktuell nicht angepasst werden.

### Q: Funktioniert das Portal mit macOS oder Linux?
**A:** Nein, das Portal ist ausschließlich für Windows entwickelt. Der Agent läuft ebenfalls nur auf Windows.

### Q: Wie deinstalliere ich das Portal?
**A:**
1. Über die Windows-Systemsteuerung: "Programme und Funktionen"
2. Oder führen Sie `Kirschke-RDP-Portal-Uninstall.exe` aus
3. Für Entwicklerinstallationen: Löschen Sie das Projektverzeichnis

### Q: Wie deinstalliere ich den Agenten?
**A:**
1. Über die Windows-Systemsteuerung: "Programme und Funktionen"
2. Oder führen Sie `Kirschke-RDP-Agent-Uninstall.exe` aus
3. Optional: Löschen Sie das Verzeichnis `C:\RDP-Portal-Daten\agenten-status`

---

## Anhang A: Tastaturkürzel

| Kürzel | Funktion |
|--------|----------|
| Strg + F | Suche fokussieren |
| Strg + T | Zwischen Karten- und Tabellenansicht wechseln |
| Strg + R | Seite neu laden |
| Strg + S | Einstellungen speichern (falls geöffnet) |
| Esc | Dialoge schließen |

---

## Anhang B: Glossar

| Begriff | Bedeutung |
|---------|----------|
| AD | Active Directory - Microsoft Verzeichnisdienst |
| RDP | Remote Desktop Protocol |
| SMB | Server Message Block - Netzwerkprotokoll für Dateifreigaben |
| WTS | Windows Terminal Services |
| SID | Security Identifier - Eindeutige Windows-Benutzerkennung |
| UPN | User Principal Name - Benutzeranmeldeinformation (z.B. benutzer@firma.de) |
| Console Session | Direkte Anmeldung am physischen Rechner (nicht über RDP) |

---

## Anhang C: Versionshistorie

| Version | Datum | Wichtige Änderungen |
|---------|-------|---------------------|
| 0.6.1 | 16.09.2026 | Versionsnummer in Setup-Fenstern, BOM für PowerShell-Skripte |
| 0.6.0 | - | SharePoint ist nicht mehr Standard-Speicherort |
| 0.5.5 | - | Synchronisierte Bibliotheken werden erkannt |
| 0.5.3 | - | Eigene Ruhesitzung blau/orange gestrichelt, 2K/4K bis Bildschirmgröße |
| 0.5.2 | - | Unicode-Normalisierung für Benutzernamen |
| 0.5.0 | - | Automatisches Ziel erzwingt keine nicht auflösbaren Namen |
| 0.4.0 | - | Reservierungen werden durch Agenten synchronisiert |

---

*Dokumentation erstellt für Kirschke RDP Workstation Portal v0.6.1*
