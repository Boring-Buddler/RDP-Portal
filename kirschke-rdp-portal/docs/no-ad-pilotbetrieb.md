# RDP-Portal ohne Active Directory

Diese Variante passt für ein kleines Büro ohne zentrale Windows-Domäne. Das
Portal organisiert Maschinen, Reservierungen, Verbindungsstarts und Logs; die
eigentlichen Windows-RDP-Berechtigungen werden einmalig direkt auf den
Zielrechnern eingerichtet.

## 1. Eine Testmaschine vorbereiten

Auf der Zielmaschine:

1. Ein eigenes lokales Windows-Konto für den Test anlegen, zum Beispiel
   `rdp-test`. Kein gemeinsames Standardkonto für mehrere Personen verwenden.
2. **Einstellungen → System → Remotedesktop** öffnen und Remotedesktop
   aktivieren.
3. Das Testkonto zur lokalen Gruppe **Remotedesktopbenutzer** hinzufügen.
4. Die Windows-Firewallregel für Remotedesktop aktiviert lassen.
5. IP-Adresse und Hostname mit `ipconfig` und `hostname` notieren.

Der Ziel-PC muss Windows Pro, Enterprise oder Server verwenden; Windows Home
kann keine eingehenden RDP-Sitzungen bereitstellen.

## 2. Portal einrichten

1. Portable App starten.
2. Beim ersten Öffnen von **Admin** ein eigenes lokales Admin-Passwort mit
   mindestens zehn Zeichen setzen. Es wird nur gehasht im lokalen
   Windows-Profil gespeichert, nicht im SharePoint-Ordner.
   Es kann später im lokalen Berechtigungsbereich über **Admin-Passwort ändern**
   ersetzt werden.
3. Über **+ Maschine** die Testmaschine registrieren und IP/Hostname prüfen.
4. In **Einstellungen** den RDP-Benutzernamen des Testkontos eintragen.
5. SharePoint-/OneDrive-Ordner im Admin-Reiter kontrollieren, damit
   Maschinen, Reservierungen und Logs zwischen Portalinstallationen
   gemeinsam vorliegen.

## 3. Funktionstest

1. In der Maschinenübersicht die **Ping**-Schaltfläche verwenden.
2. Bei erfolgreichem Ping **Verbinden** wählen.
3. Das Kennwort wird von Windows beim RDP-Start abgefragt; das Portal speichert
   es nicht.
4. Eine Reservierung anlegen und prüfen, ob sie auf einer zweiten
   Portalinstallation sichtbar wird.
5. Im Logs-Reiter Verbindungsstart und spätere Trennung prüfen.

## Grenzen ohne AD und ohne Agent

- Die Benutzerverwaltung im Admin-Reiter ist im No-AD-Modus bewusst ausgeblendet:
  sie könnte keine echten Windows-Rechte ändern.
- RDP-Berechtigungen müssen direkt auf jedem Ziel-PC gepflegt werden.
- Das Portal erkennt Ping und eigene lokale RDP-Fenster, aber keine fremden
  oder getrennten Windows-Sitzungen auf Ziel-PCs zuverlässig.
- Für zentrale lokale Benutzerverwaltung oder vollständige Sitzungsdaten wäre
  später ein Agent oder eine andere zentrale Geräteverwaltung nötig.

## Sichere KI-Hilfe

Keine Kennwörter, vollständigen `ipconfig`-Ausgaben oder echten internen
IP-Adressen teilen. Eine geeignete Frage wäre:

> Erkläre mir für Windows 11 Pro, wie ich ein lokales Konto zur Gruppe
> „Remotedesktopbenutzer“ hinzufüge und Remotedesktop sicher aktiviere.
