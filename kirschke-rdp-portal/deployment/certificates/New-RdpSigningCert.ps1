<#
.SYNOPSIS
    Stellt das Signaturzertifikat fuer die .rdp-Dateien des Portals aus.

.DESCRIPTION
    Laeuft als Administrator auf dem Rechner mit der Kirschke RDP Root CA
    (Remote-Ettlingen). Die Root wird aus der PFX-Sicherung (USB) importiert,
    signiert das neue Zertifikat und wird danach in jedem Fall wieder samt
    Schluessel aus dem Speicher entfernt.

    Ergebnis im Ausgabeordner:
      Kirschke-RDP-Signatur.pfx  Zertifikat MIT Schluessel, kennwortgeschuetzt.
                                 Nur fuer Install-RdpSigning.ps1 auf den
                                 Portal-PCs. Nie auf eine Freigabe legen.
      Kirschke-RDP-Signatur.cer  oeffentlicher Teil, fuer die Vertrauensrichtlinie.

    Verwendungszwecke: Serverauthentifizierung und Codesignatur. Beide erlaubt
    die Root; welchen rdpsign/mstsc verlangen, ist nicht eindeutig dokumentiert.

.EXAMPLE
    .\New-RdpSigningCert.ps1 -RootPfx E:\Kirschke-RDP-Root-CA.pfx
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RootPfx,
    [string]$OutputDirectory = 'C:\RdpCA',
    [ValidateRange(1, 5)][int]$Years = 2
)
$ErrorActionPreference = 'Stop'

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Bitte PowerShell als Administrator starten.'
}
if (-not (Test-Path -LiteralPath $RootPfx -PathType Leaf)) { throw "Root-Sicherung nicht gefunden: $RootPfx" }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$rootPassword = Read-Host 'Kennwort der Root-CA-Sicherung' -AsSecureString
$root = Import-PfxCertificate -FilePath $RootPfx -CertStoreLocation Cert:\LocalMachine\My -Password $rootPassword
try {
    if ($root.Subject -notlike '*Kirschke RDP Root CA*') { throw "Unerwartete Root: $($root.Subject)" }
    $signing = New-SelfSignedCertificate `
        -Subject 'CN=Kirschke RDP Portal Signatur, O=Kirschke' `
        -Signer $root `
        -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
        -KeyUsage DigitalSignature `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddYears($Years) `
        -CertStoreLocation Cert:\LocalMachine\My `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.1,1.3.6.1.5.5.7.3.3')
} finally {
    Remove-Item -LiteralPath ('Cert:\LocalMachine\My\' + $root.Thumbprint) -DeleteKey
}

try {
    $pfx = Join-Path $OutputDirectory 'Kirschke-RDP-Signatur.pfx'
    $cer = Join-Path $OutputDirectory 'Kirschke-RDP-Signatur.cer'
    $pfxPassword = Read-Host 'Neues Kennwort fuer Kirschke-RDP-Signatur.pfx' -AsSecureString
    Export-PfxCertificate -Cert $signing -FilePath $pfx -Password $pfxPassword | Out-Null
    Export-Certificate -Cert $signing -FilePath $cer | Out-Null
} finally {
    # Remote-Ettlingen signiert selbst nichts; eingerichtet wird je Portal-PC.
    Remove-Item -LiteralPath ('Cert:\LocalMachine\My\' + $signing.Thumbprint) -DeleteKey
}

$sha256 = [BitConverter]::ToString($signing.GetCertHash('SHA256')).Replace('-', '')
''
"Signaturzertifikat:  $($signing.Subject)"
"Gueltig bis:         $($signing.NotAfter.ToString('dd.MM.yyyy'))"
"SHA-1  (Richtlinie): $($signing.Thumbprint)"
"SHA-256 (rdpsign):   $sha256"
''
"Mit Schluessel:  $pfx"
"Oeffentlich:     $cer"
'Die PFX wie die Root-Sicherung behandeln: nur per USB verteilen, danach loeschen.'
