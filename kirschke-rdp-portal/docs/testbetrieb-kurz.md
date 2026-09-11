# RDP-Portal: kurzer Start in den Testbetrieb

## 1. Client starten oder aktualisieren

Empfohlen ab 0.2.0: **Kirschke-RDP-Portal-Setup.exe** ausführen. Das Portal vorher
schließen. Das Setup ersetzt seine bisherige Installation unter
`%LOCALAPPDATA%\Programs\KirschkeRDPPortal` und legt einen Startmenüeintrag an.
Maschinen, Reservierungen und Einstellungen bleiben erhalten. Frühere portable
Ordner werden nicht automatisch gesucht oder gelöscht; deren alte Verknüpfungen
nicht mehr verwenden.

Das Testpaket vollständig in einen neuen Ordner entpacken. Das alte Portal schließen
und im neuen Ordner die Datei `Client\Kirschke-RDP-Portal.exe` starten.
Den gesamten Client-Ordner zusammenlassen. Python ist auf dem Test-PC nicht erforderlich.
Das vorhandene Inventar bleibt erhalten.
Im Kopf des geöffneten Portals muss **TEST 0.2.4** stehen. Falls dort eine ältere
Version steht, die Verknüpfung auf die EXE im frisch entpackten Client-Ordner ändern.

Aus dem Quellcode: im Projektordner `python3.13 -m portal_app.app` ausführen.

## 2. Agent-Statusordner einstellen

Version 0.2.2 korrigiert einen Fehler beim Speichern der Netzwerk-Zugangsdaten.
In 0.2.1 konnte nach erfolgreicher Verbindung die allgemeine Meldung „Verbindung
fehlgeschlagen“ erscheinen. Als Übergang kann dort ohne Speichern verbunden werden;
für dauerhafte Windows-Zugangsdaten das Portal auf 0.2.2 aktualisieren.

**Einmalige Freigabeeinrichtung auf Remote-Ettlingen:** Das Paket enthält
`Statusfreigabe-einrichten.ps1`. Diese Datei auf Remote-Ettlingen kopieren und dort
in PowerShell **als Administrator** ausführen. Das Skript prüft den Rechnernamen,
fragt ein Kennwort verdeckt ab und erstellt:

- lokalen Statusordner `C:\RDP-Portal-Daten\agenten-status`;
- lokales Lesekonto `PortalLeser` (kein Administrator-/RDP-Gruppeneintrag);
- Freigabe `\\Remote-Ettlingen\RDP-Status`;
- Ordnerrechte: SYSTEM/Administratoren Vollzugriff, PortalLeser Lesen.

Vorhandene gleichnamige Konten, Freigaben und Statusordner führen zum Abbruch,
damit keine Kennwörter oder vorhandenen Berechtigungen überschrieben werden.
Das Kennwort im Passwortmanager aufbewahren; es wird später im Portal-Konfigurator
benötigt. Bei einer späteren Kennwortänderung dort die Zugangsdaten aktualisieren.
Der Agent auf Remote-Ettlingen verwendet **den lokalen Pfad**, die Portal-PCs
verwenden **den Netzwerkpfad**. Der Agent braucht das Lesekonto nicht.

Das Skript lässt die Firewall standardmäßig unverändert. Auf einem Portal-PC prüfen:

```powershell
Test-NetConnection Remote-Ettlingen -Port 445
```

Wenn `TcpTestSucceeded` false ist, zuerst Namensauflösung, VPN-Routing und Firewalls
prüfen. Eine zusätzliche Windows-Firewallregel kann das Skript über den optionalen
Parameter `-AllowedRemoteAddress` auf ausdrücklich angegebene IPv4-Adressen/Netze
beschränken. Dafür müssen die tatsächlichen Portal-Netze bekannt sein. Eine vorhandene
Regel wird nicht überschrieben; bestehende weiter gefasste Regeln werden nicht eingeschränkt.

**Netzwerkzugriff direkt im Portal einrichten (ab 0.2.1):** Unter
**Einstellungen → Windows-Agent → Netzwerkzugriff einrichten …** den Netzwerkpfad,
z. B. `\\Remote-Ettlingen\RDP-Status`, sowie `Remote-Ettlingen\PortalLeser` und dessen
Kennwort eingeben. **Verbinden, prüfen und übernehmen** prüft den Zugriff im Hintergrund
und übernimmt den Statusordner. Voraussetzung: Freigabe und Konto bestehen bereits.
Der Dialog legt keine Benutzer oder Freigaben auf anderen Rechnern an.

Die aktivierte Option zur Speicherung hinterlegt bzw. ersetzt Zugangsdaten für
diesen Server in Windows. Sie gelten für das aktuelle Windows-Benutzerprofil auf
diesem PC und auch für andere SMB-Freigaben desselben Servers. Das Portal speichert
keine Kennwörter in JSON, Logs oder Befehlszeilen. Jeder Portalbenutzer richtet den
Zugriff einmal ein; danach kann Windows die gespeicherten Daten verwenden.
Verwaltung/Entfernung: **Systemsteuerung → Anmeldeinformationsverwaltung →
Windows-Anmeldeinformationen**, dort den betreffenden Server auswählen.
Bei einer bereits unter anderem Konto geöffneten Serververbindung meldet der
Dialog den Konflikt und trennt keine anderen Verbindungen. Die Zugriffsprüfung
bestätigt die Lesbarkeit, bei bestehenden SMB-Sitzungen aber nicht unabhängig
die Gültigkeit eines neu eingegebenen Kennworts.

**Für Dauerbetrieb ohne Benutzeranmeldung:** Einen gemeinsamen UNC-Ordner wie
`\\SERVER\RDP-Portal\agenten-status` verwenden. Das SYSTEM-Konto des Agenten greift
in einer Windows-Domäne als Computerkonto zu, z. B. `DOMÄNE\NB05$`. Dieses benötigt
Schreib-/Änderungsrechte im Share und auf dem Dateisystem; Portalbenutzer benötigen
Leserechte auf den Statusordner. Bei reinen Entra-/Arbeitsgruppen-PCs muss die IT
zuerst einen passenden authentifizierten Übertragungsweg einrichten.
Keine Netzlaufwerksbuchstaben verwenden. Ein lokaler Ordner funktioniert nur lokal
oder wenn er zusätzlich für das Portal freigegeben wird.

Der bisherige SharePoint-Pfad bleibt als Vorgabe erhalten, ist aber **kein
benutzerunabhängiger Übertragungsweg**: Nach Abmeldung läuft die OneDrive-App nicht
weiter. Ein SYSTEM-Agent allein behebt das nicht. Die direkte Übertragung über
Microsoft Graph ist in dieser Version nicht integriert.

Im Portal unter **Einstellungen → Windows-Agent** auf **Standard verwenden** klicken.
Der Standard für Portal und Agent ist:

```text
%USERPROFILE%\Prof. Dr.-Ing. Dieter Kirschke GmbH & Co. KG\IB Kirschke - Dokumente\90\_K.I. Strategie\Testprogramme\RDP-Portal\remote\agenten-status
```

Alternativ den exakten Ordner mit den Agent-JSON-Dateien eingeben oder auswählen
und **Statusordner übernehmen** klicken. Das Portal liest direkt aus diesem Ordner;
es hängt nichts an. %USERPROFILE% wird zum Benutzerverzeichnis aufgelöst.
Unter **Gelesener Statusordner** steht der tatsächlich verwendete Pfad.
Am einfachsten: **Agent-JSON auswählen …** anklicken und die vom Agenten
aktualisierte JSON auf diesem Portal-PC auswählen. Deren Ordner wird sofort
übernommen und auch nach einem Portal-Neustart verwendet.

Im Agent-Setup denselben synchronisierten Ordner auswählen. Die lokalen Benutzernamen
und damit die lokalen Pfade dürfen sich unterscheiden; beide müssen in dieselbe
SharePoint-Bibliothek und denselben Ordner zeigen. Bei SharePoint/OneDrive zunächst
nur eine schreibende Portalinstanz betreiben. Für parallele Portal-Schreibzugriffe
einen gemeinsamen SMB-Ordner verwenden.

Der Inventar-Speicherort im Adminbereich ist eine separate Einstellung für Maschinen
und Reservierungen. Zur Behebung einer fehlenden Agent-Anzeige genügt die Einstellung
unter **Windows-Agent**. Bestehende Statusordner mit den Namen agent-status oder
agenten-status werden ohne zusätzlich angehängten Unterordner erkannt.

## 3. Zielrechner und Konto eintragen

**Maschine hinzufügen** wählen, Hostname/IP eingeben und Registrierung abschließen.
Die **Maschinen-ID** aus den Details für den Agent notieren.
Auf der Karte **Anmelden als → + Benutzer hinzufügen …** wählen und ein vorhandenes
Windows-Konto wie ZIELPC\tester oder FIRMA\benutzer eintragen.
Die Liste wird pro Maschine gespeichert, die Auswahl pro lokalem Benutzerprofil.
Das Portal legt keine Windows-Konten an, erteilt keine RDP-Rechte und speichert keine
Kennwörter. Windows fragt das Kennwort bei der Verbindung ab.

Auf dem Ziel-PC müssen Remotedesktop und die RDP-Berechtigung für das Konto eingerichtet
sein. Bei Problemen die **RDP-Diagnose** öffnen.

## 4. Agent installieren oder Pfad ändern

Kirschke-RDP-Agent-Setup.exe auf dem Ziel-PC starten und die Windows-Administratorabfrage
bestätigen. Maschinen-ID und dauerhaft erreichbaren Statusordner eintragen.
**Jetzt installieren** entfernt automatisch bekannte alte Agent-Installationen samt
benutzereigenen Aufgaben und ersetzt die Konfiguration. Programmdateien liegen unter
`%ProgramFiles%\KirschkeRDPAgent`, Konfiguration und Verlauf unter
`%ProgramData%\KirschkeRDPAgent`. Die neue Aufgabe heißt **Kirschke RDP Agent - Machine**,
läuft als SYSTEM beim Hochfahren und wird sofort gestartet. Python ist nicht erforderlich.

Das Setup prüft, ob eine aktuelle Online-Statusdatei geschrieben wird. Wenn der Agent
bereits die JSON am gewünschten Ort aktualisiert, muss für die Portal-Pfadkorrektur
der Agent nicht erneut installiert werden.

Der Agent läuft unabhängig von angemeldeten Benutzern. Es ist eine rechnerweite
Systemaufgabe, kein Windows-Dienst. Nach Installation zusätzlich einen Neustart und
eine vollständige Benutzerabmeldung testen; die JSON muss weiter aktualisiert werden.
Die Einrichtung prüft das Schreiben einer frischen JSON durch die tatsächliche Aufgabe.

## 5. Ergebnis prüfen

**Statusdateien gefunden, aber keiner Maschine zugeordnet:** Auf der betroffenen
Maschinenkarte **Details → Agent zuordnen …** öffnen. Den passenden Agenten wählen,
beispielsweise **NB05 · NB05**, und mit OK übernehmen. Die IP-Adresse für RDP und
die interne Maschinen-ID bleiben erhalten. Die Zuordnung wird dauerhaft gespeichert.
Alte Dateien wie NB05-PC12 werden dadurch nicht für diese Maschine übernommen.
Die JSON nicht händisch ändern: Der laufende Agent schreibt seine Konfiguration
bei jeder neuen Meldung wieder hinein.

Eine aktuelle Online-Meldung erscheint auf der Karte als **Agent: Online** und
bei leerer Sitzung als **Frei und verfügbar**. Bei einer aktiven Sitzung steht dort
der Benutzer. Der Online-Zähler oben wird ebenfalls aktualisiert.

**Grüner, verstärkter Rahmen:** online und frei. **Blauer Rahmen:** online und belegt,
auch bei getrennter Sitzung. Fehler/veraltete Meldungen haben Vorrang bei der Farbe.
Nach einem Ping steht dessen Ergebnis oben rechts auf der Karte. Eine fehlende
ICMP-Antwort ändert den Agentstatus nicht.

Unter **Details → Status und Sitzung** stehen alle gemeldeten Windows-Sitzungen,
Benutzer und Windows-Anmeldezeiten (ISO-Zeit mit UTC-Offset). Der lokale Agent-Verlauf
behält die letzten 200 erkannten Änderungen, das Portal zeigt die letzten 20.
Die Zeit einer Änderung ist die Erkennungszeit der Abfrage, keine garantierte
Windows-Ereigniszeit. Sitzungen, die vollständig zwischen zwei Abfragen liegen,
können fehlen. „Nicht mehr gemeldet“ kann auch eine Änderung während einer Agent-
Unterbrechung bedeuten. Verlauf und Anmeldezeiten werden auch für Konsolensitzungen erfasst.

Im Dashboard **Agent-Diagnose** öffnen und auf **Agentstatus jetzt einlesen** klicken.
Das Portal liest automatisch alle fünf Sekunden; die SharePoint-Synchronisierung
kann zusätzliche Zeit benötigen.

Das Dashboard zeigt die Anzahl gefundener JSON-Dateien, gültiger Meldungen und
zugeordneter Maschinen. Unter **Diagnose anzeigen** stehen je Datei Maschinen-ID,
Hostname, Meldungszeit und Zuordnung. Eine aktuelle Dateiänderungszeit allein reicht
nicht: Entscheidend ist `observed_at_utc` innerhalb der JSON. Bei weiter bestehenden
Problemen **Diagnose kopieren** klicken und den Text zur Fehlersuche weitergeben.
Er enthält auch die gestartete Programmdatei und die tatsächlich gelesenen Pfade.

- **Keine Agent-Statusdatei gefunden:** Im gelesenen Ordner fehlt eine Agent-JSON.
- **Nicht zugeordnet:** Maschinen-ID und Hostname im Portal und Agent prüfen.
- **Nicht lesbar:** Dateiname und Fehler stehen direkt unter der Pfadeinstellung.
- **Zugeordnet, aber offline/veraltet:** Aktualisierungszeit der JSON prüfen.
  Nach 90 Sekunden ohne neue Meldung wird der Status veraltet, nach fünf Minuten offline.

Ping bestätigt die Netzwerk-Erreichbarkeit; eine aktuelle Agent-Meldung bestätigt den
Windows-Sitzungsstatus. Zum Test anmelden, RDP-Fenster schließen und danach ausdrücklich
in Windows abmelden. Eine getrennte Sitzung bleibt zunächst belegt.

Agent-Log: %ProgramData%\KirschkeRDPAgent\agent.log.
Portal-Log: %LOCALAPPDATA%\KirschkeRDPPortal\logs\portal.log.
Die EXE-Dateien sind nicht signiert; eine lokale Anwendungssteuerung kann eine IT-Freigabe
erfordern. Ausführlicher Prüfbericht: Pruefbericht.md im Paket.

Beide Programme lassen sich unter **Windows → Installierte Apps** deinstallieren.
Der Agent-Uninstaller benötigt Administratorrechte und entfernt Programmdateien,
Aufgaben und Konfiguration. Rechnerweiter Verlauf/Logs und gemeinsame Statusdateien
bleiben erhalten. Der Portal-Uninstaller entfernt Programmdateien und Startmenüeintrag;
Inventar und Benutzereinstellungen bleiben erhalten. Alternativ:

```powershell
.\Kirschke-RDP-Agent-Setup.exe --uninstall
.\Kirschke-RDP-Portal-Setup.exe --uninstall
```


## Eigene Sitzung wieder öffnen oder abmelden (ab Portal 0.2.3)

Das Schließen des RDP-Fensters trennt nur die Verbindung: Programme und Anmeldung
bleiben auf dem Zielrechner bestehen. Die Maschine bleibt deshalb blau/belegt.

1. Unter **Anmelden als** exakt das Konto der gemeldeten Sitzung auswählen,
   beispielsweise `AzureAD\ChristianBecker`. Fehlt es, mit **+ Benutzer hinzufügen**
   diesen Kontonamen hinterlegen. Unterschiedliche Schreibweisen wie E-Mail-Adresse
   und Windows-Kurzname werden nicht automatisch als dieselbe Identität behandelt.
2. **Wiederverbinden** öffnet RDP mit diesem Konto. Windows prüft die Anmeldung
   und entscheidet über die Wiederaufnahme der Sitzung. Ein bereits geöffnetes,
   vom Portal gestartetes RDP-Fenster wird weiterhin nicht doppelt gestartet.
3. Für eine vollständige Abmeldung: **Details → Sitzung abmelden …**. Bei mehreren
   passenden Sitzungen die Sitzungsnummer auswählen. Die Bestätigung beendet die
   Programme dieser Sitzung; nicht gespeicherte Arbeit kann verloren gehen.
4. Die Anzeige wird erst frei, wenn der Agent das Ende der Sitzung bestätigt.
   Die normale Agentabfrage erfolgt alle 30 Sekunden, das Portal liest alle 5 Sekunden.

Die direkte Abmeldung verwendet die Windows-Sitzungsverwaltung und ist auf das
Windows-Konto beschränkt, unter dem das Portal läuft. Sitzungsnummer, Kontoname,
Anmeldezeitpunkt und Windows-Benutzerkennung werden vor der Anforderung geprüft.
Die Auswahl eines fremden Kontonamens oder Portal-Adminrechte erlauben keine fremde
Abmeldung. Fehlende Anmeldezeiten alter Agentversionen verhindern die Direktabmeldung.

**Netzwerkgrenze:** Leserechte auf `\\Remote-Ettlingen\RDP-Status` oder eine
funktionierende RDP-Verbindung garantieren keinen Zugriff auf diese zusätzliche
Windows-Verwaltungsschnittstelle. Insbesondere auf Entra-Geräten kann Windows den
Aufruf verweigern. Das Portal zeigt dann den Fehler an. In diesem Fall erneut
verbinden und im Ziel-Windows **Start → Benutzer → Abmelden** wählen. Der Agent
verarbeitet weiterhin keine Befehle aus dem Statusordner. Für diese Portaländerung
muss Agent 1.1.0 nicht neu installiert werden.

## Update 0.2.4 / Agent 1.2.0: Reservieren und Live-Status

Für die neue Live-Abfrage **beide Setups aktualisieren**: Portal auf dem Arbeitsplatz,
Agent auf Remote-Ettlingen. Im Agent-Setup denselben lokalen Statusordner wie bisher
angeben. Das Setup ersetzt die alte Installation und startet den Agenten wieder
als SYSTEM. Die Windows-Freigabe und das Konto PortalLeser bleiben bestehen.

Beim Starttest auf dem Entwicklungs-PC hat die Windows-Anwendungssteuerung das
neue Portal und dessen Setup mit Fehler 4551 blockiert. Falls das auch auf eurem
Gerät erscheint, muss die IT die Anwendung regulär freigeben beziehungsweise
geeignet signieren. Die Richtlinie nicht abschalten. Der Agent konnte dort starten;
die Portaloberfläche wurde aus dem Quellcode geprüft. Details stehen im Prüfbericht.

**Wiederverbinden:** Bei einer erkannten belegten/getrennten Sitzung ist jetzt
**Sitzung öffnen …** verfügbar, auch wenn der voreingestellte Benutzername nicht
zum vom Agenten gemeldeten Windows-Namen passt. Eigenes Sitzungskonto auswählen;
Windows prüft dessen Anmeldung. Alternativ steht der gemeldete Name direkt in
**Anmelden als → Angemeldet · …**. Nach der Auswahl erscheint **Wiederverbinden**.

**Reservieren:** Im Kalender Maschine und Zeitraum buchen. Während dieses Zeitraums
zeigt das Portal „Für dich reserviert“ beziehungsweise den anderen Reservierenden
mit Endzeit. Eigentümer ist das Portal-Benutzerkonto der Buchung, nicht der gerade
ausgewählte RDP-Kontoname. Andere Portalbenutzer können dann keine Verbindung
starten; eigenes Wiederverbinden bleibt möglich. Anfang gilt inklusive, Ende
exklusive. Zeitgrenzen werden spätestens beim nächsten Portalzyklus (5 Sekunden)
und unmittelbar vor dem RDP-Start geprüft. Eine laufende Sitzung wird bei Beginn
oder Ende einer Reservierung nicht automatisch beendet. Fremde Buchungen dürfen
im Portal nur Administratoren ändern; dabei bleibt der ursprüngliche Eigentümer
erhalten. Parallel kollidierende Buchungen werden beim Speichern abgewiesen.

Alle Portal-PCs müssen denselben **Inventar-/Planungsordner** verwenden, in dem
portal-state.json liegt. Der Agent-Statusordner allein teilt keine Reservierungen.
Für mehrere schreibende Benutzer eine gemeinsame Windows-Netzwerkfreigabe mit
passenden Schreibrechten verwenden. Die bestehende RDP-Status-Freigabe bleibt
lesbar; sie wird dafür nicht pauschal beschreibbar gemacht. Bei OneDrive weiterhin
nur eine schreibende Portalinstanz verwenden. Reservierungen sind eine
Koordinationsregel dieses Portals: direkte mstsc-Aufrufe oder Änderungen an der
Inventardatei werden damit nicht auf Windows-Ebene gesperrt.

**Live-Status:** In den Maschinendetails **Agent live abfragen** anklicken. Der neue
Agent liest Windows-Sitzungen für diese Anfrage frisch und antwortet direkt über
eine Windows-Named-Pipe (einen durch Windows geschützten Nachrichtenkanal über SMB).
Die übliche Windows-Dateifreigabeverbindung zum Zielrechner muss funktionieren,
einschließlich Zugang als dessen lokales Konto PortalLeser. Ein reiner OneDrive-Pfad
oder eine funktionierende RDP-Verbindung genügt nicht. Die Live-Antwort wird sofort
in die Anzeige übernommen und ihr Zeitpunkt steht unter Agent-Diagnose. Ältere
Statusdateien verdrängen sie nicht sofort; nach maximal 90 Sekunden erfolgt wieder
die Bewertung des Dateikanals. Eine jüngere Agent-Datei übernimmt früher.

Die Abfrage wartet nicht auf das 30-Sekunden-Intervall und nicht auf OneDrive.
Netzwerkaufbau, Windows und VPN benötigen trotzdem Zeit; völlig latenzfrei ist sie
nicht. Verbindungsfehler werden angezeigt und bestätigen keinen alten Status.
Im lokalen nativen Test lag die Abfrage im einstelligen Millisekundenbereich;
die Geschwindigkeit und SMB-Zulassung im Firmen-VPN sind vor Ort zu prüfen.

Der Agent erlaubt ausschließlich eine feste Statusanfrage. Die Pipe-Berechtigungen
gelten für SYSTEM, Administratoren und das lokale Konto PortalLeser. Fehlt es beim
Agentstart, bleibt der zusätzliche Zugang für dieses Konto gesperrt; nach Einrichtung
Agent neu starten. Bei abweichendem Lesekontonamen kann ein Administrator in
`%ProgramData%\KirschkeRDPAgent\agent-config.json` den Wert `live_status_reader`
anpassen und die Aufgabe „Kirschke RDP Agent - Machine“ neu starten. Keine Kennwörter
in diese Datei schreiben. Über den Kanal gibt es keine Abmelde-/Ausführungsbefehle.

**Notfall-Abmeldung fremder Benutzer:** Windows unterstützt das technisch über
WTSLogoffSession mit den nötigen Rechten am Zielrechner. Das Admin-Fenster besitzt
in 0.2.4 noch keinen Force-Abmeldeknopf. Die vorhandene Selbstabmeldung prüft weiter
die Windows-Benutzerkennung. Portal-Adminfreischaltung und PortalLeser-Lesezugriff
sind keine Berechtigung, andere Windows-Benutzer abzumelden. Eine solche Abmeldung
kann ungespeicherte Arbeit verlieren lassen und muss bewusst bestätigt werden.
