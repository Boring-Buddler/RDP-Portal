"""The one place the portal and agent versions are defined.

Before this, the portal version existed in four files (plus two that still said
0.1.0) and the agent version was hardcoded in six, two of which fell back to
1.0.0 and stamped that into event records.  Everything that reports a version
imports it from here.

``portal_app.version`` re-exports PORTAL_VERSION so existing imports keep working.
"""

from __future__ import annotations

# 0.6.1: both setup windows name the version they are about to install. The
# portal setup had the number hardcoded and it had gone three versions stale --
# it offered to install 0.2.12 while 0.5.x sat in the package. Along the way:
# every PowerShell script with German text now carries a byte order mark, without
# which Windows PowerShell 5.1 reads the file as ANSI and mangles it -- an en dash
# then even breaks the parser.
# 0.6.0: the SharePoint folder is no longer the default storage location. It was
# a guess about how one person's OneDrive is laid out, and it failed differently
# on every PC that did not match -- refused halfway up the profile, or refused
# inside a synced library the account may not write to. The portal now stores
# locally unless a shared folder is set in the admin area, and an installation
# that already keeps its state in the old folder keeps finding it there.
# 0.5.5: the shared storage folder is used only when the synchronised library is
# actually present. The profile part always came from %USERPROFILE%; the folder
# chain under it was the assumption that broke. Creating it anyway produced a
# look-alike that never syncs, so everyone would believe they share a state that
# in truth exists once per machine. Without the library the portal stays local.
# 0.5.4: two things that made the portal unusable on a colleague's PC. The setup
# started PowerShell without -ExecutionPolicy Bypass, so a machine whose policy
# forbids scripts refused to install -- as administrator too, with a message that
# reads like a rights problem. And the first run died with an unhandled traceback
# when the configured storage folder could not be created: it now falls back to a
# local folder and says so, instead of never showing a window.
# 0.5.3: your own session without a window is now blue/orange dashed instead of
# solid orange, so the orange dash means one thing everywhere -- somebody holds
# the machine without being connected -- while the base colour says who. Border
# weight still follows what you can act on: four pixels for yours, two for a
# colleague's. Also: the quick resolution list now reaches 2K and 4K, but only as far as
# the screen in front of you goes -- a session larger than the panel is only
# reachable by scrolling. A panel whose size is not one of the standard steps
# joins the list as its own entry, so 'as large as this screen allows' can be
# picked at all.
# 0.5.2: the same account name in two Unicode spellings no longer counts as two
# people. Windows reports 'Schaelike' with a precomposed umlaut in one place and
# with a combining diaeresis in another; they look identical and never compared
# equal, so a person's own machine stayed marked as occupied by a stranger even
# after entering the account exactly as displayed. Also: a stored 'Anmelden als'
# choice is kept even when no session currently reports it, instead of silently
# falling back to the default; and 'Das bin ich' moved to the detail page.
# 0.5.1: the portal now also remembers the spelling the agent reports for a
# session it opened itself. Remembering only the account it connects with was
# useless for Entra, where the UPN and the reported profile name share nothing
# -- a person's own machine kept showing up as occupied by a stranger.
# 0.5.0: the automatic target no longer insists on a name that cannot be
# resolved -- across two sites a short Windows name has no chance, and RDP
# failed on it while the IP address next to it worked. The same check now
# guards the agent channel, whose server name comes from the fallback share.
# Also: a foreign session whose window is closed is drawn violet/orange
# dashed, and one click records a reported account as your own.
# 0.4.1: the machine card is a fixed 4:3 tile instead of stretching across the
# window, and carries a quick choice of resolution and all-monitors right next
# to the name. A checkbox outside a dialog was unstyled in the light theme.
# 0.4.0: reservations travel through each machine's own agent, so a portal on
# another PC sees a booking without a shared state file. Also: a real Windows
# application icon, the machine card shows the site instead of repeating the
# name, adding a machine lives in the admin area only, and the calendar is
# readable in both themes.
# 1.5.0 (agent): RESERVE/1 -- the agent keeps its own machine's reservations
# and reports them with every snapshot. Older agents report none, which the
# portal distinguishes from "none booked".
# 0.3.9: an account entered under "Weitere eigene Windows-Konten" now also
# passes the portal's ownership check for a logoff. The agent still requires
# the request to come from the machine that opened the session.
# 0.3.10: a console session can now be ended after a short RDP takeover, and
# 1.4.3 (agent): the same machine is recognised across IPv4, IPv6 and its name,
# so a logoff from exactly the right computer is no longer refused.
# 1.4.2 (agent): a refused logoff now names the requesting machine and the one
# that built the session, instead of only stating that they differ.
# 1.4.1 (agent setup): an update pre-fills the machine ID, status folder and
# interval from the installed agent instead of resetting them to the host name.
# 0.3.8: the detail page now shows the agent version and, per session, whether
# it is the console and which RDP client the agent reports -- the two facts a
# refused logoff turns on, and both were invisible.
# 0.3.7: violet moved into the middle of the only gap on the colour wheel, and
# weight now follows what you can act on: full border for usable machines,
# a quieter one for everything you cannot touch.
# 0.3.6: violet for a machine somebody else holds -- brown and amber both sat
# too close to the orange of your own idle session on a card border.
# 0.3.5: one rule for "is this the agent of this machine" -- the status channel
# and the logoff path no longer disagree about a generated portal ID.
# 0.3.4: brown for every machine somebody else holds (signed in or booked),
# blue only for your own. "Berechnung laeuft" retired; reservations replace it.
# 0.3.3: raise an already running RDP window instead of refusing, and recognise
# further Windows accounts as your own so a local account is not a stranger.
# 0.3.2: brown for a running calculation, and a colour key under the grid.
# 0.3.1: one machine state decides colour and buttons; orange marks an own session
# holding a machine with no portal window, violet a foreign reservation.
# 0.3.0: typed Windows identity, SID-based session ownership, one button matrix.
# 0.6.2: portable profile paths and protocol-based console/RDP classification.
# 0.6.3: one bundled admin password replaces profile-local password setup.
# 0.6.4: explicit admin save to portable state beside the portal executable.
# 0.7.0: a connection assistant replaces the two-step "add a machine, then go
# find its agent" dance. It sweeps the network for machines running an agent --
# the pipe answers whether it exists before it checks who is asking, so agents
# are findable without credentials and identifiable with them -- offers every one
# it found for linking or for a new machine, derives the site from the address
# (192.168.2.x Ettlingen, 192.168.20.x Munich) and sets up the file fallback
# itself. It opens on its own when the inventory is empty, which is the first
# start. Two things it fixes on the way: agent assignment used to read the status
# folder of the very machine being assigned, so the list was empty exactly when
# it was needed; and nothing ever re-established the SMB session after a restart,
# so the fallback -- and with it the live channel, whose pipe target comes from
# the same server -- stayed dead until somebody re-ran the setup dialog by hand.
# The reader account may now ship with the release (see
# portal_app/services/reader_account.py, which is empty in the repository and
# filled at build time); a password entered on a PC still wins over it.
# 0.8.0: die Oberfläche folgt der Windows-Schriftgröße, und drei Dinge, die sich
# gegenseitig blockiert haben, sind entkoppelt. Eine fremde Reservierung sperrt
# nichts mehr: Sie hat gleichzeitig den Reservierenden (wegen der laufenden
# fremden Sitzung) und den Angemeldeten (der weder zurück auf seine Sitzung kam
# noch sie beenden konnte) ausgesperrt, und niemand konnte den Zustand
# auflösen. Aus dem toten "Maschine besetzt" wird ein Verbinden-Knopf, der
# vorher sagt, wer die Maschine hält und dass Windows die bestehende Sitzung
# dabei trennt; Farbe und Randstärke der Karte bleiben unverändert. Die
# Kontowahl überlebt wieder einen Abgleich des gemeinsamen Stands -- ein Konto
# aus einer gemeldeten Sitzung steht weder in login_accounts noch im
# username_hint, und genau dagegen prüfte der Store beim Laden, was alle paar
# Sekunden zu einem stillen Rücksprung auf "Standard" führte. Jeder ordnet die
# Maschinenkarten für sich selbst an, per Ziehen und in der eigenen
# Benutzerdatei. Behoben: Der Verbindungsassistent kürzte eine IP-Adresse wie
# ein DNS-Label und baute daraus \\192\RDP-Status, was Windows mit Fehler 67
# beantwortete; und der Fallback-Dialog schlug ein Lesekonto vor, das nicht zum
# Server im Pfad gehörte.
# 1.6.0 (agent): CLAIM/1 -- das Portal meldet dem Agenten, welcher Mensch sich
# unter welchem Windows-Konto aufgeschaltet hat, und der Agent bindet die
# Meldung an die Sitzung, die er dazu findet. Gebraucht für Maschinen mit einem
# einzigen gemeinsamen Konto: Dort erkannte bisher jedes Portal den Kontonamen
# als den eigenen wieder und zeigte die Maschine allen als "von dir belegt".
# Weil jede vom Portal gestartete Verbindung gemeldet wird, ist das Ausbleiben
# einer Meldung selbst eine Auskunft -- die Karte schreibt dann "direkt
# verbunden". Ältere Agenten melden keine Aufschaltungen, was das Portal von
# "niemand hat sich gemeldet" unterscheidet.
# 0.8.1: das Ereignisprotokoll kann in einen gemeinsamen Netzwerkordner gelegt
# werden (Admin → Gemeinsames Protokoll). Gebraucht, seit klar ist, dass eine
# Installation über das Setup nach %LOCALAPPDATA%\Programs\KirschkeRDPPortal
# geht: Der gemeinsame Stand liegt neben der EXE und ist dort privat, jeder
# pflegt also sein eigenes Inventar. Das Protokoll ist der Teil, den man
# trotzdem zusammen sehen will. Beim Einrichten wird wirklich geschrieben und
# nicht nur verbunden -- die Agentenfreigaben geben nur Leserecht, und das
# fiele sonst erst beim ersten Ereignis auf. Ein wachsendes gemeinsames
# Protokoll löst außerdem keinen vollständigen Neuaufbau des Inventars mehr
# aus; nachgeladen werden nur die neuen Einträge.
# Behoben: Der Adminbereich behauptete bei einer lokalen Installation eine
# "Verteilung nach SharePoint-Synchronisierung". Die Prüfung dahinter verglich
# gegen %LOCALAPPDATA%\KirschkeRDPPortal und traf den Installationspfad nie --
# wer dem Text folgte, wartete auf eine Verteilung, die es nicht gibt.
# 0.8.2: die Maschinenkarten werden an einem eigenen Griff verschoben -- drei
# Punkte unter dem Verbinden-Knopf, an denen der Zeiger zur greifenden Hand
# wird. Vorher nahm die ganze Karte das Ziehen entgegen, und das ging nicht
# zusammen: Derselbe Mausdruck oeffnete die Maschinenseite, die dann jedes
# Verschieben abfing -- die Anordnung war eingebaut, aber nicht erreichbar.
# Ausserdem sortiert der Zustand nicht mehr mit. Eine Karte wanderte durchs
# Raster, sobald sich jemand verband oder abmeldete, und man suchte seine
# Maschine nach jeder Aktualisierung neu; eine Kachel merkt man sich aber ueber
# ihren Platz. Ohne eigene Anordnung gilt jetzt der Name, und wie es um eine
# Maschine steht, sagt weiterhin ihre Farbe.
# 0.9.0: kein SharePoint und kein OneDrive mehr. Gemeinsame Daten laufen
# ausschließlich über das Netzwerk: die Pipe und die Statusfreigaben der
# Agenten und, neu, ein gemeinsames Inventar auf einer SMB-Freigabe (Admin →
# Gemeinsames Inventar). Dort schreiben alle Portale direkt, unter einer
# Byte-Sperre und mit Drei-Wege-Abgleich; eine gleichzeitige Änderung an
# derselben Maschine wird abgelehnt statt überschrieben. Ist die Freigabe weg,
# legt das Portal dort nichts an, sondern arbeitet sichtbar im Notbetrieb mit
# der zuletzt gelesenen Kopie. Kein Ordner, den das Portal beschreibt, darf in
# OneDrive oder einer synchronisierten SharePoint-Bibliothek liegen -- erkannt
# über Umgebung, Registry, Sync-Roots und Cloud-Dateiattribute; eine portable
# EXE dort legt ihren Stand im lokalen Profil ab. Der alte SharePoint-Ordner
# und der Eintrag storage_directory werden nicht mehr gelesen, die
# Graph-/SharePoint-Module sind entfernt. Außerdem prüft der Abgleich alle 5 s
# im Hintergrund, weil schon ein stat auf einer Freigabe hängen kann.
# 0.9.1: "Anmelden als" gilt. Bei einer fremden Sitzung ersetzte das Portal das
# gewählte Konto still durch das Sitzungskonto; und hatte Windows für das Ziel
# Anmeldedaten eines anderen Kontos gespeichert, nahm Remotedesktop diese. Das
# Portal fragt jetzt vor dem Start, ob der gespeicherte Eintrag weg soll.
# "Belegt von" ordnet Aufschaltmeldungen in jeder Schreibweise des Kontos zu,
# die jüngste gewinnt, und die Nachmeldung läuft bei jeder neuen Verbindung.
# Die eigene Sitzung ohne Fenster zeigt ein oranges PC-Symbol statt eines
# gestrichelten Rands.
# 0.9.2: kein Text wird mehr abgeschnitten. Karten werden so hoch wie ihr
# Inhalt, lange Namen enden mit "…" und stehen im Tooltip, Filter und
# Knopfzeilen brechen um, Admin und Maschinendetails scrollen, Rückfragen
# werden so breit wie ihre Knöpfe, und Qt-Standardknöpfe sind deutsch.
# "Belegt von" nennt Person und Windows-Konto ("… als NB12KI\Codex").
# 0.9.3: Entra-Konten werden ohne Webanmeldung als AzureAD\name@firma.de
# übergeben, sobald die Maschine Entra-Sitzungen meldet oder der Portal-Benutzer
# selbst mit Entra angemeldet ist. Die bloße E-Mail-Adresse lehnte Windows mit
# "nicht zur Remoteanmeldung autorisiert" ab, obwohl normales RDP ging; die
# Warnung "Entra-Anmeldung fehlt" mit "Trotzdem starten" entfällt. Außerdem
# tragen Aufschaltmeldungen den Namen des Portal-PCs und gelten nur für
# Sitzungen, die von diesem PC aus aufgebaut wurden.
# 0.9.4: der Freigabedialog legte für das Freigabekonto einen Windows-Eintrag
# für den ganzen Server an ("Domain:target=192.168.2.66", PortalLeser). Den nahm
# auch mstsc, und jede RDP-Verbindung zu diesem Rechner scheiterte mit "nicht
# zur Remoteanmeldung autorisiert". Gemerkt wird das Konto jetzt unter einem
# eigenen Portal-Eintrag; alte Einträge dieser Art entfernt das Portal beim
# Start, vor dem Verbinden wird ein verbliebener gemeldet. Inventar- und
# Protokollfreigabe verbindet das Portal deshalb beim Start selbst. Dazu: Die
# eigenen Windows-Konten stehen bei jeder Maschine unter "Anmelden als", ohne
# Entra-Profilnamen, mit denen keine Anmeldung möglich ist. Ein Konto lässt sich
# als gemeinsam genutzt markieren (RDPUser); dessen Sitzung gilt nur als eigene,
# wenn Windows diesen PC als RDP-Client meldet.
# 0.9.5: die gebaute 0.9.4 startete nicht: CredEnumerate lädt für Zeitstempel
# intern win32timezone nach, das PyInstaller nicht mitgepackt hatte. Das Modul
# wird jetzt ausdrücklich importiert, und ein Fehler beim Aufräumen alter
# Anmeldedaten verhindert den Start nie mehr. Betraf auch CredRead: Ein selbst
# gespeichertes Lesekonto wurde in der EXE bisher still nicht gelesen.
# 0.9.6: ein Klick auf Verbinden startet auf einer freien Maschine direkt.
# Die Rückfragen "Serveridentität bestätigen" und "IP-Verbindung ohne
# Webkonto" sowie die Meldung "Verbindung gestartet" entfallen. Die
# Serveridentität prüft Windows selbst anhand des Zertifikats; die Ausnahme
# bleibt eine Einstellung unter "Bearbeiten". Warnungen bei belegter oder
# gebuchter Maschine und bei gespeicherten Anmeldedaten eines anderen Kontos
# bleiben.
# 0.9.7: bei Verbindungsziel "Automatisch" startet die Verbindung mit dem
# Ziel, das die Karte anzeigt. Die Karte prüfte die Namensauflösung und
# zeigte am anderen Standort die IP, der Start schrieb aber trotzdem den
# Namen in die .rdp-Datei, und mstsc fand den Computer nicht.
# 0.9.8: ein neu installiertes Portal ohne eigenen Stand beginnt mit dem
# mitgelieferten Startinventar (portal_app/data/start-inventar.json):
# NB13KI, Remote-Ettlingen, PC07, NB12KI und PC12. Übernommen werden nur
# Felder, die eine Maschine beschreiben, nie Anmeldenamen. Ein vorhandener
# Stand und ein gemeinsames Inventar bleiben unberührt.
# 0.9.9: das Portal signiert jede .rdp-Datei mit rdpsign.exe, sobald unter
# HKLM\SOFTWARE\Kirschke\RDPPortal ein Signaturzertifikat eingetragen ist
# (deployment/certificates). Scheitert das Signieren, startet die
# Verbindung unsigniert wie bisher.
# 0.9.12: "Standard wiederherstellen" löscht nichts mehr (0.9.11 entfernte das
# hinterlegte Lesekonto und alle eigenen Fallbacks) und fragt das Admin-Passwort
# im eigenen Dialog ab, mit "Ohne Admin fortfahren" für den Teil ohne Admin.
# 0.9.11: Einstellungen -> "Standard wiederherstellen" setzt ein Portal auf den
# Stand einer Neuinstallation: mit Admin Startinventar statt eigener Maschinenliste
# (mit Sicherung); auch ohne Admin ("Ohne Admin fortfahren") jede Statusfreigabe
# eingerichtet wie im Fallback-Dialog -- Lesekonto, Probelesen, Konto gemerkt. Das
# geschieht auch beim ersten Start. Gelöscht wird nichts. Neue
# Maschinen eines Updates kommen je PC einmal dazu -- der erste Versuch dazu
# fehlte als Modul und mischte bei jedem Neuladen gelöschte Maschinen zurück.
# 0.9.10: rdpsign /sha256 erwartet trotz des Namens den SHA-1-Fingerabdruck.
# 0.9.9 trug den SHA-256-Wert ein, und rdpsign meldete 0x80092004. Ein alter
# SHA-256-Eintrag wird jetzt abgelehnt und im Protokoll gemeldet.
PORTAL_VERSION = "0.9.12"
# 1.4.0: every reported session carries its account SID, so the portal no longer
# has to resolve Entra names against a cache that may not know them.
# 1.6.1 (agent setup): das Setup kann auf Wunsch zusätzlich die beschreibbare
# Freigabe RDP-Protokoll anlegen, in der alle Portale ihr Ereignisprotokoll
# sammeln. Nötig auf genau einer Maschine im Testbetrieb, deshalb standardmäßig
# aus. Bewusst dasselbe Konto PortalLeser wie für den Statusordner -- ein
# zweites brächte ein zweites Kennwort in Umlauf, und das Portal probiert für
# jeden Server ohnehin dasselbe. Schreibrecht bekommt das Konto nur im
# Protokollordner; der Statusordner bleibt lesend.
# 1.6.2 (agent setup): das Fenster misst seinen Inhalt, statt auf 680x635
# festgenagelt zu sein, und die Knopfzeile hängt am Fenster statt im
# Inhaltsraster. Der Kasten für die Protokollfreigabe hatte "Jetzt
# installieren" unter den unteren Rand geschoben, und weil das Fenster
# unveränderbar war, kam man auch durch Aufziehen nicht daran. Jetzt bleiben
# die Knöpfe unten sitzen, egal wie hoch der Inhalt wird -- auch bei einer
# größeren Windows-Schrift oder auf einem kleinen Bildschirm.
# 1.6.3 (agent setup): behebt ein Setup, das nach getaner Arbeit wie eingefroren
# dastand. `log_share_note` wurde erst im Arbeitsthread gesetzt und nur bei
# angekreuzter Protokollfreigabe -- sonst lief die Erfolgsmeldung in einen
# AttributeError mitten im Tk-Callback: kein Dialog, keine Fehlermeldung, nur
# gesperrte Knöpfe. Der Agent war dabei längst eingerichtet und lief.
# Damit so etwas nicht mehr unsichtbar bleibt: Die Statuszeile nennt jetzt den
# laufenden Schritt und dessen Nummer ("Schritt 5/8: Programmdateien kopieren"),
# das Warten auf die erste Statusmeldung zählt sichtbar herunter, und scheitert
# die Anzeige des Ergebnisses trotzdem, sagt das Fenster es und gibt die Knöpfe
# wieder frei, statt stumm stehen zu bleiben.
# 1.6.4 (agent): eine Aufschaltmeldung hängt sich nicht mehr an die nächste
# Sitzung desselben Kontos. Einmal an eine Sitzung gebunden, gilt sie nur noch
# für genau diese -- erkannt an Sitzungsnummer *und* Anmeldezeitpunkt, weil
# Windows Nummern neu vergibt. Vorher übernahm die alte Meldung jede spätere
# Anmeldung unter demselben Konto, und auf einer Maschine, auf der sich alle
# unter einem gemeinsamen Konto anmelden, ist das der Normalfall: Nach dem
# Abmelden stand die Maschine als "belegt durch" eine Person da, die längst weg
# war, und der Nächste sah dasselbe, bevor er überhaupt verbunden hatte.
# 1.6.5 (agent): eine getrennte RDP-Sitzung gilt nicht mehr als Konsolensitzung.
# ``WTSClientProtocolType`` beschreibt den *gerade angehängten* Client, nicht die
# Art der Sitzung: Trennt sich eine RDP-Sitzung, hängt keiner mehr daran und
# Windows meldet 0 -- denselben Wert wie für die Konsole. Damit galt ausgerechnet
# der häufigste Fall als lokale Sitzung, weil die meisten ihr Fenster schließen
# statt sich abzumelden. Sichtbar war das als "Konsole am Gerät" bei jemandem,
# der von einem anderen Standort verbunden war, und als Abmeldung, die mit
# "lokale Konsolensitzung" abgelehnt wurde, obwohl gar keine vorlag.
# Maßgeblich ist jetzt der WinStation-Name (`RDP-Tcp#5` gegen `Console`): Er
# gehört zur Sitzung, das Protokoll nur zur Verbindung. An echten WinStations
# nachgemessen -- die Station `RDP-Tcp` meldet ohne Client ebenfalls 0.
# 1.7.0 (agent): der Graph-/SharePoint-Zweig ist entfernt -- Status-Upload,
# Ereignisversand und Erstabgleich gegen SharePoint-Listen samt Zertifikats-
# und Tenant-Einstellungen. Er war nie eingerichtet; der Agent meldet seinen
# Stand wie bisher über die Statusfreigabe und die Pipe. Alte Einträge wie
# sharepoint_site_id in agent-config.json werden ignoriert.
# 1.7.1 (agent): eine Aufschaltmeldung findet ihre Sitzung in jeder
# Schreibweise des Kontos -- "Rechenknecht" gehört zu "WORKSTATION\Rechenknecht".
# Vorher nur bei wörtlich gleicher, und eine neue Meldung ersetzte die alte nur
# dann; sonst blieb der Vorgänger an der Sitzung stehen.
# 1.7.2 (agent): eine Aufschaltmeldung wird nur an eine Sitzung gebunden, die
# vom meldenden Rechner aus aufgebaut wurde, und verfällt, wenn ein anderer
# Rechner die Sitzung übernimmt. Vorher hängte sich die Meldung einer nie
# zustande gekommenen Verbindung an die Sitzung eines Kollegen unter demselben
# Konto -- die Maschine in München stand als "belegt von Christian Becker".
# 1.7.3 (agent setup): die Statusprüfung am Ende der Einrichtung erkennt den
# eigenen Rechner auch, wenn sein Name länger als 15 Zeichen ist. Der Agent
# meldet den DNS-Namen ("Remote-Ettlingen"), das Setup verglich mit
# %COMPUTERNAME%, dem auf 15 Zeichen gekürzten NetBIOS-Namen
# ("REMOTE-ETTLINGE") -- und lehnte den laufenden Agenten jedes Mal ab. Weil
# die Protokollfreigabe erst danach angelegt wird, fehlte sie dann ebenfalls.
# Scheitert die Prüfung, nennt die Meldung jetzt, was nicht stimmte, und die
# angezeigten Freigabepfade verwenden den DNS-Namen.
AGENT_VERSION = "1.7.3"

__all__ = ["AGENT_VERSION", "PORTAL_VERSION"]
