# KI-Ausführungsplan und Konventionen

**Version:** 1.0  
**Stand:** 16. September 2026  
**Ziel:** Konsistente Zusammenarbeit zwischen menschlichem Entwickler und KI-Agenten

---

## 1. Git- und Commit-Konventionen

### Commit-Nachrichten
- **Format:** `v<Version>: <kurze Beschreibung>`
- **Beispiele:**
  - `v0.6.2: Live-Status-Polling Intervall konfigurierbar`
  - `v0.6.1: Versionsnummer in Setup-Fenstern`
  - `fix: Agent-Zuordnung bei abweichender ID`
- **Sprache:** Deutsch, wenn der Commit eine deutsche Beschreibung hat
- **Git-Commits selbst nur erstellen, wenn sie ausdrücklich angefordert werden**

### Branch-Strategie
- **Main-Branch:** `main` - immer stabil
- **Feature-Branches:** `feature/<kurzbeschreibung>` - für neue Funktionen
- **Fix-Branches:** `fix/<problem>` - für Bugfixes
- **KI-Arbeit:** Immer in einem dedizierten Branch, nie direkt auf `main`
- **Merge:** Nur nach Review und Test

---

## 2. UI-Entwicklung und Abnahme

### Visuelle Prüfung (Pflicht nach jeder UI-Änderung)
- [ ] Kontrastverhältnisse (WCAG-AA: mindestens 4.5:1 für Text)
- [ ] Lesbarkeit bei allen Themen (Hell/Dunkel)
- [ ] Abstände (Padding/Margins) konsistent mit Design-System
- [ ] Schaltflächenzustände (Normal, Hover, Active, Disabled, Focus)
- [ ] Hochskalierung (High-DPI) ohne Artefakte
- [ ] Tastaturbedienbarkeit (Tab-Order, Fokusindikatoren)
- [ ] Kirschke-Corporate-Design-Tokens korrekt angewendet

### Render-Check
```bash
# Vor dem Commit ausführen
python -m portal_app.app
# Visuell prüfen:
# - Alle Maschinenkarten
# - Detailansichten
# - Dialoge und Modalfenster
# - Admin-Bereich
```

---

## 3. Code-Qualität und Tests

### Vor jedem Commit
- [ ] `ruff check` - Linting sauber
- [ ] `pytest` - Alle Tests grün (aktuell: 327 tests)
- [ ] `mypy` - Typprüfung (123 bekannte Findings, kein neues `Any`)
- [ ] Keine neuen `noqa`-Kommentare ohne Begründung

### Test-Anforderungen für neue Features
- [ ] Unit-Tests für neue Module
- [ ] Integrationstests für Schnittstellen
- [ ] UI-Tests für neue Dialoge (falls zutreffend)
- [ ] Visuelle Prüfung dokumentiert

### Per-File-Ignores
- Neue Ignorierungen in `pyproject.toml` dokumentieren
- Immer mit Kommentar versehen, warum die Regel deaktiviert wird

---

## 4. KI-spezifische Anweisungen

### Arbeitsmodus
- **Niemals direkt auf `main` arbeiten** - Immer Branch erstellen
- **Änderungen minimal halten** - Nur was angefordert wurde
- **Vor dem Editieren lesen** - Datei vollständig verstehen
- **Nach dem Editieren testen** - Code muss laufen

### Durchschnitt
- **Niemals angenommenen Code als faul annehmen**
- **Immer validieren:**
  - Pfade existieren
  - Importe funktionieren
  - Typen passen
  - Keine Syntaxfehler

### Dokumentation
- **Jede Änderung, die Verhalten oder Konfiguration betrifft, muss in README.md dokumentiert werden**
- **Neue Features** → Features-Liste aktualisieren
- **Breaking Changes** → Migration-Hinweise ergänzen
- **Sicherheitsrelevante Änderungen** → Security Notes aktualisieren

---

## 5. Projekt-spezifische Konventionen

### Dateinamen
- **Python:** `snake_case.py`
- **MD-Dokumente:** `kebab-case.md`
- **Tests:** `test_<modul>.py`

### Code-Stil
- **String-Quotes:** Doppelanführungszeichen (`"`) für Strings
- **Line Length:** 88 Zeichen (Ruff Standard)
- **Imports:** Gruppe nach Typ (Standard Library, Third Party, Local), alphabetisch
- **Typ-Hints:** Immer angeben, `from __future__ import annotations` nutzen

### Logging
- **Level:** INFO für normale Operationen, WARNING für problematische Zustände
- **Format:** `"%(asctime)s %(levelname)s %(name)s: %(message)s"`
- **Datei:** `%LOCALAPPDATA%\KirschkeRDPPortal\logs\portal.log`

---

## 6. Sicherheitscheckliste für KI-Arbeit

### ⚠️ NIEMALS tun
- [ ] Passwörter oder Secrets im Code hinterlassen
- [ ] `shell=True` in `subprocess` verwenden
- [ ] Unvalidierte Benutzereingaben in RDP-Dateien schreiben
- [ ] Relative Pfade für `CreateProcess` verwenden
- [ ] Admin-Rechte ohne explizite Bestätigung verwenden
- [ ] Fremde Befehle ausführen (kein `eval`, kein `exec`)

### ✅ Immer prüfen
- [ ] Alle Pfade sind absolut (z.B. `C:\Windows\System32\mstsc.exe`)
- [ ] Alle Eingaben werden validiert
- [ ] Alle temporären Dateien werden gelöscht
- [ ] Keine Klartext-Passwörter in Logs
- [ ] Rate-Limiting für sensible Operationen
- [ ] ETag-Konflikte werden korrekt behandelt

---

## 7. Abnahmekriterien für KI-generierten Code

### Vor dem Merge
- [ ] Code wurde von menschlichem Entwickler geprüft
- [ ] Alle Tests passieren
- [ ] Linting ist sauber
- [ ] UI wurde visuell geprüft (falls zutreffend)
- [ ] Dokumentation ist aktualisiert
- [ ] Keine neuen Sicherheitsprobleme eingeführt
- [ ] Keine doppelten oder widersprüchlichen Anweisungen

---

## 8. Häufige Fallstricke und Lösungen

### Problem: `ruff check` schlägt fehl
**Lösung:** Fehler analysieren, Code anpassen, nicht blind ignorieren

### Problem: Tests schlagen fehl
**Lösung:** Test lesen, Verständnis für den Fehler entwickeln, dann beheben

### Problem: UI sieht falsch aus
**Lösung:** Kirschke-Design-Tokens prüfen, Farbwerte vergleichen

### Problem: Importfehler
**Lösung:** Immer absolute Importe verwenden, Pfad in `sys.path` prüfen

---

*Dieses Dokument ist verbindlich für alle KI-Agenten, die am Projekt arbeiten.*
