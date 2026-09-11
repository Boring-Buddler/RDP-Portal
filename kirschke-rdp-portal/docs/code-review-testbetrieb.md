# Codeprüfung und erster Testbetrieb

Stand: 11.09.2026, Portal 0.2.12 / Agent 1.3.0.

## Nachtrag: zielseitig autorisierte Agent-Abmeldung

Portal 0.2.12 und Agent 1.3.0 ersetzen den auf Entra-/Arbeitsgruppenrechnern mit
Windows-Fehler 5 abgewiesenen Remote-WTS-Aufruf. Der SYSTEM-Agent prüft lokal die
exakte Sitzung und führt die Abmeldung lokal aus. Eigentümeranfragen sind zusätzlich
an den vom Agenten beobachteten RDP-Client gebunden. Administrative Anforderungen
werden nur akzeptiert, wenn Windows die Pipe-Verbindung auf dem Ziel als Mitglied
der lokalen Administratorengruppe authentifiziert. Zeitfenster und Vorgangs-ID
schützen gegen Wiederholung; das Ziel-Admin-Kennwort wird nicht gespeichert.

## Nachtrag: natives Agent-Setup ohne PowerShell-Abhängigkeit

Agent 1.2.2 ersetzt im Ein-Datei-Setup den bisherigen internen Aufruf von
`Install-Agent.ps1` durch eine native Python-/Windows-Implementierung. Das Setup
prüft weiterhin Administratorrechte und Statusordner, kopiert die eingebetteten
Agentdateien, schützt `%ProgramData%\KirschkeRDPAgent`, schreibt die Konfiguration,
registriert die SYSTEM-Aufgabe über die Windows-Aufgabenplanung und bestätigt eine
frische Statusdatei. Die Deinstallation wird ebenfalls von der installierten
Setup-EXE ausgeführt.

Für eine neue Maschine erstellt dasselbe Setup nun auch das lokale Konto
`PortalLeser`, ein vom Administrator zweimal eingegebenes, nicht ablaufendes
Kennwort sowie die Freigabe `RDP-Status`. Auf NTFS- und Freigabeebene erhält das
Konto nur Lesen; SYSTEM und lokale Administratoren erhalten Vollzugriff. Das
Kennwort wird nur im Arbeitsspeicher an die native Windows-Benutzerverwaltung
übergeben und nicht protokolliert, gespeichert oder in einer Befehlszeile verwendet.
Vollständig bestehende Objekte werden unverändert wiederverwendet; Teilbestände und
abweichende Freigabeziele führen zum sicheren Abbruch.

Dadurch hängt die normale Installation nicht mehr von der PowerShell-
Ausführungsrichtlinie ab. Das Setup setzt keine Richtlinie und verwendet weder
`ExecutionPolicy Bypass` noch einen anderen Skriptumgehungsweg. Eine Windows-
Anwendungssteuerung kann die unsignierte EXE unabhängig davon weiterhin sperren;
das erfordert eine reguläre IT-Freigabe. Statuskanal und Rechte von `PortalLeser`
bleiben unverändert; es wurden keine echten Benutzer abgemeldet.

Der vollständige Prüflauf umfasst 216 bestandene Tests. Agent und Ein-Datei-Setup
wurden erfolgreich gebaut; die Agent-EXE 1.2.2 beendete den read-only Aufruf
`--status` mit Exitcode 0. Die finale Setup-EXE bestand `--check` mit Exitcode 0 und
öffnete ihren echten Installationsdialog; der Testdialog wurde geschlossen, ohne
**Jetzt installieren** auszulösen. Ein früherer Zwischenbuild war zunächst von der
Windows-Anwendungssteuerung blockiert. Die Richtlinie wurde nicht verändert.
Zusätzlich bestätigte die Archivprüfung: Agent-Payload vorhanden, kein eingebettetes
`Install-Agent.ps1`. Die Setup-Oberfläche wurde auf Lesbarkeit, Abstände und
Schaltflächenzustände geprüft. Build-Erfolg und tatsächlicher EXE-Start bleiben
getrennt ausgewiesen.

## Nachtrag: getrennte RDP- und Agentstatusziele

Portal 0.2.11 leitet das Ziel der read-only Liveabfrage aus dem Serveranteil des
expliziten maschinenspezifischen UNC-Fallbacks ab. Ein RDP-Profil kann dadurch eine
funktionierende IP-Adresse verwenden, während Named Pipe und Statusbestätigung dieselbe
Windows-SMB-Identität wie `\\RECHNER\RDP-Status` verwenden. Der native WTS-Aufruf
bleibt auf das RDP-Ziel beschränkt. Tests sichern ab, dass Statusprüfungen vor und nach
der Abmeldung den SMB-Server verwenden, der Hilfsprozess aber die RDP-IP erhält. Es
wurde keine reale Sitzung abgemeldet. Der zuvor entfernte globale RDP-Hinweis ist im
0.2.11-Paket nicht mehr enthalten.

## Nachtrag: WTS-Handle im Abmelde-Hilfsprozess

Der gemeldete Prozesscode `3221226356` entspricht `0xC0000374`
(`STATUS_HEAP_CORRUPTION`). `win32ts.WTSOpenServer` liefert einen selbstverwalteten
PyWin32-Handle. Der bisherige direkte Aufruf von `win32ts.WTSCloseServer(handle)`
schloss zwar den nativen Handle, markierte den Python-Wrapper aber nicht als geschlossen;
beim Zerstören des Wrappers konnte derselbe Handle erneut geschlossen werden. Der
Hilfsprozess verwendet jetzt `handle.Close()`, sodass PyWin32 den Handle schließt und
seinen internen Wert gleichzeitig löscht. Regressionstests decken den Erfolgs- und
Fehlerpfad ab, ohne eine reale Sitzung abzumelden. Der `STATUS/1`-Kanal und die Rechte
von `PortalLeser` bleiben unverändert.

Das gelbe globale Banner für aktive oder geschlossene lokale RDP-Fenster wurde auf
Wunsch entfernt. Beendete `mstsc`-Prozesse werden weiterhin als lokales Ereignis
erfasst, beeinflussen die Oberfläche aber nicht mehr. Die sichtbare Belegung stammt
weiterhin aus dem Live-Agentstatus beziehungsweise dem Datei-Fallback.

## Nachtrag: maschinenspezifische Fallbacks und Statuspriorität

Portal 0.2.9 speichert den Datei-Fallback clientlokal pro Maschinen-ID. Die
Eingabe befindet sich in den jeweiligen Maschinendetails und verbindet vorhandene
SMB-Freigaben weiterhin ausschließlich mit dem Lesekonto. Ein früherer globaler
Ordner wird bei einem Update als kompatibler Alt-Standard verwendet, bis eine
Maschine einen eigenen Pfad erhält. Unterschiedliche Fallbackordner werden getrennt
gelesen; eine Datei kann nur innerhalb des Ordners ihrer Maschine zugeordnet werden.

Eine erfolgreiche Liveantwort bleibt auch bei fehlender oder nicht lesbarer
Fallbackfreigabe maßgeblich. Ohne bestätigten Live- oder Dateistatus bleibt die
Karte bewusst grau; Ping allein bestätigt keinen Agenten. Farbige Karten verwenden
einen 4-Pixel-Rahmen, graue einen 2-Pixel-Rahmen. Das Dashboard sortiert grüne,
freie Maschinen vor blauen, belegten Maschinen; Warn-/Fehlerzustände folgen und
unbestätigte graue Karten stehen zuletzt. Das Qt-gezeichnete Rechnersymbol wird bei
Statusänderungen nun ebenfalls neu eingefärbt.

Der Agent bleibt bei 1.2.1. Der aktualisierte Agent-Installer verwendet als Vorgabe
den lokalen SYSTEM-Pfad `C:\RDP-Portal-Daten\agenten-status` und erklärt den
separaten Portalpfad `\\ZIELRECHNER\RDP-Status`. Installer, Starter und AD-Helfer
fordern keine `ExecutionPolicy Bypass` mehr an. Eine Richtlinienblockade wird nicht
umgangen und muss organisatorisch freigegeben werden. Der Statuskanal bleibt auf
`STATUS/1` beschränkt; `PortalLeser` erhält keine Abmeldeberechtigung. Kein echter
Benutzer wurde für die Prüfung abgemeldet.

Der vollständige Prüflauf umfasst 197 bestandene Tests; Syntax- und Ruff-Prüfung
sind ebenfalls fehlerfrei.

Portal-, Agent- und beide Setup-Builds wurden erfolgreich erzeugt. Die eingebauten
`--check`-Prüfungen beider Setup-EXE-Dateien endeten mit Exitcode 0. Der tatsächliche
Start der finalen Portal-EXE 0.2.11 war erfolgreich; sie lief im Kurztest weiter und
wurde danach regulär als Testprozess beendet. Der Statusaufruf der unveränderten
Agent-EXE wurde auf diesem Entwicklungsrechner dagegen von der Windows-
Anwendungssteuerungsrichtlinie blockiert. Das ist getrennt vom Build-Erfolg zu
bewerten. Die Richtlinie wurde weder verändert noch umgangen; für blockierte Dateien
ist weiterhin eine reguläre Freigabe/Signierung nötig. Der Python-/Qt-Stand wurde
separat gerendert und visuell geprüft.

## Nachtrag: isolierter WTS-Aufruf und Erfolgsbestätigung

Nach dem Vor-Ort-Bericht, dass beim Abmeldeversuch die Portaloberfläche beendet
wurde, die Zielsession aber bestehen blieb, führt Portal 0.2.8 den nativen
`WTSLogoffSession`-Aufruf nicht mehr im Qt-Prozess aus. Ein kurzlebiger Hilfsprozess
mit demselben Windows-Token führt ausschließlich den bereits zweimal per Live-Status
geprüften Aufruf aus und wartet auf dessen Ende. Ein nativer Fehler bleibt dadurch
vom Portalprozess isoliert; die Windows-Berechtigungsentscheidung ändert sich nicht.

Nach einem Exitcode 0 liest das Portal `STATUS/1` nochmals frisch. Nur wenn die
konkret geprüfte Kombination aus Sitzungsnummer, Benutzer und Anmeldezeit nicht
mehr aktiv ist, wird Erfolg gemeldet. Andernfalls bleibt die Belegung sichtbar und
der Fehler sagt ausdrücklich, dass Windows den Aufruf beendet, der Agent dieselbe
Sitzung aber weiterhin gemeldet hat. Der Statuskanal akzeptiert weiterhin nur
Statusanfragen; kein Agent- oder SMB-Abmeldebefehl wurde hinzugefügt. Automatisierte
Tests verwenden ausschließlich Attrappen und melden keinen echten Benutzer ab.
Der vollständige Prüflauf umfasst nun 190 bestandene Tests.

## Nachtrag: eindeutige Sitzung und Zielrechner ohne Intune

Portal 0.2.7 überspringt beim Wiederverbinden den Kontodialog, wenn der Agent genau
ein aktives Sitzungskonto meldet. Der gemeldete Name wird nur als RDP-Benutzerhinweis
verwendet; die Windows-Authentifizierung und Berechtigungsprüfung bleiben unverändert.
Bei mehreren Sitzungskonten bleibt die explizite Auswahl erhalten. Regressionstests
decken beide Zweige ab.

Die Kurzanleitung trennt nun ausdrücklich Intune-Verwaltung, Entra-Gerätebeitritt,
Portal-Inventar, Agent-Status und Windows-RDP-Anmeldung. Ein Zielrechner wird manuell
im Portal angelegt. Für weitere Arbeitsgruppen-/Entra-Rechner dokumentiert sie den
erforderlichen Parameter `-ExpectedComputerName` bei der lokalen Statusfreigabe.
Agent und Statuskonto erzeugen keine RDP-Benutzer und erteilen keine
Remoteanmelderechte. Agent 1.2.1 bleibt unverändert.

## Nachtrag: eigene getrennte Entra-Sitzung und Live-Vorprüfung

Portal 0.2.6 trennt die beim Programmstart erkannte Windows-Prozessidentität vom
frei wählbaren RDP-Anmeldekonto. Dadurch wird eine getrennte eigene Sitzung wie
`AzureAD\Benutzer` auch dann als eigene Sitzung dargestellt, wenn im Dropdown
„Standard · Windows-Anmeldung“ steht oder für RDP ein abweichender Entra-UPN
verwendet wird. Die Karte zeigt dann wie vorgesehen **Wiederverbinden** und den
roten Knopf **Abmelden**. Eine Dropdown-Auswahl allein erklärt eine fremde Sitzung
weiterhin nicht zur eigenen; vor der Ausführung bleibt die native SID-Prüfung
maßgeblich.

Der Vor-Ort-Test zeigte außerdem, dass Remote-Ettlingen die zusätzliche direkte
WTS-Informationsabfrage mit Windows-Fehler 5 verweigert, während der authentifizierte
Agent-Livestatus funktioniert. Die Sicherheitsprüfung liest Benutzer,
Sitzungsnummer und Anmeldezeit deshalb jetzt zweimal frisch über den bestehenden
reinen `STATUS/1`-Kanal. Der Kanal erhält weiterhin keinen Abmeldebefehl. Erst danach
ruft das Portal separat `WTSLogoffSession` auf; Windows entscheidet mit den Rechten
des Portalprozesses über Annahme oder Ablehnung. Der Status wird nicht vorzeitig
auf frei gesetzt. Fehler unterscheiden nun fehlenden Livestatus, anderen Agenten,
verschwundene Sitzung, geänderten Benutzer und geänderte Anmeldezeit.

187 Tests bestanden. Kein echter Benutzer wurde während der automatisierten oder
manuellen Diagnose abgemeldet.

## Nachtrag: automatische Statuspflege und getrennte Abmeldungen

Das Maschinendashboard startet beim Öffnen sofort eine direkte Agentabfrage und
wiederholt sie im lokal gespeicherten Intervall. Unter **Einstellungen →
Statusaktualisierung** sind 2 bis 60 Sekunden einstellbar; der Standard beträgt
5 Sekunden. Ein eigener Threadpool begrenzt die Parallelität auf vier Zielrechner.
Pro Rechner ist höchstens eine Anfrage gleichzeitig aktiv. Fehler eines Rechners
halten andere Abfragen nicht auf; nach Fehlern wird dessen Wiederholung schrittweise
bis höchstens 60 Sekunden verzögert. Die vorhandenen Pipe- und I/O-Zeitgrenzen
bleiben wirksam.

Karten zeigen Statusquelle und Alter, zum Beispiel „Live · vor 3 Sekunden“ oder
„Datei-Fallback · vor 45 Sekunden“. Scheitert Live, wird eine neuere Agent-JSON
verwendet; eine ältere Datei überschreibt keinen neueren Live-Stand. Solange der
letzte Live-Stand neuer ist, wird er ausdrücklich als nicht erreichbar/veraltet
gekennzeichnet und nicht als aktuelle Erreichbarkeit gewertet. Die nächste
erfolgreiche Direktabfrage schaltet automatisch auf Live zurück. Statusänderungen
werden in vorhandene Karten übernommen, sodass Scrollposition, Kontenauswahl und
geöffnete Auswahlmenüs erhalten bleiben.

Die Hauptaktionen unterscheiden freie Rechner, eigene verbundene Sitzungen,
eigene getrennte Sitzungen sowie fremde Sitzungen und Reservierungen. Die eigene
rote **Abmelden**-Aktion prüft den Windows-Kontonamen, die Sitzungsnummer, den
Anmeldezeitpunkt und die SID frisch und unmittelbar vor `WTSLogoffSession` erneut.
Danach wird sofort neu abgefragt; erst ein bestätigtes Sitzungsende macht die
Maschine frei. Bei einer getrennten eigenen Sitzung bleiben **Wiederverbinden**
und **Abmelden** nebeneinander verfügbar. Fremde Belegungen bieten diese normale
Aktion nicht an.

Im freigeschalteten Adminbereich gibt es davon getrennt **Notfall-Abmeldung …**.
Sie prüft Benutzer, Sitzungsnummer und Anmeldezeit ebenfalls zweimal und übergibt
die Anforderung direkt an Windows. Maßgeblich sind die tatsächlichen Windows-Rechte
des Portalprozesses auf dem Zielrechner. Das Lesekonto `PortalLeser` erhält weder
Administrator- noch Abmelderechte; der Agentkanal akzeptiert weiterhin ausschließlich
`STATUS/1` und keine administrativen Befehle. Gerade beim dauerhaft laufenden,
Entra-joined und nicht AD-domain-joined Ziel Remote-Ettlingen ist die Autorisierung
vor Ort zu prüfen.

Die Oberfläche verwendet die Windows-/Qt-Systemschrift und skalierbare Punktgrößen.
Fließtext, Eingaben und Schaltflächen wurden vereinheitlicht. Geschlossene
Auswahllisten verändern sich beim Mausrad nicht und geben das Scrollen an die Seite
weiter; nach bewusstem Öffnen funktionieren Mausrad und Tastatur normal.

186 Tests bestanden. Hinzu kamen Prüfungen für Intervallgrenzen und Persistenz,
parallele/nicht überlappende Liveabfragen, Rückstau nach Fehlern, Fallback und
automatische Rückkehr, veraltete Quellen, Kartenaktionen, verweigerte Abmeldungen,
Admin-WTS-Neuprüfung sowie geschlossenes/geöffnetes Dropdown-Verhalten. Es wurde
kein echter Benutzer abgemeldet. Karten, Details, Einstellungen und Adminansicht
wurden in Hell/Dunkel bei 100 %, 125 % und 150 % Skalierung nativ gerendert und
auf Lesbarkeit geprüft.

Portal- und Agent-Installer wurden erfolgreich mit PyInstaller gebaut. Die lokalen
PowerShell-Buildwrapper waren durch die vorhandene Ausführungsrichtlinie gesperrt;
die Richtlinie wurde nicht verändert oder umgangen. Stattdessen wurden die in den
Skripten dokumentierten PyInstaller-Aufrufe direkt ausgeführt. Build-Erfolg und
Programmstart wurden getrennt geprüft: Die Portal-EXE 0.2.6 startete und blieb bis
zum kontrollierten Ende der Testinstanz aktiv. Die Agent-EXE 1.2.1 beendete
`--status` mit Exitcode 0, und beide Setup-Selbstprüfungen `--check` endeten beim
finalen Build mit Exitcode 0. Ein vorheriger Start des Portal-Setups wurde auf
demselben Rechner noch von der lokalen Anwendungssteuerungsrichtlinie blockiert
(bekanntes Fehlerbild 4551). Die Richtlinie wurde weder verändert noch umgangen;
die unterschiedliche Richtlinienentscheidung ist daher keine Rolloutgarantie.
Installation und Notfall-Abmeldung auf Remote-Ettlingen bleiben bewusste Vor-Ort-Tests.

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
   starten. Exakte Maschinen-ID und den lokalen Ordner
   `C:\RDP-Portal-Daten\agenten-status` angeben. Danach in den Details dieser
   Portalmaschine deren `\\ZIELRECHNER\RDP-Status`-Fallback verbinden.
   Nach Installation und nach einem Neustart eine frische Statusdatei prüfen.
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
