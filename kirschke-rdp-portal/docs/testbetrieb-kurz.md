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
Im Kopf des geöffneten Portals muss **TEST 0.2.12** stehen. Falls dort eine ältere
Version steht, die Verknüpfung auf die EXE im frisch entpackten Client-Ordner ändern.

Aus dem Quellcode: im Projektordner `python3.13 -m portal_app.app` ausführen.

## Update 0.2.12 / Agent 1.3.0: Abmeldung auf dem Ziel-Agenten

Die Abmeldung wird nicht mehr durch eine remote WTS-Anforderung des Portal-PCs
ausgeführt. Stattdessen prüft der Agent die aktuelle Sitzung lokal und meldet sie als
SYSTEM ab. Bei einer normalen Abmeldung müssen Sitzungskonto, Sitzungsnummer,
Anmeldezeit und der vom Ziel gemeldete RDP-Clientrechner zur Anfrage passen.

Die administrative Notfall-Abmeldung verlangt zusätzlich ein echtes
Windows-Administratorkonto des Zielrechners. Das Portal verwendet die eingegebenen
Zugangsdaten nur im Hintergrundthread für diese eine Verbindung und speichert das
Kennwort nicht. Portal-Adminfreischaltung oder `PortalLeser` allein reichen nicht.
Anfragen sind 30 Sekunden gültig und können nicht wiederholt werden. Für diese
Funktion müssen **Portal und Agent aktualisiert** werden.

## Agent 1.2.2: Installation ohne internes PowerShell-Skript

Die Agent-Setup-EXE führt Installation, Konfiguration, Aufgabenregistrierung und
Deinstallation jetzt selbst aus. Sie startet intern kein `Install-Agent.ps1` mehr.
Damit scheitert das Setup nicht mehr an einer PowerShell-Ausführungsrichtlinie, die
Skripte auf dem Ziel-PC sperrt. Die Richtlinie wird weder verändert noch umgangen.

Bei einer neuen Maschine richtet das Setup außerdem den lokalen Benutzer
`PortalLeser`, dessen ausschließlich lesbare Freigabe `RDP-Status` und die nötigen
Ordnerrechte ein. Das Kennwort wird im Setup zweimal selbst vergeben und muss für
den späteren Portalzugriff im Passwortmanager aufbewahrt werden. Es wird nicht in
Konfiguration, Log oder Befehlszeile geschrieben. Bei einem Update mit bereits
vollständig vorhandener Freigabe bleiben die Kennwortfelder leer.

Zum Installieren ausschließlich die neue Datei
`Kirschke-RDP-Agent-Setup.exe` als Administrator starten, Maschinen-ID, lokalen
Statusordner und bei der ersten Einrichtung das neue Lesekennwort eintragen und
**Jetzt installieren** wählen. Eine eventuell vorhandene
Anwendungssteuerung kann die unsignierte EXE weiterhin separat blockieren; dann ist
eine reguläre IT-Freigabe erforderlich. `Statusfreigabe-einrichten.ps1` bleibt ein
separates Hilfsskript und benötigt, falls es verwendet wird, eine reguläre
Skriptfreigabe. Für die normale Neueinrichtung wird dieses Skript nicht mehr benötigt.

216 automatisierte Tests bestanden. Der Agent-Build und der Setup-Build waren
erfolgreich; die Agent-EXE 1.2.2 startete für eine reine Statusabfrage. Die finale
Setup-EXE bestand ihren Selbsttest und öffnete den Installationsdialog, ohne dass
eine Installation ausgelöst wurde. Ein vorheriger Zwischenbuild war von der
Windows-Anwendungssteuerung blockiert; die Richtlinie wurde nicht verändert. Der
Paketinhalt enthält kein PowerShell-Installationsskript.

## Update 0.2.11: getrennte Ziele für RDP und Agentstatus

Verwendet RDP wegen fehlender Namensauflösung eine IP-Adresse, kann der
maschinenspezifische SMB-Fallback weiterhin unter dem Windows-Rechnernamen verbunden
sein. Das Portal verwendet für Liveabfrage sowie Vor- und Nachprüfung einer Abmeldung
jetzt exakt den Servernamen aus dem ausdrücklich eingerichteten UNC-Fallbackpfad. Der
eigentliche WTS-Abmeldeaufruf verwendet weiterhin das konfigurierte RDP-Ziel. Damit
bleibt die Windows-SMB-Anmeldung gültig, ohne das RDP-Ziel umzuschreiben. Der gelbe
Hinweis zu lokalen RDP-Fenstern ist in diesem ausgelieferten Stand ebenfalls entfernt.

## Update 0.2.10: Absturz des Abmelde-Hilfsprozesses behoben

Der von PyWin32 gelieferte WTS-Serverhandle wird nun über sein eigenes `Close`
geschlossen. Zuvor konnte ein zusätzlicher direkter `WTSCloseServer`-Aufruf denselben
Handle beim Aufräumen ein zweites Mal schließen. Der isolierte Hilfsprozess endete
dann mit `3221226356` (`0xC0000374`), ohne die Sitzung abzumelden. Der Portalprozess
blieb zwar geschützt, die gewünschte Aktion schlug jedoch fehl. Erfolg und Windows-
Fehlerpfad sind jetzt per Regressionstest abgedeckt; echte Sitzungen wurden dabei
nicht abgemeldet. Windows prüft die Berechtigung auf dem Zielrechner weiterhin selbst.
Das bisherige gelbe Banner zu aktiven oder geschlossenen lokalen RDP-Fenstern wurde
entfernt. Das Portal protokolliert ein geschlossenes `mstsc`-Fenster weiterhin intern;
für die sichtbare Sitzungsbelegung ist der Agentstatus maßgeblich.

## Update 0.2.9: eigener Fallback und klare Kartenreihenfolge

Jede Maschine besitzt jetzt ihren eigenen, clientlokal gespeicherten Datei-Fallback.
Er wird unter **Maschinen → Details → Datei-Fallback einrichten …** verbunden.
Für NB12KI sind das beispielsweise `\\NB12KI\RDP-Status` und
`NB12KI\PortalLeser`. Ein früherer globaler Statusordner bleibt nach dem Update nur
als Alt-Standard aktiv, bis für die jeweilige Maschine ein eigener Pfad gespeichert
wurde. Die Einstellungen-Seite zeigt nur noch die gemeinsame Diagnose.

Ein fehlender Datei-Fallback stuft eine erfolgreiche Liveantwort nicht herab. Nur
ein bestätigter Live- oder Dateistatus erhält eine Zustandsfarbe; Ping allein gilt
nicht als Agentnachweis. Farbige Karten haben einen 4-Pixel-Rahmen, unbestätigte
graue Karten einen 2-Pixel-Rahmen. Das Dashboard sortiert verfügbare grüne Maschinen
zuerst, danach belegte blaue, besondere Warn-/Fehlerzustände und zuletzt graue.
Auch das Monitor-Symbol wird bei einem Statuswechsel aktualisiert.

Der Agent bleibt bei Version 1.2.1. Sein Setup bezeichnet den empfohlenen Pfad nun
eindeutig als lokalen Zielrechnerordner. Installer und Hilfsskripte setzen keine
`ExecutionPolicy Bypass`; eine blockierende Richtlinie muss regulär durch die IT
freigegeben werden.

Der automatisierte Prüflauf umfasst 197 bestandene Tests. Dabei wurde keine echte
Windows-Sitzung abgemeldet.

Die finalen Portal-, Agent- und Setup-Builds waren erfolgreich; beide Setup-
Selbstprüfungen (`--check`) lieferten Exitcode 0. Die finale Portal-EXE 0.2.11 startete
auf dem Entwicklungsrechner erfolgreich und lief im Kurztest weiter. Der Statusaufruf
der unveränderten Agent-EXE wurde dagegen von der vorhandenen Windows-
Anwendungssteuerungsrichtlinie blockiert. Diese Richtlinie wurde nicht umgangen.
Build-Erfolg und tatsächlicher EXE-Start werden deshalb getrennt bewertet; die
Python-/Qt-Oberfläche wurde zusätzlich gerendert und visuell geprüft.

## Update 0.2.8: absturzgeschützte und bestätigte Abmeldung

Der native Windows-WTS-Aufruf läuft nun in einem kurzlebigen Hilfsprozess mit
demselben Windows-Benutzertoken. Ein Fehler dieser Windows-Schnittstelle kann damit
nicht mehr den laufenden Portalprozess beenden. Der Hilfsprozess wartet auf den
Abschluss des Windows-Aufrufs. Anschließend fragt das Portal den reinen `STATUS/1`-
Kanal frisch ab und meldet nur dann Erfolg, wenn die exakt geprüfte alte Sitzung
nicht mehr aktiv ist. Wird sie weiterhin gemeldet, bleibt die Maschine belegt und
der Dialog nennt dies ausdrücklich. Der Agentkanal erhält weiterhin keinen
Abmeldebefehl. Agent 1.2.1 bleibt unverändert.

## Update 0.2.7: eindeutige Sitzung ohne Kontodialog

Meldet der Agent genau ein bestehendes Windows-Sitzungskonto, verwendet das Portal
diesen Namen beim Wiederverbinden direkt und zeigt keinen inhaltslosen Auswahldialog
mehr. Der Name wird lediglich in die RDP-Datei eingetragen; Windows prüft weiterhin
Kennwort, Identität und Remoteanmelderecht. Nur bei mehreren gemeldeten Konten ist
weiterhin eine bewusste Auswahl erforderlich. Dieses Update betrifft nur das Portal;
Agent 1.2.1 bleibt unverändert.

## Update 0.2.6: eigene getrennte Entra-Sitzung

Dieses Update betrifft nur das Portal; Agent 1.2.1 muss dafür nicht erneut
installiert werden. Das Portal verwendet für die Anzeige einer eigenen Sitzung
die beim Programmstart erkannte Windows-Identität und nicht das frei wählbare
RDP-Anmeldekonto. Bei einer eigenen getrennten Sitzung erscheinen deshalb auch
mit „Standard · Windows-Anmeldung“ sowohl **Wiederverbinden** als auch der rote
Knopf **Abmelden**.

Vor einer Abmeldung fragt das Portal den Agentstatus zweimal frisch ab und prüft
Sitzungsnummer, Windows-Benutzer und Anmeldezeit. Der Agentkanal bleibt dabei ein
reiner Statuskanal. Anschließend fordert das Portal die Abmeldung getrennt über
Windows WTS an; Windows kann sie weiterhin wegen fehlender Rechte ablehnen. Erst
eine neue Agentmeldung ohne diese Sitzung zeigt die Maschine als frei.

## Update 0.2.5 / Agent 1.2.1: automatische Aktualisierung und Abmelden

Für diesen Stand **beide Setups aktualisieren**: Portal auf dem Arbeitsplatz und
Agent auf Remote-Ettlingen. Der Agent läuft weiterhin als SYSTEM. Freigabe,
Statusordner und das lokale Lesekonto `PortalLeser` bleiben unverändert.

Beim Öffnen des Maschinendashboards fragt das Portal alle Zielrechner sofort direkt
ab. Unter **Einstellungen → Statusaktualisierung** lässt sich das Intervall von
2 bis 60 Sekunden einstellen; Vorgabe sind 5 Sekunden. Mehrere Rechner werden mit
begrenzter Parallelität unabhängig voneinander abgefragt. Eine noch laufende
Abfrage desselben Rechners wird nicht doppelt gestartet; nach Fehlern wartet das
Portal dort länger, höchstens 60 Sekunden.

Unter dem Agentstatus steht nun immer Quelle und Alter:

- **Live · vor …**: aktuelle direkte Antwort des Agents;
- **Datei-Fallback · vor …**: direkte Abfrage fehlgeschlagen, neuere Agent-JSON wird verwendet;
- **Live nicht erreichbar · letzter Stand …**: der neuere Live-Stand bleibt sichtbar,
  gilt aber ausdrücklich nicht als aktuelle Erreichbarkeit.

Eine ältere Datei verdrängt keine neuere Live-Meldung. Sobald der direkte Kanal
wieder antwortet, wechselt die Anzeige automatisch zurück. Karten werden dabei
an Ort und Stelle aktualisiert; Scrollposition, gewähltes Anmeldekonto und ein
geöffnetes Menü bleiben erhalten.

Die rote Abmeldeaktion ist absichtlich zustandsabhängig:

- frei und zugelassen: **Verbinden**;
- eigene verbundene Sitzung: **Abmelden**;
- eigene getrennte Sitzung: **Wiederverbinden** und zusätzlich **Abmelden**;
- fremde Sitzung oder fremde Reservierung: Belegung anzeigen, keine normale Abmeldung.

Vor der eigenen Abmeldung prüft das Portal Windows-Benutzerkennung, Kontonamen,
Sitzungsnummer und Anmeldezeit erneut. Die Bestätigung nennt Rechner und Benutzer
und warnt vor dem Verlust ungespeicherter Arbeit. Windows entscheidet über die
Berechtigung. Anschließend fragt das Portal sofort neu ab und zeigt den Rechner
erst nach bestätigtem Sitzungsende als frei.

Eine fremde Sitzung lässt sich nur über die getrennte rote Aktion **Notfall-Abmeldung …**
im freigeschalteten Adminbereich auswählen. Auch dort werden Benutzer, Sitzungsnummer
und Anmeldezeit frisch geprüft. Portal-Adminfreischaltung allein reicht nicht:
Der laufende Portalprozess braucht tatsächliche Windows-Rechte für die
Sitzungsverwaltung auf Remote-Ettlingen. `PortalLeser` bleibt reines Lesekonto;
der Agentkanal akzeptiert ausschließlich Statusanfragen und keine Abmeldebefehle.
Auf dem dauerhaft laufenden, Entra-joined und nicht AD-domain-joined Ziel muss die
IT diese Windows-Autorisierung vor Ort prüfen.

Geschlossene Auswahllisten ändern beim Darüberrollen weder Zustand noch Auswahl;
das Mausrad scrollt stattdessen die Seite. Erst nach bewusstem Öffnen bedienen
Mausrad und Tastatur die Liste. Schriftgrößen folgen der Windows-Skalierung; geprüft
wurde die Oberfläche bei 100 %, 125 % und 150 %.

Bei einem früheren Zwischenstand starteten Portal-EXE und Agent-EXE; beide damaligen
Setup-Prüfungen endeten erfolgreich. Ein vorheriger Start des Portal-Setups war
auf demselben Rechner trotz erfolgreichen Builds noch von der vorhandenen
Anwendungssteuerungsrichtlinie blockiert (Fehlerbild 4551). Die Richtlinie wurde
nicht verändert oder umgangen. Die spätere erfolgreiche Selbstprüfung ist keine
Freigabe für andere Geräte; bei erneuter Blockierung sind eine reguläre IT-Freigabe
beziehungsweise geeignete Signierung erforderlich.

## 2. Agent-Statusordner einstellen

Version 0.2.2 korrigiert einen Fehler beim Speichern der Netzwerk-Zugangsdaten.
In 0.2.1 konnte nach erfolgreicher Verbindung die allgemeine Meldung „Verbindung
fehlgeschlagen“ erscheinen. Als Übergang kann dort ohne Speichern verbunden werden;
für dauerhafte Windows-Zugangsdaten das Portal auf 0.2.2 aktualisieren.

**Einmalige Freigabeeinrichtung auf dem Zielrechner:** Das Paket enthält
`Statusfreigabe-einrichten.ps1`. Diese Datei auf den Zielrechner kopieren und dort
in PowerShell **als Administrator** ausführen. Das Skript prüft den Rechnernamen,
fragt ein Kennwort verdeckt ab und erstellt:

- lokalen Statusordner `C:\RDP-Portal-Daten\agenten-status`;
- lokales Lesekonto `PortalLeser` (kein Administrator-/RDP-Gruppeneintrag);
- Freigabe `\\Remote-Ettlingen\RDP-Status`;
- Ordnerrechte: SYSTEM/Administratoren Vollzugriff, PortalLeser Lesen.

Für einen anderen Rechner als Remote-Ettlingen muss dessen tatsächlicher kurzer
Windows-Computername ausdrücklich angegeben werden, zum Beispiel:

```powershell
.\Statusfreigabe-einrichten.ps1 -ExpectedComputerName "ZIELPC"
```

Das ist keine Intune-Registrierung. Es richtet nur den lokalen Statusordner, das
reine Lesekonto und die SMB-Freigabe für diesen Zielrechner ein. Blockiert die
Unternehmensrichtlinie das Skript oder die unsignierte Setup-EXE, muss die IT sie
regulär freigeben; die Richtlinie nicht umgehen.

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

**Netzwerkzugriff pro Maschine einrichten (ab 0.2.9):** Unter
**Maschinen → Details → Datei-Fallback einrichten …** den Netzwerkpfad,
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

**Für Dauerbetrieb ohne Benutzeranmeldung:** Der Agent verwendet auf jedem
Zielrechner den lokalen Pfad `C:\RDP-Portal-Daten\agenten-status`; SYSTEM benötigt
dort Schreibrechte. Das Freigabeskript stellt denselben Ordner als
`\\ZIELRECHNER\RDP-Status` für das reine Lesekonto `PortalLeser` bereit. Im Portal
wird diese UNC-Freigabe ausschließlich der betreffenden Maschine zugeordnet. Keine
Netzlaufwerksbuchstaben und keinen benutzergebundenen OneDrive-Pfad für den
SYSTEM-Agenten verwenden.

Der Inventar-Speicherort im Adminbereich ist eine separate Einstellung für Maschinen
und Reservierungen. **Einstellungen → Windows-Agent** enthält nur noch Aktualisierung
und Diagnose; den Fallbackpfad immer in den Details der betroffenen Maschine ändern.

## 3. Zielrechner und Konto eintragen

**Maschine hinzufügen** wählen, Hostname/FQDN oder IP eingeben und Registrierung
abschließen. Das Portal sucht weder Intune noch das lokale Netzwerk automatisch ab.
Die **Maschinen-ID** aus den Details für den Agent notieren.
Auf der Karte **Anmelden als → + Benutzer hinzufügen …** wählen und ein vorhandenes
Windows-Konto wie ZIELPC\tester oder FIRMA\benutzer eintragen.
Die Liste wird pro Maschine gespeichert, die Auswahl pro lokalem Benutzerprofil.
Das Portal legt keine Windows-Konten an, erteilt keine RDP-Rechte und speichert keine
Kennwörter. Windows fragt das Kennwort bei der Verbindung ab.

Auf dem Ziel-PC müssen Remotedesktop und die RDP-Berechtigung für das Konto eingerichtet
sein. Der Agent legt kein Anmeldekonto an und erteilt keine RDP-Rechte. Ist der
Zielrechner nicht Microsoft-Entra-joined, ist ein `@prof-kirschke.de`-Konto dort
nicht automatisch vorhanden; dann ein vorhandenes lokales Konto als
`ZIELPC\benutzer` oder ein erreichbares AD-Domänenkonto verwenden. Bei Problemen
die **RDP-Diagnose** öffnen.

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

Im Dashboard **Agent-Diagnose** öffnen und auf **Agentstatus jetzt einlesen** klicken,
wenn die Dateiquelle gezielt geprüft werden soll. Das Dashboard fragt den direkten
Livekanal automatisch im eingestellten Intervall ab; bei Fehlern wertet es die
Agent-JSON als Fallback aus. Dateisynchronisierung kann zusätzliche Zeit benötigen.

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

1. Meldet der Agent genau eine Sitzung, verwendet das Portal deren Windows-Kontonamen
   beim Wiederverbinden automatisch. Bei mehreren Sitzungen das richtige Konto
   auswählen. Unterschiedliche Schreibweisen wie E-Mail-Adresse und Windows-Kurzname
   werden nicht automatisch als dieselbe Identität behandelt.
2. **Wiederverbinden** öffnet RDP mit diesem Konto. Windows prüft die Anmeldung
   und entscheidet über die Wiederaufnahme der Sitzung. Ein bereits geöffnetes,
   vom Portal gestartetes RDP-Fenster wird weiterhin nicht doppelt gestartet.
3. Für eine vollständige Abmeldung den roten **Abmelden**-Knopf auf der Karte oder
   in den Details wählen. Bei mehreren passenden Sitzungen die Sitzungsnummer
   auswählen. Die Bestätigung beendet die
   Programme dieser Sitzung; nicht gespeicherte Arbeit kann verloren gehen.
4. Die Anzeige wird erst frei, wenn der Agent das Ende der Sitzung bestätigt.
   Direkt danach startet das Portal eine neue Liveabfrage.

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
