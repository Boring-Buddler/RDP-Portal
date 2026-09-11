# Codeprüfung und erster Testbetrieb

Stand: 10.09.2026, Portal 0.2.4 / Agent 1.2.0.

## Nachtrag: Reservierung, Sitzungsauswahl und Live-Abfrage

Reservierungen steuern jetzt die Verbindungsfreigabe während ihres Zeitraums.
Eigentümer werden anhand des Portal-UPN verglichen; der ausgewählte RDP-Kontoname
ist davon getrennt. Die Sperre erscheint in Karten/Details und wird unmittelbar
vor dem Start erneut aus der gemeinsamen Datei geprüft. Beginn/Ende werden auch
ohne geänderte Agentdatei neu bewertet. Parallelbuchungen werden unter der
bestehenden Dateisperre auf Überschneidungen geprüft. Fremde Buchungen sind in der
Oberfläche nur administrativ bearbeitbar; ein Admin-Edit überträgt kein Eigentum.
Dies bleibt eine Portal-Koordinationsregel, keine Windows-Zugriffssperre oder
zentrale Identitätsprüfung. Eine getrennte Inventardatei je Portal teilt keine
Reservierungen; für mehrere Schreiber ist ein gemeinsamer SMB-Speicher vorgesehen.

Wenn E-Mail-Adresse und gemeldeter Windows-Kurzname abweichen, öffnet die neue
Aktion „Sitzung öffnen …“ eine explizite Auswahl der erkannten Sitzungskonten.
Sie ersetzt die pauschal deaktivierte Schaltfläche. Der gewählte Name geht an
mstsc; Windows authentifiziert weiterhin. Es erfolgt keine automatische Übernahme
einer fremden Sitzung. Reservierungen und manuelle Sperren gelten auch dabei.

Der Agent bietet einen zusätzlichen, durch Windows authentifizierten Named-Pipe-
Kanal an. Die ACL enthält SYSTEM, Administratoren und das konfigurierte lokale
Lesekonto; keine anonyme oder allgemeine Benutzerfreigabe. Leserrechte enthalten
ausdrücklich nicht FILE_CREATE_PIPE_INSTANCE. FIRST_PIPE_INSTANCE verhindert,
dass der Agent sich an eine bereits fremd angelegte Pipe hängt. Client-SQOS lässt
keine Identitätsübernahme durch den Server zu. Erlaubt ist ausschließlich STATUS/1.
Die Antwort stammt aus einer neuen lokalen WTS-Abfrage, nicht aus einer Cachedatei.
Es gibt keine Befehlsausführung oder Abmeldung über diesen Kanal. Antworten sind
auf 64 KiB begrenzt; laufende Pipe-I/O hat Zeitlimits und wird bei Ablauf abgebrochen.
Windows-Verbindungsaufbau kann zusätzlich Zeit benötigen. Der Portalaufruf läuft
in einem Hintergrundthread. Fehler bestätigen keinen bisherigen Status als frisch.

Live-Antworten werden gegen Maschinenzuordnung geprüft. Ältere Dateisnapshots
überschreiben sie höchstens 90 Sekunden lang nicht; eine neuere Datei löst sie
vorher ab. Änderung von Ziel oder Agent-Zuordnung verwirft die zwischengespeicherte
Antwort. Die regelmäßige Veröffentlichung und die Sitzungsverlaufserfassung
bleiben von Live-Anfragen unabhängig. Die Agent-Installation schaltet den Kanal
ein; Konfiguration und Log liegen weiterhin im geschützten ProgramData-Verzeichnis.

180 Tests bestanden. Neue Prüfungen: Reservierungsgrenzen/Eigentümer, parallele
Konflikte, Admin-Edit ohne Besitzerwechsel, Auswahl trotz Namensabweichung,
ältere Datei nach Live-Antwort, falsche Agentidentität, echte native Pipe-Abfragen
mit Leerlauf/erneuter Verbindung, verworfener LOGOFF-Text und eingeschränkte ACL.
Die Live-Rundreise wurde unter Windows lokal mit etwa 4 ms gemessen. Kein fremder
Benutzer wurde zu Testzwecken abgemeldet. VPN, SMB-Richtlinien und Remote-Zugang
über PortalLeser müssen vor Ort geprüft werden. Karten, Details und Dialoge wurden
in Hell/Dunkel nativ gerendert. Umlaute in RDP-Diagnosen, lokale Darstellung des
letzten Agentzeitpunkts und der Reservierungshinweis wurden korrigiert.
Falsch typisierte Sitzungsfelder in Agent-JSON werden vor der Oberfläche abgefangen.

Beide Installer wurden mit PyInstaller gebaut. Die gebaute Agent-EXE 1.2.0
publizierte Statusdateien und beantwortete native Live-Abfragen (lokal 8–10 ms,
einschließlich der finalen EXE nach der zusätzlichen JSON-Validierung).
Beim ersten Starttest von Portal 0.2.4 blockierte die Windows-Anwendungssteuerung
auf dem Entwicklungs-PC sowohl Portal-EXE als auch Portal-Setup mit Fehler 4551.
Die Richtlinie wurde nicht umgangen. Der Start der fertig gebauten Portalversion
ist deshalb nicht bestätigt; Quellcode-/UI-Tests sind hiervon getrennt. Für einen
Rollout auf Geräten mit entsprechender Richtlinie ist eine reguläre IT-Freigabe
oder geeignete Signierung erforderlich. Agent-Setup fordert wie vorgesehen
Administratorrechte an (740 beim direkten Start ohne Erhöhung).

Eine erzwungene fremde Abmeldung ist technisch mit passenden Windows-Rechten
möglich, wurde hier aber nicht als zusätzlicher Admin-Button implementiert.
Die vorhandene Selbstabmeldung bleibt durch SID- und Sitzungsprüfung geschützt.

## Nachtrag: Wiederverbinden und eigene Abmeldung

Portal 0.2.3 gibt belegte Sitzungen für das ausdrücklich passende Anmeldekonto
wieder frei; unbekannte oder andere Konten und manuelle Sperren bleiben blockiert.
Karten, Detailansicht, Tabellenaktionen und Startprüfung verwenden dieselbe Regel.
Windows authentifiziert weiterhin die RDP-Verbindung; ein Kontonamenvergleich in
der Oberfläche ist keine Berechtigung.

Die neue bestätigte Direktabmeldung läuft im Hintergrund über native WTS-APIs.
Vor dem Aufruf werden die Sitzung und ihr Anmeldezeitpunkt live gelesen und die
Windows-SID des Sitzungsbenutzers mit dem Prozesstoken verglichen. Direkt vor der
Anforderung erfolgt eine erneute Sitzungsprüfung. Windows autorisiert den Aufruf.
WTS bietet keine atomare bedingte Abmeldung anhand einer Anmeldezeit; ein extrem
kurzer Wechsel zwischen letzter Prüfung und Aufruf bleibt eine API-Grenze.
Eine angenommene Anforderung setzt den Portalstatus nicht vorzeitig auf frei.

168 Tests bestanden, einschließlich Kontentrennung, wiederverwendeter Sitzungs-ID,
Wechsel während der Prüfung, Windows-Verweigerung und Oberflächenzuständen.
Keine echte Windows-Sitzung wurde für Tests abgemeldet. Die Direktabmeldung über
euer VPN und die Entra-Anmeldung muss vor Ort geprüft werden; SMB/RDP-Erreichbarkeit
allein genügt dafür nicht. Statusordner bleiben ohne ausführbare Remote-Befehle.
Karten, Detailansicht und Bestätigung wurden in Hell/Dunkel nativ gerendert.
Die gebaute Portal-EXE startete mit isoliertem Profil; Agent 1.1.0 schrieb im
isolierten Lauf weiterhin Online-Meldungen. Sein Setup benötigt erwartungsgemäß
Administratorrechte (Fehler 740 bei direktem Start ohne Erhöhung).

## Nachtrag: Windows-Zugangsdaten speichern

Die Speicherung in 0.2.1 übergab UTF-16-Bytes an PyWin32 CredWrite. Der native
Wrapper erwartet einen Unicode-String und löste deshalb einen TypeError aus.
Dies wurde gegen die installierte Windows-Schnittstelle reproduziert. 0.2.2
übergibt den String unverändert; Speichermeldungen unterscheiden nun eine bereits
erreichbare Freigabe vom fehlgeschlagenen Speichern und nennen Fehlercode/-klasse
ohne Exception-Argumente oder Kennwort. Die bisherigen gemockten API-Tests hatten
den Typfehler nicht erkannt; ein neuer Test prüft die echte Argumentkonvertierung.
Zusätzlich wurde einmal ein eindeutig benannter, synthetischer Windows-Testeintrag
geschrieben, dessen Metadaten gelesen und genau dieser Eintrag wieder entfernt.
157 Tests bestanden. Der Zugriff auf eure Freigabe bleibt der Praxistest vor Ort.
Portal 0.2.2 startete erfolgreich mit isoliertem Profil; die Portal-Setup-Selbstprüfung
bestand. Die neuen Fehlermeldungen wurden in Hell/Dunkel nativ auf Lesbarkeit geprüft.

## Nachtrag: Freigabeeinrichtung Remote-Ettlingen

Das Paket enthält zusätzlich `Statusfreigabe-einrichten.ps1` mit UTF-8-BOM für
Windows PowerShell. Es prüft den Zielrechner und Administratorrechte, erstellt
ein kennwortgeschütztes lokales Lesekonto sowie eine SMB-Freigabe und setzt separate
NTFS-Rechte für Leser, SYSTEM und Administratoren. Vorhandene Objekte werden nicht
verändert. Firewalländerungen erfolgen nur mit ausdrücklich angegebenen Quellnetzen.
Ein isolierter Test mit gemockten Windows-Konto-/SMB-Aufrufen prüft die erzeugten
ACLs, die Leseridentität, den Schutz bestehender Konten und die Fehlerbereinigung.
Auf Remote-Ettlingen wurde hier nichts installiert; der tatsächliche Zugriff bleibt
vor Ort zu prüfen. Aktueller Gesamtlauf: 154 Tests bestanden.

## Nachtrag: Netzwerk-Konfigurator

Der Dialog verbindet vorhandene SMB-Statusordner über WNetAddConnection2, prüft
Verzeichnis und JSON-Lesezugriff in einem Hintergrundthread und übernimmt den Pfad.
Optional werden Server-Zugangsdaten mit CredWrite im Windows-Benutzerprofil gespeichert.
Kein Kennwort wird an eine Shell übergeben oder in Portal-Dateien geschrieben.
Bestehende Verbindungen werden bei Fehler 1219 nicht getrennt. Das Speichern kann
bereits hinterlegte Windows-Zugangsdaten für denselben Server ersetzen; der Dialog
benennt dies ausdrücklich. Die erstmalige Einrichtung bleibt pro Benutzer erforderlich.
Windows-Netzwerkaufrufe werden für Tests gemockt; ein echter Zugriff auf eure Freigabe
und eine Wiederanmeldung mit gespeicherten Zugangsdaten stehen zur Prüfung vor Ort aus.
Aktueller automatisierter Prüfstand: 153 Tests und Ruff F.
Portal 0.2.1 und seine Setup-Selbstprüfung wurden erfolgreich ausgeführt. Der neue
Dialog sowie seine Schaltflächen wurden nativ in Hell/Dunkel geprüft. Die Agent-
Version bleibt 1.1.0; eine Neuinstallation des Agenten ist für den Konfigurator unnötig.

## Aktueller Nachtrag: rechnerweiter Agent

Der Agent startet jetzt als SYSTEM-Aufgabe beim Hochfahren, unabhängig von der
Benutzeranmeldung. WTS liefert alle Benutzersitzungen einschließlich Konsole und
Anmeldezeit. Eine echte WTS-Abfrage auf dem Entwicklungs-PC lieferte eine Sitzung
mit gültiger Anmeldezeit. Ein lokal gespeicherter, auf 200 Änderungen begrenzter
Verlauf wird mit den Statusdaten übertragen; die Details zeigen die letzten 20.
Die Abfrage kann sehr kurze Sitzungen verpassen; dies ist kein vollständiges Auditlog.

Beide Setup-EXEs enthalten einen Uninstaller und registrieren sich in Windows.
Agent-Upgrades entfernen bekannte frühere Installationen und Aufgaben aus den
Benutzerprofilen; Portal-Upgrades ersetzen ihren festen Installationsordner.
Beliebige portable Kopien werden nicht gesucht oder gelöscht. Inventar und gemeinsame
Statusdateien werden nicht entfernt. Löschpfade werden geprüft, Reparse Points abgewiesen.
Der Agent-Installer wurde mit gemockter Aufgabenplanung/Registry und echten Dateien
in einem isolierten Testverzeichnis geprüft: SYSTEM/Start bei Boot, Konfiguration,
Entfernung überholter Dateien, Deinstallation und Erhalt gemeinsamer Statusdateien.

Prüfstand: 142 Tests, Ruff F; native Renderprüfung von Karten in Hell/Dunkel und
beiden Setup-Oberflächen. Portal-/Agent-EXE starteten erfolgreich mit isoliertem
Profil; der Agent schrieb eine Online-Meldung. Portal-Setup-Selbstprüfung erfolgreich.
Die Agent-Setup-EXE fordert nun absichtlich Administratorrechte und konnte aus dem
nicht erhöhten Prüflauf nicht gestartet werden (740). Eine echte Aufgabenregistrierung,
ein Systemstart und Abmeldetest auf dem Ziel-PC stehen noch aus.

Offen für den tatsächlichen Dauerbetrieb ist der benutzerunabhängige Transport:
Ein SMB-Ordner muss dem System-/Computerkonto zugänglich sein. OneDrive im Profil
eines abgemeldeten Benutzers synchronisiert nicht weiter. Direkter Graph-Transport
ist nicht Bestandteil dieser Änderung. Die Umgebungsentscheidung wurde angefragt.

API-Referenzen: [WTSINFOW / LogonTime](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/ns-wtsapi32-wtsinfow),
[LocalSystem-Netzwerkidentität](https://learn.microsoft.com/en-us/windows/win32/services/localsystem-account).

Die folgenden Abschnitte dokumentieren die vorherigen Prüfstände bis 0.1.2;
für Agent-Start und Installation gilt der aktuelle Nachtrag samt Kurzanleitung.

## Nachtrag: dauerhafte Agent-Zuordnung

Die Screenshots zeigen drei gelesene Statusdateien ohne Maschinenzuordnung:
Agent-ID und Hostname NB05 treffen auf ein Portal-Verbindungsziel 192.168.2.74.
Version 0.1.2 ergänzt **Details → Agent zuordnen …**. Eine separate Agent-ID wird
im Inventar gespeichert; Maschinen-ID, Reservierungen und RDP-Ziel bleiben erhalten.
Explizite Zuordnungen haben Vorrang; ein Agent wird nicht zusätzlich per Hostname
einer anderen Maschine zugewiesen. Doppelte Agent-IDs werden gemeldet.
Der NB05-Fall mit drei Dateien ist als Regressionstest einschließlich Kartenanzeige,
Benutzerwechsel, Online-Zähler und Neustart abgedeckt.

## Nachtrag: Anmeldekonten und Setup-EXE

Die Maschinenkarten und Details enthalten eine Kontenauswahl mit **+ Benutzer
hinzufügen …**. Kontonamen werden pro Maschine gespeichert, die Auswahl pro
lokalem Benutzerprofil. Die Auswahl wird in RDP-Datei und Verbindungsstart verwendet.
Windows-Konten und deren Berechtigungen werden dadurch nicht angelegt oder geändert.

Der Agent-Build erzeugt zusätzlich die eigenständige
`dist-agent/Kirschke-RDP-Agent-Setup.exe`. Das Setup enthält den vollständigen Agenten,
verwendet eine benutzereigene geplante Aufgabe und prüft nach dem Start einen neuen
Online-Snapshot. Der Agent läuft ohne Konsolenfenster. Einrichtung und Funktionstest:
[Kurzanleitung](testbetrieb-kurz.md).

Aktueller Prüfstand: **135 Tests bestanden**, Ruff-Regeln der Gruppe F fehlerfrei,
PowerShell-Syntaxprüfung erfolgreich; Kontenauswahl, Dashboard und Agent-Einstellungen
in Hell/Dunkel nativ gerendert. Der aufgeklappte Diagnosebericht wurde ebenfalls geprüft.
Die Portal-EXE 0.1.2 wurde erfolgreich gebaut, ihr Start hier jedoch durch Windows-
Anwendungssteuerung mit WinError 4551 blockiert. Der Python-/Qt-Ablauf und die
native Darstellung sind geprüft; der Start dieser EXE bleibt auf dem Test-PC zu prüfen.
Der unveränderte Agent aus dem vorherigen Paket startete und schrieb eine aktuelle
Online-JSON; seine Setup-Selbstprüfung `--check` endete mit Exitcode 0.
Der Codepfad für
alte globale Logvariablen und nicht beschreibbare Logdateien ist mit Tests abgedeckt.
Eine echte Installation mit Aufgabenregistrierung und RDP-Anmeldung auf einem vorgesehenen
Ziel-PC bleibt Teil der Abnahme vor Ort.

## Ergebnis und Umfang

Pfadkorrektur: Der Agent-Statusordner ist unabhängig vom Inventar direkt einstellbar.
Das Portal hängt bei Auswahl von `agent-status` oder `agenten-status` keinen weiteren
Ordner an. Standard für Portal und Agent ist `RDP-Portal/remote/agenten-status` in der
Benutzerprofil-SharePoint-Bibliothek. Explizite Pfade werden lokal gespeichert;
alte Inventar-/Statuspfade werden ohne Verschieben bestehender Dateien erkannt.
Unlesbare oder ungültige Statusdateien zeigen Dateiname und Fehler in den Einstellungen.

Version 0.1.1 prüft den gesamten Weg von der Datei bis zur Anzeige: Ordnerfehler
werden ausdrücklich gemeldet, UTF-16-JSON wird erkannt und uneindeutige Hostnamen
werden nicht automatisch zugeordnet. IP-Adressen werden vollständig verglichen.
Die Agent-Einstellungen stehen oben; die Übersicht öffnet sie über **Agent-Diagnose**.
Direkte JSON-Auswahl und kopierbarer Bericht zeigen Pfade, Dateiinhalt-Metadaten,
Maschinenzuordnung und Zeitstempel. Regressionstests prüfen Online-Zähler,
Maschinenkarte, Benutzer, Detailansicht und Portal-Neustart mit geschriebenen Statusdateien.
Die konkrete JSON und SharePoint-Synchronisierung auf dem gemeldeten Zielsystem
waren hier nicht zugänglich; die Ursache dieses Einzelfalls ist daher noch nicht bestätigt.

Der aktive lokale Portal-/Agent-Pfad ist für einen kontrollierten Funktionstest
vorbereitet. Eine Freigabe für unbeaufsichtigten Mehrbenutzerbetrieb oder die
Cloud-Variante ergibt sich daraus nicht. Die reale RDP-Anmeldung und die
Installation auf den vorgesehenen Bürorechnern müssen noch abgenommen werden.

Geprüft wurden die Python-Pakete `portal_app`, `workstation_agent` und `shared`,
die Tests sowie Build-, Installations- und Einrichtungsdateien. Die Prüfung
kombiniert statische Analyse des gesamten Python-Bestands mit Ablaufprüfung
der Speicher-, RDP-, Admin-, Agent-, Ereignis- und UI-Pfade. Nicht jeder
Cloud-Zweig wurde ausgeführt. Lokale Buildprodukte sind keine weiteren Quellen.
`MODULENTWICKLUNG.md` im übergeordneten Verzeichnis beschreibt ein anderes
Berechnungsprojekt und ist kein technischer Vertrag für dieses Portal.

## Behobene Befunde

| Priorität | Befund und Auswirkung | Korrektur |
| --- | --- | --- |
| Hoch | Fehlerhafte JSON-Inventare wurden durch Ersatzdaten überschrieben; leere Inventare wurden wieder mit Beispielen gefüllt. | Bestehende ungültige Daten verursachen einen lesbaren Fehler; leere Inventare bleiben leer. |
| Hoch | Dreiwege-Merge ohne Schreibsperre; wiederholtes Speichern konnte zuvor unbekannte Fremdänderungen löschen. | Atomare Dateien mit eindeutigen temporären Namen, kooperative Windows-Dateisperre für denselben lokalen/SMB-Pfad und korrigierte Merge-Basis. |
| Hoch | Zwei neue Reservierungen mit unterschiedlichen IDs konnten denselben Zeitraum belegen. | Prüfung auf Überschneidungen und gelöschte Maschinen nach dem Merge. |
| Hoch | Ereignisschreiben bestätigte versehentlich eine gleichzeitig veränderte Inventardatei als bereits gelesen. | Signaturen werden nur für den tatsächlich bearbeiteten Kanal aktualisiert. |
| Hoch | Agent-Polling speicherte ungespeicherte Formularänderungen und erzeugte konkurrierende Inventarschreibzugriffe. | Heartbeats bleiben Anzeigezustand; sie lösen keinen Inventar-Speichervorgang mehr aus. |
| Hoch | Zeilenumbrüche in RDP-Benutzername oder Anzeigename konnten zusätzliche RDP-Einstellungen einschleusen. | Prüfung aller ausgegebenen Texte an der Ausgabegrenze; strukturelle Prüfung der RDP-Datei. |
| Hoch | WTS-Abfragefehler wirkten wie eine freie Maschine. | Fehler werden weitergegeben und als Agentfehler behandelt. Der bekannte Sitzungszustand bleibt erhalten. |
| Hoch | Ungültige Agent-Konfiguration wurde still ignoriert; PowerShell-BOM war nicht lesbar; JSON `false` wurde übergangen. | BOM-toleranter Leser, expliziter Fehler bei defekter Konfiguration und korrekte Verarbeitung boolescher Werte. |
| Hoch | Remote-Befehle hatten keinen vollständigen Berechtigungs-, Claim- und Wiederholungsschutz. | Automatische Remote-Befehlsausführung im Pilot abgeschaltet. |
| Hoch | Beschädigte Admin-Passwortdatei öffnete die Ersteinrichtung erneut. | Vorhandene Datei bleibt eine Zugangssperre; ungültige Hashparameter werden abgewiesen. AD-Fallback nur auf explizite Aktivierung. |
| Mittel | Veraltete/gelöschte Statusdateien ließen Maschinen online erscheinen; Zukunftszeitstempel blieben frisch. | Alterung auch ohne aktuelle Datei, Zukunftszeitstempel als Fehler und Vorrang der exakten Maschinen-ID. |
| Mittel | Bildschirmmodus, Laufwerks-, Audio- und Gatewayoption waren teilweise falsch. | Korrigierte RDP-Schlüssel, Auflösungsprüfung sowie gültige IPv4-/IPv6-Adressen. |
| Mittel | Agent-Erkennung und Übertragung verwendeten unterschiedliche Ereignisqueues; Neustarts luden Enums und Zeitstempel als Strings. | Gemeinsame Queue und typisierte Wiederherstellung; Ereignis-IDs verwenden vollständige UUIDs. |
| Mittel | Nicht übertragene Befehlsantworten wurden als erfolgreich gesendet markiert. | Nicht implementierte Übertragung wird als Fehler festgehalten. |
| Mittel | Lokale und UTC-Ereignisse konnten den Logfilter zum Absturz bringen. | Ereignisse mit UTC-Offset, lokale Anzeige und Datumsfilter bis zum gesamten letzten Tag. |
| Mittel | Portable App schrieb Logs in das Arbeitsverzeichnis. | Rotierende Logs im lokalen Benutzerprofil; verständlicher Startfehler bei unlesbarem Speicher. |
| Mittel | Installer startete einen zweiten, nicht von der Aufgabe verwalteten Prozess; lange Intervalle erzeugten regulär veraltete Statusanzeigen. | Start über die registrierte Aufgabe, Laufzeitlimit entfernt, Wiederanlauf und 5–60 Sekunden Intervall. |
| Mittel | Tote Namen im Graph-Konverter und ungenutzter Code. | Fehlende Importe/statische Verweise korrigiert; nicht verwendete Importe und toter Passwortzweig entfernt. |
| Mittel | Flag-Ereignisse wurden erstellt, aber nie gespeichert. | Audit-Ereignis nach erfolgreicher Persistenz; Längenprüfung und Berechtigungsprüfung beim Entfernen. |
| Mittel | Veraltete Detailobjekte nach Fremdänderungen; „frei“ trotz fehlender Agentinformation. | Detailansicht neu gebunden; unbestätigter Sitzungsstatus ausdrücklich angezeigt. |
| Mittel | Nach Dunkel-/Hellwechsel konnten Tabelleninhalte weiß auf weiß erscheinen. | Text- und Eckfarben für beide Tabellen-Themes explizit gesetzt und nativ gerendert. |

Die verwendeten RDP-Schlüssel wurden mit der
[Microsoft-Dokumentation zu RDP-Eigenschaften](https://learn.microsoft.com/en-us/azure/virtual-desktop/rdp-properties)
abgeglichen, insbesondere `screen mode id`, `audiomode`, `drivestoredirect` und
`gatewayusagemethod`.

## Was vor dem ersten Test noch fehlt

1. **Testumgebung benennen:** ein Portalrechner, ein Ziel-PC und ein eigenes
   Testkonto. Windows Pro/Enterprise/Server als RDP-Ziel; Netzwerk/VPN und
   Windows-RDP-Berechtigungen auf dem Ziel konfigurieren.
2. **Speicher festlegen und sichern:** bestehende `portal-state.json`,
   `portal-events.jsonl` und `portal-directory-users.json` vor der Umstellung
   kopieren. Bei OneDrive nur eine schreibende Portalinstanz; parallele Tests
   über denselben SMB-Pfad durchführen. Share-/NTFS-Rechte tatsächlich prüfen.
3. **Portal starten:** den gesamten frisch gebauten Ordner
   `dist\Kirschke-RDP-Portal` verwenden. Alte Beispielmaschinen in einem
   bestehenden Inventar selbst prüfen und gegebenenfalls entfernen.
4. **Echte Maschine registrieren:** Maschinen-ID, Hostname/IP, Benutzerformat,
   RDP-Zielmodus und Standort kontrollieren. Keine Serverzertifikatsausnahme
   pauschal aktivieren. Einstellungen ausdrücklich speichern.
5. **Adminzugang einrichten:** im lokalen Modus ein individuelles Passwort.
   Es schützt die Oberfläche im jeweiligen Benutzerprofil, nicht die gemeinsamen
   JSON-Dateien. AD nur nach separater Einrichtung und Prüfung aktivieren.
6. **Agent optional installieren:** auf dem Ziel-PC `Kirschke-RDP-Agent-Setup.exe`
   starten. Exakte Maschinen-ID und denselben synchronisierten Statusordner wie
   im Portal unter **Windows-Agent** angeben.
   Nach Installation und nach erneuter Anmeldung eine frische Statusdatei prüfen.
7. **Vorprüfung ausführen:** `python -m portal_app.preflight --storage "C:\Pilot\RDP-Portal" --json`.
   Exitcode 1 bedeutet einen gefundenen Fehler. Warnungen erfordern die folgenden
   praktischen Checks; Exitcode 0 ist keine vollständige Betriebsfreigabe.
8. **Anwendungssteuerung prüfen:** unsignierte EXE-Dateien können durch lokale
   Windows-Richtlinien blockiert werden. Für den Test-PC muss die IT gegebenenfalls
   die zulässige Verteilung/Freigabe bzw. Signierung klären. Den aktuellen
   Ausführungsprüfstand nennt der Nachtrag oben.

### Praktische Abnahme

- [ ] TCP/3389 und tatsächliche Anmeldung als Testnutzer funktionieren.
- [ ] Fenster-/Vollbildmodus, Audio, Laufwerke und Zwischenablage entsprechen den Einstellungen.
- [ ] Ein zweiter Verbindungsstart derselben lokalen Portalinstanz wird verhindert.
- [ ] Aktive und getrennte Sitzungen werden bei laufendem Agent erkannt.
- [ ] Stoppen/Abmelden des Agent-Benutzers erzeugt spätestens nach Ablauf der
  Schwellwerte „veraltet“ bzw. „offline“; „offline“ beweist keinen freien Ziel-PC.
- [ ] Flag setzen, entfernen, Neustart und Ereignislog funktionieren.
- [ ] Reservierungen bleiben nach Neustart erhalten; Überschneidungen werden abgewiesen.
- [ ] Zwei Portalprozesse auf demselben SMB-Pfad erhalten unabhängige Änderungen;
  gleichzeitige Änderungen am selben Datensatz führen zu einer Konfliktmeldung.
- [ ] Netzunterbrechung/Schreibschutz meldet einen Speicherfehler und zerstört keine Daten.
- [ ] CSV/JSON-Export, Benutzerprofil, Zeitzone und Tagesgrenzen sind korrekt.
- [ ] Wiederherstellung der Sicherung wurde in einem getrennten Testverzeichnis geprüft.

## Bewusst offene Grenzen und nächste Arbeitspakete

- **Cloud:** Entra-Anmeldung ist nicht mit `MainWindow` verbunden. Agent-Zertifikatbehandlung,
  MSAL-Tokenpersistenz, Graph-Feldendpunkte/Listen-IDs, Pagination, ETags und
  Idempotenz müssen als durchgehender Integrationspfad fertiggestellt und in
  einem Testtenant geprüft werden. Die bloße Existenz der Module belegt keine Betriebsfähigkeit.
- **Remote-Administration:** vor erneuter Aktivierung braucht es geprüfte
  Autorisierung, Ablaufdatum, atomaren Claim, dauerhaften Wiederholungsschutz,
  Zielbenutzer-/Sitzungsprüfung, Flag-/Override-Regeln und bestätigte Resultate.
  Das alternative Modul `workstation_agent/commands` ist ebenfalls nicht freigegeben.
- **Windows-Dienst:** bisheriger Installationsaufruf war nicht korrekt. Statt
  falscher Erfolgsmeldung verweist die CLI nun auf den unterstützten Aufgaben-Installer.
- **Agent ohne angemeldeten Benutzer:** interaktive Aufgaben liefern vor Anmeldung
  und nach Abmeldung keinen verlässlichen Dauerdienst. WTS-Sichtbarkeit anderer
  Benutzer muss mit den tatsächlichen Kontorechten geprüft werden.
- **Gemeinsame Dateien:** OneDrive kann unabhängige Replikate nicht atomar sperren.
  JSON-Dateien und lokale Adminpasswörter sind keine zentrale Sicherheitsgrenze.
  Logs sind nicht manipulationssicher. Umziehen des Speicherorts erfordert
  Anpassung aller anderen Portale und Agenten; Statusdateien werden nicht automatisch umgezogen.
- **Ereignisse/Outbox:** lokale Agent-Ereignisse werden noch nicht ins Portal-Log
  transportiert. Queue-Limits und Aufbewahrung sind kein verlustfreier SQLite-Outbox-Ersatz.
- **UI/Netzwerk:** einzelne DNS-, Diagnose- und AD-Abfragen laufen noch synchron
  im UI-Thread. Für größere Installationen Hintergrundjobs und Abbruchmöglichkeiten ergänzen.
- **Qualitätswerkzeuge:** die vollständige Ruff-Konfiguration meldet weiterhin
  zahlreiche Formatierungs-, Modernisierungs- und Namenskonventionsbefunde.
  Strenge Typprüfung ist nicht als bestanden nachgewiesen. Pydantic meldet die
  veraltete `json_encoders`-Konfiguration.
- **Reproduzierbarkeit:** feste Abhängigkeitsstände, CI, signierte Pakete und
  Intune-/Update-/Rollback-Verfahren fehlen noch.

## Nachweise der ursprünglichen Prüfung (0.1.0)

- **98 Tests bestanden**, davon 40 neue Regressionstests. Abschließender Lauf
  unter Windows/Python 3.13.14, Qt 6.11.1 mit `QT_QPA_PLATFORM=offscreen`.
  Ein vorheriger nativer Lauf scheiterte einmal an einer extern gesperrten
  Windows-Zwischenablage; die Testlogik wurde dafür nicht abgeschwächt.
- Alle **69 Python-Module** der Anwendung/Agent/shared erfolgreich importiert;
  `compileall` erfolgreich. `ruff check ... --select F` und `git diff --check` sauber.
- Alle vier PowerShell-Skripte erfolgreich mit dem PowerShell-Parser geprüft.
  Die Installeraktionen selbst wurden nicht auf dem Entwicklerkonto ausgeführt.
- Beide PyInstaller-Ordnerbuilds erfolgreich neu erzeugt.
- Portable **Agent-EXE tatsächlich ausgeführt**: Live-WTS-Abfrage sowie Start mit
  BOM-Konfiguration und Schreiben eines gültigen Snapshots in ein isoliertes
  Testverzeichnis erfolgreich. Testprozess anschließend beendet.
- Portable **Portal-EXE durch Windows-Anwendungssteuerung blockiert** (`4551`).
  Dieser Laufzeittest bleibt offen; es wurde keine Systemrichtlinie abgeschaltet.
- Native Windows-Renderprüfung der leeren Übersicht, Maschinenkarten in Hell/Dunkel,
  Logtabelle und Flagdialog: Lesbarkeit, Abstände und aktive/deaktivierte Schaltflächen geprüft.
- Mypy konnte wegen einer durch Windows-Anwendungssteuerung blockierten DLL nicht
  laufen. Pyright ist in dieser Umgebung nicht installiert. Die strenge
  Typprüfung wird daher ausdrücklich nicht als bestanden bewertet.

Zwischenstände liegen lokal unter `.pytest_cache` und werden nicht eingecheckt.
Es wurden keine echten RDP-Anmeldungen, AD-Gruppenänderungen oder Installationen
in die Windows-Aufgabenplanung vorgenommen.
