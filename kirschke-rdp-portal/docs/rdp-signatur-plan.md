# Plan: Signierte .rdp-Dateien (Option 3) mit Ausblick auf eine eigene CA (Option 5)

Stand: 2026-09-15 · Portal 0.3.10 · betrifft den Verbindungsstart, nicht den Agenten

## Warum und wann

Beim Start einer Verbindung zeigt Windows „Vorsicht: Unbekannte Remoteverbindung –
Der Herausgeber dieser Remoteverbindung konnte nicht überprüft werden". Diese Warnung
gilt **nicht** dem Zielrechner, sondern der `.rdp`-Datei, die das Portal in
`portal_app/rdp/generator.py` erzeugt und unsigniert an `mstsc.exe` übergibt. Für
Windows ist jede unsignierte `.rdp`-Datei von unbekanntem Herausgeber.

Dieser Plan beschreibt, wie das Portal seine eigenen Dateien signiert und die
Arbeitsplätze genau dieser einen Signatur vertrauen. Alle anderen `.rdp`-Dateien —
etwa aus einem Mailanhang — lösen die Warnung weiterhin aus. Das ist der Unterschied
zu der Richtlinie `AllowUnsignedFiles`, die die Warnung pauschal abschaltet und
deshalb hier ausdrücklich nicht verwendet wird.

### Zeitpunkt: nach dem Alpha-Test

Die Umsetzung berührt den Startpfad **jeder** Verbindung. Ein Fehler dort verhindert
nicht eine Warnung, sondern den Verbindungsaufbau selbst. Solche Änderungen gehören
nicht in dieselbe Phase wie das erste Nutzerfeedback, in der ohnehin unklar ist,
woher ein Fehler kommt.

Für den Alpha-Test gilt deshalb: **nichts ändern**. Stattdessen ein Absatz in der
Testanleitung, der die Warnung erklärt und sagt, dass „Verbinden" an dieser Stelle
richtig ist. Der Hinweis ist auch für sich genommen nützlich, weil er die Tester
davon abhält, den Dialog für einen Fehler zu halten und ihn zu melden.

## Ziel und Abgrenzung

**Erreicht wird:** Die Herausgeberwarnung entfällt für Dateien des Portals. Als
Nebeneffekt ist die Datei zwischen Erzeugung und Start gegen Manipulation geschützt,
weil die Signatur über ihren Inhalt läuft.

**Nicht erreicht wird:** Die zweite, davon unabhängige Warnung „Die Identität des
Remotecomputers kann nicht überprüft werden". Die betrifft das Serverzertifikat des
Zielrechners und ist heute über den Schalter `trust_unverified_server` je Maschine
abgefangen. Dafür ist Option 5 zuständig, siehe Ausblick.

## Entscheidung vorab: Woher kommt der Schlüssel

| | Variante A – selbstsigniert | Variante B – von einer CA ausgestellt |
|---|---|---|
| Erzeugung | vollständig auf einem Windows-PC | Schlüsselpaar auf Windows, Signatur durch die CA |
| Vertrauen auf den Clients | Zertifikat muss einzeln verteilt werden | CA muss einmalig bekannt sein, dann gilt sie für alles |
| Aufwand | gering | zusätzlich eine CA im Betrieb |
| Umstieg später | möglich, siehe unten | — |

**Empfehlung: Variante A beginnen.** Der Umstieg auf B ist später kein Bruch: Man
erzeugt auf demselben Windows-PC einen **CSR** (*Certificate Signing Request* — eine
Anfragedatei, die den öffentlichen Schlüssel und den Wunschnamen enthält, aber nicht
den privaten Schlüssel), lässt ihn von der CA signieren und importiert das Ergebnis.
Der private Schlüssel verlässt den Rechner dabei nie, und im Portal ändert sich nur
ein Fingerabdruck in der Konfiguration.

## Arbeitspakete

### AP1 – Signaturzertifikat erzeugen

Neues Skript `deployment/certificates/New-RdpSigningCert.ps1` (der Ordner existiert,
ist aber leer). Es legt das Zertifikat an und gibt beide benötigten Fingerabdrücke aus:

```powershell
$cert = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject "CN=Kirschke RDP Portal Signatur" `
    -CertStoreLocation Cert:\LocalMachine\My `
    -KeyExportPolicy NonExportable `
    -NotAfter (Get-Date).AddYears(5)

$cert.Thumbprint                                                        # SHA-1
[BitConverter]::ToString($cert.GetCertHash('SHA256')).Replace('-','')   # SHA-256
```

`-KeyExportPolicy NonExportable` heißt: Windows gibt den privaten Schlüssel nicht
mehr als Datei heraus. Damit signieren geht, ihn mitnehmen nicht.

**Zwei Fingerabdrücke, ein Zertifikat.** `rdpsign.exe` erwartet den **SHA-256**-Wert,
um das Zertifikat im Speicher zu finden; die Vertrauensrichtlinie auf den Clients
arbeitet mit dem **SHA-1**-Wert. Das ist keine Inkonsistenz im Plan, sondern zwei
verschiedene Prüfsummen desselben Zertifikats — im Labor aber ausdrücklich zu
bestätigen, siehe offene Punkte.

*Fertig, wenn:* Das Skript läuft zweimal hintereinander ohne Dublette, gibt beide
Fingerabdrücke aus und dokumentiert, in welchen Speicher es geschrieben hat.

### AP2 – Signierschritt im Portal

Neues Modul `portal_app/rdp/signing.py` mit einer Klasse `RDPSigner`, aufgerufen in
`RDPSessionLauncher._launch_mstsc` (`portal_app/rdp/launcher.py:95`) zwischen
`generator.generate()` und `subprocess.Popen`.

```
rdpsign.exe /sha256 <SHA-256-Fingerabdruck> /q <datei.rdp>
```

Festlegungen:

- **`rdpsign.exe` wird wie `mstsc.exe` gesucht** — über `SystemRoot`, mit derselben
  Fallback-Kette wie `_find_mstsc`. Kein fester Pfad.
- **Aufruf mit `subprocess.run` und Timeout** (5 s). Signieren ist ein lokaler
  Dateivorgang; hängt es länger, stimmt etwas nicht und die Verbindung soll trotzdem
  starten.
- **Kein Fingerabdruck konfiguriert → stillschweigend überspringen.** Damit laufen
  Entwicklungsrechner und der Alpha-Stand unverändert weiter, ohne Sonderfall im Code.
- **Signieren schlägt fehl → protokollieren und trotzdem starten.** Die Signatur ist
  Komfort, kein Schutzmechanismus, auf den das Portal angewiesen ist. Der Benutzer
  sieht dann wieder die Warnung und kann arbeiten. Ein abgebrochener Start wäre der
  schlechtere Ausgang.
- **Nach dem Signieren wird die Datei nicht mehr verändert.** Das ist heute schon so
  — sie wird einmal geschrieben und dann übergeben — muss aber so bleiben, sonst
  bricht die Signatur. Ein Kommentar im Generator hält das fest.

`rdpsign` trägt selbst zwei Zeilen in die Datei ein: `signscope` (welche
Einstellungen die Signatur abdeckt) und `signature`.

*Fertig, wenn:* Eine erzeugte Datei enthält beide Zeilen, und ein Start ohne
konfigurierten Fingerabdruck verhält sich exakt wie heute.

### AP3 – Fingerabdruck konfigurierbar machen

Der Fingerabdruck gehört **nicht** in den Quelltext — er unterscheidet sich zwischen
Entwicklung, Alpha und Produktivbetrieb und ändert sich bei jeder Erneuerung.

Ablage: `HKLM\SOFTWARE\Kirschke\RDPPortal\SigningThumbprint`, geschrieben vom
Installer, gelesen vom Portal. `HKLM` (*HKEY_LOCAL_MACHINE*) statt `HKCU`, weil die
Einstellung zum Rechner gehört und nicht zum angemeldeten Benutzer.

*Fertig, wenn:* Fingerabdruck ändern wirkt sich ohne neues Portal-Paket aus.

### AP4 – Vertrauen auf den Arbeitsplätzen einrichten

Neues Skript `deployment/certificates/Install-RdpSigningTrust.ps1`, das drei Dinge tut:

1. Den **öffentlichen** Teil des Zertifikats (`.cer`, ohne privaten Schlüssel) nach
   `Cert:\LocalMachine\TrustedPublisher` importieren.
2. Weil selbstsigniert, zusätzlich nach `Cert:\LocalMachine\Root`
   (*Vertrauenswürdige Stammzertifizierungsstellen*). Bei Variante B entfällt das,
   wenn die CA dort schon bekannt ist.
3. Den SHA-1-Fingerabdruck eintragen unter
   `HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services\TrustedCertThumbprints`.
   Das ist die Richtlinie *„SHA1-Fingerabdrücke von Zertifikaten vertrauenswürdiger
   .rdp-Herausgeber angeben"*. **Das ist der entscheidende Schritt** — hier steht
   genau ein Fingerabdruck, und nur ihm wird vertraut.

Für den Regelbetrieb gehören Schritte 1–3 in eine Gruppenrichtlinie (**GPO**,
*Group Policy Object* — die zentrale Einstellungsverteilung einer AD-Domäne) oder in
ein Intune-Profil. Das Skript bleibt trotzdem sinnvoll: für die Laborprüfung und für
Rechner außerhalb der Domäne. Der bestehende Pfad `deployment/intune/` nimmt die
Cloud-Variante auf.

*Fertig, wenn:* Auf einem frisch aufgesetzten Testrechner erscheint nach Ausführung
des Skripts beim Start einer Portalverbindung keine Warnung mehr, bei einer fremden
`.rdp`-Datei dagegen weiterhin.

### AP5 – Tests

**Automatisiert**, `tests/test_rdp_signing.py`, im Stil der vorhandenen Tests mit
ersetztem `subprocess`:

- Fingerabdruck konfiguriert → `rdpsign` wird mit dem richtigen Aufruf gestartet
- kein Fingerabdruck → kein Aufruf, Start unverändert
- `rdpsign` liefert Fehlercode → `mstsc` wird trotzdem gestartet, Protokolleintrag da
- `rdpsign` fehlt / Timeout → dasselbe

**Manuell**, im Labor:

- Signierte Datei starten: keine Warnung, und im Dialogfall steht der Herausgebername
- **Manipulationsprobe:** In einer signierten Datei `full address` auf einen anderen
  Rechner ändern und starten. Die Warnung muss zurückkommen — das ist der Nachweis,
  dass die Signatur tatsächlich prüft und nicht nur vorhanden ist.
- Zertifikat aus dem Speicher entfernen: Verbindung funktioniert weiter, mit Warnung

### AP6 – Dokumentation und Paket

`docs/`-Abschnitt zur Ersteinrichtung und zur Erneuerung, dazu die beiden Skripte in
das Auslieferungspaket aufnehmen. Wie alles andere geht das in
`Kirschke-RDP-Testbetrieb.zip`, nicht als lose Dateien.

## Offene Punkte, vor AP2 zu klären

Diese vier Punkte sind im Labor in überschaubarer Zeit zu beantworten, und ihre
Antworten bestimmen Details der Umsetzung:

1. **Aus welchem Speicher liest `rdpsign`?** `LocalMachine\My` oder `CurrentUser\My`?
   Davon hängt ab, wohin der Installer das Zertifikat legt und ob jeder Benutzer eine
   eigene Kopie braucht. — *Wichtigster Punkt, entscheidet über AP1 und AP4.*
2. **Zeichenkodierung.** Der Generator schreibt die Datei als UTF-8
   (`generator.py:64`), `.rdp`-Dateien sind herkömmlich UTF-16LE. `mstsc` nimmt
   beides; ob `rdpsign` das auch tut, ist zu prüfen.
3. **SHA-1 oder SHA-256 in `TrustedCertThumbprints`?** Der Richtlinienname sagt SHA-1,
   `rdpsign` kennt nur noch SHA-256. Erwartung: zwei Prüfsummen desselben Zertifikats
   für zwei verschiedene Zwecke. Bestätigen, bevor es in ein Skript geschrieben wird.
4. **Bleibt die Warnung wirklich vollständig aus**, obwohl die Datei Zwischenablage
   und weitere Umleitungen anfordert? Erwartung ja, weil die Umleitungsabfrage Teil
   desselben Dialogs ist.

## Bekanntes Restrisiko

Zum Signieren muss der private Schlüssel auf **jedem** Rechner liegen, auf dem das
Portal läuft. Wer dort lokaler Administrator ist, kann damit beliebige `.rdp`-Dateien
erzeugen, denen alle Arbeitsplätze vertrauen.

Bei verwalteten Firmenrechnern in dieser Größenordnung ist das vertretbar, und der
Zustand ist immer noch besser als heute. Abgemildert wird es durch den nicht
exportierbaren Schlüssel, durch das Vertrauen über genau einen Fingerabdruck statt
über einen ganzen Herausgeberzweig, und durch eine begrenzte Laufzeit.

Wer das ausschließen will, müsste die Dateien zentral auf einer Verwaltungsmaschine
vorsignieren. Das passt nicht zu einem Portal, das Verbindungen je Benutzer
zusammenstellt, und ist deshalb hier nicht vorgesehen.

---

# Ausblick: eigene CA (Option 5), auch auf einem Linux-Server

## Kurzantwort

Ja. Eine **CA** (*Certificate Authority*, Zertifizierungsstelle) muss kein Windows
sein. Ein Zertifikat ist ein standardisiertes Format (**X.509**), und Windows fragt
beim Prüfen nicht danach, auf welchem Betriebssystem es ausgestellt wurde. Beide
Zertifikate, die hier vorkommen, kann ein Linux-Server ausstellen:

- das **Signaturzertifikat** aus Option 3 (Verwendungszweck *Codesignatur*)
- die **Serverzertifikate** der Arbeitsplätze, die Warnung B beseitigen
  (Verwendungszweck *Serverauthentifizierung*, ausgestellt auf den vollständigen
  Rechnernamen)

## Was auf Linux läuft

| Software | Charakter | Passt, wenn |
|---|---|---|
| **step-ca** (Smallstep) | schlank, modern, gut dokumentiert, Automatisierung eingebaut | nur Zertifikate ausgestellt werden sollen |
| **FreeIPA** | vollständiger Verzeichnisdienst mit integrierter CA (Dogtag) | ein AD-Gegenstück auf Linux gewünscht ist |
| **HashiCorp Vault** (PKI) | CA als Teil einer Geheimnisverwaltung | Vault ohnehin im Haus ist |
| **EJBCA** | Unternehmens-PKI, sehr mächtig, sehr schwergewichtig | formale Anforderungen es verlangen |
| **XCA** / OpenSSL | Werkzeugkasten, manuell | wenige Zertifikate, selten |

Für den hier beschriebenen Zweck wäre **step-ca** die naheliegende Wahl: ein Dienst,
überschaubare Konfiguration, und die Erneuerung lässt sich automatisieren — der Punkt,
an dem selbstgebaute PKIs sonst scheitern.

## Was ein Linux-Server nicht mitbringt

Das ist der ehrliche Teil. Ausstellen kann Linux alles; was fehlt, ist die
**Windows-Automatik** drumherum:

- **Kein Autoenrollment.** Bei **AD CS** (*Active Directory Certificate Services*,
  Microsofts CA-Rolle) holt sich jeder Domänenrechner sein Serverzertifikat selbst ab
  und erneuert es selbst. Mit einer Linux-CA baut man diesen Ablauf nach — per
  Skript, ACME-Client oder Verwaltungswerkzeug.
- **Keine Zertifikatvorlagen per Gruppenrichtlinie.** Die Richtlinie
  *„Serverauthentifizierungszertifikat-Vorlage"*, mit der man den Arbeitsplätzen
  zentral sagt, welche Vorlage sie für RDP nehmen sollen, greift nur bei AD CS.
- **Das Zuordnen am Zielrechner ist Handarbeit.** Auch mit passendem Zertifikat muss
  dem RDP-Dienst gesagt werden, welches er benutzen soll. Das geschieht über
  `Win32_TSGeneralSetting.SSLCertificateSHA1Hash` — ein Wert, den man je Rechner
  setzen muss. Bei zwei Dutzend Arbeitsplätzen ein Skript, kein Drama, aber eben
  Arbeit, die AD CS abnimmt.
- **Sperrlisten und Erneuerung** bleiben in jedem Fall Betrieb: Was passiert, wenn ein
  Schlüssel kompromittiert ist, und wer merkt, dass in vier Jahren etwas abläuft.

Die Verteilung des Stammzertifikats an die Clients ist übrigens in **beiden** Fällen
gleich viel Aufwand — sie läuft über GPO oder Intune, nicht über die CA.

## Wie sich das zu Option 3 verhält

Die beiden Wege widersprechen sich nicht, sie bauen aufeinander auf:

1. **Jetzt:** Option 3 mit selbstsigniertem Zertifikat. Löst die Warnung aus dem
   Screenshot, kostet keine Infrastruktur.
2. **Wenn eine CA steht:** Das Signaturzertifikat per CSR neu ausstellen lassen. Im
   Portal ändert sich ein Fingerabdruck, sonst nichts.
3. **Danach:** Serverzertifikate für die Arbeitsplätze. Erst damit fällt Warnung B
   weg, und zwar richtig — die Identität des Zielrechners wird dann tatsächlich
   geprüft, statt die Prüfung über `trust_unverified_server` abzuschwächen. Der
   Schalter und die zugehörige Bestätigungsmaske können danach entfallen.

Schritt 3 ist der eigentliche Gewinn einer CA, und er ist auch das einzige, was gegen
einen **MitM** (*Man-in-the-Middle* — jemand hängt sich unbemerkt zwischen Client und
Ziel) wirklich schützt. Schritt 1 und 2 beseitigen nur einen Dialog.

## Empfehlung zur Reihenfolge

Eine CA lohnt sich nicht für das Signaturzertifikat allein — dafür ist Option 3
selbstsigniert vollkommen ausreichend. Sie lohnt sich, sobald die Serverzertifikate
dazukommen sollen oder ohnehin andere interne Dienste Zertifikate brauchen.

Die Frage ist also nicht „Windows-CA oder Linux-CA", sondern: **Wollen wir Warnung B
lösen und den Ausnahmeschalter loswerden?** Wenn ja, ist ein vorhandener Linux-Server
mit step-ca ein vernünftiger Weg, der weniger kostet als ein zusätzlicher
Windows-Server — man zahlt mit etwas mehr Eigenbau bei der Verteilung.
