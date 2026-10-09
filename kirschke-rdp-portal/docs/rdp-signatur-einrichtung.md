# Signierte .rdp-Dateien einrichten

Stand: 09.10.2026 · ab Portal 0.9.9

Ohne Signatur zeigt Windows vor jeder Verbindung „Vorsicht: Unbekannte
Remoteverbindung – Unbekannter Herausgeber“. Neuere Windows-Versionen geben
Zwischenablage, Laufwerke und Drucker dann erst frei, wenn jemand die Häkchen
setzt. Mit der Signatur steht dort der Herausgeber *Kirschke RDP Portal
Signatur*, und mit dessen Fingerabdruck in der Vertrauensrichtlinie entfällt
der Dialog für Dateien des Portals ganz. Eine fremde `.rdp`-Datei, etwa aus
einem Mailanhang, löst die Warnung weiterhin aus.

Hintergrund und Abwägungen: [rdp-signatur-plan.md](rdp-signatur-plan.md).

## Voraussetzungen

- Die **Kirschke RDP Root CA** ist auf allen Portal-PCs als vertrauenswürdige
  Stammzertifizierungsstelle importiert, von Hand oder per Intune.
- Die **Root-Sicherung** `Kirschke-RDP-Root-CA.pfx` vom USB-Stick samt Kennwort.
- Die Skripte aus dem Paketordner `Zertifikate\`.

## 1. Signaturzertifikat ausstellen (einmal, auf Remote-Ettlingen)

PowerShell **als Administrator**:

```powershell
powershell -ExecutionPolicy Bypass -File .\New-RdpSigningCert.ps1 -RootPfx E:\Kirschke-RDP-Root-CA.pfx
```

Das Skript fragt nach dem Kennwort der Root-Sicherung und nach einem **neuen**
Kennwort für das Signaturzertifikat. Die Root wird danach wieder samt Schlüssel
vom Rechner entfernt. Ergebnis in `C:\RdpCA`:

| Datei | Inhalt | Umgang |
|---|---|---|
| `Kirschke-RDP-Signatur.pfx` | Zertifikat **mit** Schlüssel | nur per USB auf die Portal-PCs, danach löschen; nie auf eine Freigabe |
| `Kirschke-RDP-Signatur.cer` | öffentlicher Teil | darf überall liegen |

Gültig ist das Zertifikat zwei Jahre (`-Years` ändert das, höchstens 5).

## 2. Auf jedem Portal-PC einrichten

PowerShell **als Administrator**, beide Dateien zum Beispiel vom USB-Stick:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-RdpSigning.ps1 -CerPath E:\Kirschke-RDP-Signatur.cer -PfxPath E:\Kirschke-RDP-Signatur.pfx
```

Das Skript

1. legt das Zertifikat in den Computerspeicher (`LocalMachine\My`), den
   Schlüssel nicht exportierbar,
2. gibt der Gruppe *Benutzer* Leserecht auf den Schlüssel, weil das Portal
   ohne Administratorrechte signiert,
3. trägt den SHA-1-Fingerabdruck (`Thumbprint`) unter
   `HKLM\SOFTWARE\Kirschke\RDPPortal\SigningThumbprint` ein,
4. signiert eine Testdatei und meldet **„Probe: Testdatei erfolgreich
   signiert.“**,
5. trägt den SHA-1-Fingerabdruck in die Richtlinie *„SHA1-Fingerabdrücke von
   Zertifikaten vertrauenswürdiger .rdp-Herausgeber“* ein
   (`TrustedCertThumbprints`). Vorhandene Einträge bleiben erhalten.

Ein PC, der nur die Vertrauensrichtlinie braucht, bekommt das Skript ohne
`-PfxPath`.

**Wer das Skript aus Portal 0.9.9 benutzt hat:** Es trug den SHA-256-Wert ein,
und die Probe scheiterte mit `0x80092004`. `rdpsign /sha256` erwartet trotz des
Namens den SHA-1-Fingerabdruck. Das Skript aus 0.9.10 einfach mit denselben
Dateien erneut ausführen; es überschreibt den Eintrag.

## 3. Prüfen

1. Portal neu starten.
2. In den Maschinendetails zeigt **RDP-Diagnose** „RDP-Signatur: eingerichtet“.
3. **Verbinden**: Es erscheint kein Herausgeber-Dialog mehr. Kommt er doch,
   muss dort *Kirschke RDP Portal Signatur* statt *Unbekannter Herausgeber*
   stehen – dann fehlt nur die Richtlinie aus Schritt 5.
4. Scheitert das Signieren, startet das Portal die Verbindung trotzdem
   unsigniert und schreibt „RDP-Datei nicht signiert …“ mit dem Grund in
   `%LOCALAPPDATA%\KirschkeRDPPortal\logs\portal.log`.

**Manipulationsprobe (einmal):** Eine signierte Datei mit dem Editor öffnen, bei
`full address` einen anderen Rechner eintragen, speichern und doppelklicken.
Die Warnung muss zurückkommen – das zeigt, dass die Signatur tatsächlich prüft.
Die Datei liegt kurz nach dem Start unter `%TEMP%\rdp_*.rdp`.

## Erneuerung

Vor Ablauf Schritt 1 und 2 wiederholen. Das Portal liest den neuen
Fingerabdruck beim nächsten Start; die Richtlinie enthält danach alten und
neuen SHA-1-Wert. Den alten kann man aus `TrustedCertThumbprints` entfernen und
das alte Zertifikat aus `LocalMachine\My` löschen.

## Später per Intune

Der Eintrag aus Schritt 5 ist eine normale Richtlinie und lässt sich über den
Intune-Einstellungskatalog verteilen; dort nach „vertrauenswürdiger
.rdp-Herausgeber“ suchen. Das Zertifikat mit Schlüssel (Schritte 1–3) bleibt Handarbeit je
Portal-PC.

## Restrisiko

Der Schlüssel liegt auf jedem Portal-PC, und jeder angemeldete Benutzer dort kann
damit signieren. Wer das Zertifikat missbraucht, kann `.rdp`-Dateien erzeugen,
denen alle Portal-PCs vertrauen. Begrenzt wird das durch den nicht
exportierbaren Schlüssel, das Vertrauen über genau einen Fingerabdruck und die
Laufzeit von zwei Jahren. Bei Verdacht: Fingerabdruck aus
`TrustedCertThumbprints` entfernen und neu ausstellen.
