# RDP-Portal ohne Active Directory

Diese Variante passt für ein kleines Büro ohne zentrale Windows-Domäne. Das
Portal organisiert Maschinen, Reservierungen, Verbindungsstarts und Logs; die
eigentlichen Windows-RDP-Berechtigungen werden einmalig direkt auf den
Zielrechnern eingerichtet.

Die [aktuelle Abnahmeliste](code-review-testbetrieb.md) ergänzt diese Anleitung.
Für gleichzeitige Änderungen einen gemeinsamen SMB-Speicher verwenden. Bei
OneDrive zunächst nur eine Portalinstanz zum Schreiben verwenden.

## 1. Eine Testmaschine vorbereiten

Auf der Zielmaschine:

1. Ein eigenes lokales Windows-Konto für den Test anlegen, zum Beispiel
   `rdp-test`. Kein gemeinsames Standardkonto für mehrere Personen verwenden.
2. **Einstellungen → System → Remotedesktop** öffnen und Remotedesktop
   aktivieren.
3. Das Testkonto zur lokalen Gruppe **Remotedesktopbenutzer** hinzufügen. Der
   Name ist sprachabhängig — auf englischsprachigen Installationen heißt sie
   **Remote Desktop Users**. Sprachunabhängig ist nur die SID `S-1-5-32-555`:

   ```powershell
   $name = (Get-LocalGroup -SID 'S-1-5-32-555').Name
   ```

   Bei Entra-Konten muss der Eintrag das Format `AzureAD\<UPN>` haben, also
   `AzureAD\vorname.name@firma.de` — **nicht** den Anzeigenamen. Windows prüft
   beim Anmelden die SID; ein Eintrag über den Anzeigenamen kann auf eine andere
   oder gar keine Kennung zeigen, und die Anmeldung wird dann mit „Benutzerkonto
   nicht zur Remoteanmeldung autorisiert" (0x3 / 0x9) abgelehnt, obwohl der
   Eintrag in der Gruppe richtig aussieht.
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
5. Gemeinsamen Speicherordner im Admin-Reiter kontrollieren, damit
   Maschinen, Reservierungen und Logs zwischen Portalinstallationen
   gemeinsam vorliegen.

## 3. Funktionstest

1. In der Maschinenübersicht die **Ping**-Schaltfläche verwenden.
2. **RDP-Diagnose** für TCP/3389 verwenden und anschließend **Verbinden** wählen.
   Ein blockierter Ping allein schließt eine funktionierende RDP-Verbindung nicht aus.
3. Das Kennwort wird von Windows beim RDP-Start abgefragt; das Portal speichert
   es nicht.
4. Eine Reservierung anlegen und prüfen, ob sie auf einer zweiten
   Portalinstallation sichtbar wird.
5. Im Logs-Reiter Verbindungsstart und spätere Trennung prüfen.

## Administrative Abmeldung: UAC-Remoteeinschränkung beachten

Die **administrative Notfall-Abmeldung** prüft am Zielrechner, ob das eingegebene
Konto dort wirklich Administrator ist. Bei **lokalen** Konten — also genau im
Betrieb ohne AD — greift dabei die UAC-Remoteeinschränkung von Windows: bei einer
Netzwerkanmeldung wird die Gruppe *Administratoren* im Token auf „nur verweigern“
gefiltert, und die Prüfung lehnt das Konto ab, obwohl es Administrator ist.

Betroffen sind alle lokalen Administratorkonten **außer** dem eingebauten Konto
`Administrator` (RID 500), das unter Windows 10/11 standardmäßig deaktiviert ist.

Zwei Wege, damit die Funktion nutzbar ist:

1. **Empfohlen für den Pilotbetrieb:** keine administrative Abmeldung verwenden.
   Die eigene Sitzung lässt sich ohne diese Einstellung abmelden, weil der Agent
   dort den Sitzungsbesitz über den gemeldeten RDP-Client prüft.
2. **Wenn die Funktion benötigt wird:** auf dem Zielrechner einmalig setzen

   ```powershell
   New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' `
     -Name LocalAccountTokenFilterPolicy -Value 1 -PropertyType DWord -Force
   ```

   Das erlaubt lokalen Administratorkonten eine nicht gefilterte
   Netzwerkanmeldung. Diese Einstellung schwächt einen UAC-Schutz ab und sollte
   nur auf den Pilotrechnern und nur bewusst gesetzt werden.

Die Fehlerrichtung ist sicher: ohne die Einstellung wird die Abmeldung
*abgelehnt*, nicht fälschlich erlaubt. In einer Domäne tritt das Problem nicht
auf, weil Domänenkonten nicht gefiltert werden.

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

> Erkläre mir für Windows 11 Pro, wie ich ein lokales Konto zur Gruppe mit
> der SID S-1-5-32-555 („Remotedesktopbenutzer“ bzw. „Remote Desktop Users“)
> hinzufüge und Remotedesktop sicher aktiviere.
