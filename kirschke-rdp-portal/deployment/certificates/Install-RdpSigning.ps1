<#
.SYNOPSIS
    Richtet die Signatur der Portal-.rdp-Dateien auf einem PC ein.

.DESCRIPTION
    Als Administrator auf jedem PC ausfuehren, auf dem das Portal laeuft.

    Mit -PfxPath (Portal-PC):
      1. Signaturzertifikat nach LocalMachine\My, Schluessel nicht exportierbar.
         rdpsign sucht nur im Computerspeicher.
      2. Leserecht auf den Schluessel fuer "Benutzer" (S-1-5-32-545), weil das
         Portal ohne Administratorrechte signiert.
      3. SHA-1-Fingerabdruck nach HKLM\SOFTWARE\Kirschke\RDPPortal
         (SigningThumbprint). Daran erkennt das Portal, dass es signieren soll.
         rdpsign /sha256 erwartet trotz des Namens den SHA-1-Fingerabdruck.
      4. Probe: eine Testdatei signieren.

    Immer:
      5. SHA-1-Fingerabdruck in die Richtlinie TrustedCertThumbprints
         ("SHA1-Fingerabdruecke von Zertifikaten vertrauenswuerdiger
         .rdp-Herausgeber"). Dann fragt Windows bei Dateien dieses Portals
         nicht mehr nach, bei fremden .rdp-Dateien weiterhin. Vorhandene
         Eintraege bleiben erhalten.

    Die Kirschke RDP Root CA muss auf dem PC bereits vertrauenswuerdig sein.

.EXAMPLE
    .\Install-RdpSigning.ps1 -CerPath E:\Kirschke-RDP-Signatur.cer -PfxPath E:\Kirschke-RDP-Signatur.pfx
.EXAMPLE
    .\Install-RdpSigning.ps1 -CerPath E:\Kirschke-RDP-Signatur.cer   # nur Vertrauen
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CerPath,
    [string]$PfxPath
)
$ErrorActionPreference = 'Stop'

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Bitte PowerShell als Administrator starten.'
}

$public = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 (Resolve-Path -LiteralPath $CerPath).Path
if ($public.Subject -notlike '*Kirschke RDP Portal Signatur*' -or $public.Issuer -notlike '*Kirschke RDP Root CA*') {
    throw "Unerwartetes Zertifikat: $($public.Subject), ausgestellt von $($public.Issuer)"
}
$chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
$chain.ChainPolicy.RevocationMode = 'NoCheck'
if (-not $chain.Build($public)) {
    throw 'Die Kirschke RDP Root CA ist auf diesem PC nicht vertrauenswuerdig. Zuerst die Root importieren.'
}
$sha1 = $public.Thumbprint.ToUpperInvariant()
"Signaturzertifikat: $($public.Subject), gueltig bis $($public.NotAfter.ToString('dd.MM.yyyy'))"

if ($PfxPath) {
    $password = Read-Host 'Kennwort von Kirschke-RDP-Signatur.pfx' -AsSecureString
    $imported = Import-PfxCertificate -FilePath $PfxPath -CertStoreLocation Cert:\LocalMachine\My -Password $password
    if ($imported.Thumbprint -ne $public.Thumbprint) {
        Remove-Item -LiteralPath ('Cert:\LocalMachine\My\' + $imported.Thumbprint) -DeleteKey
        throw 'PFX und CER gehoeren nicht zusammen.'
    }
    $certificate = Get-Item -LiteralPath ('Cert:\LocalMachine\My\' + $sha1)
    $rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($certificate)
    $name = if ($rsa -is [System.Security.Cryptography.RSACng]) { $rsa.Key.UniqueName } else { $rsa.CspKeyContainerInfo.UniqueKeyContainerName }
    $keyFile = "$env:ProgramData\Microsoft\Crypto\Keys\$name",
               "$env:ProgramData\Microsoft\Crypto\RSA\MachineKeys\$name" |
               Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $keyFile) { throw "Schluesseldatei nicht gefunden: $name" }
    & icacls.exe $keyFile /grant '*S-1-5-32-545:R' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Leserecht auf den Schluessel nicht gesetzt (icacls $LASTEXITCODE)" }

    $portalKey = 'HKLM:\SOFTWARE\Kirschke\RDPPortal'
    New-Item -Path $portalKey -Force | Out-Null
    New-ItemProperty -Path $portalKey -Name 'SigningThumbprint' -Value $sha1 -PropertyType String -Force | Out-Null
    "Portal signiert ab dem naechsten Start mit $sha1"

    $probe = Join-Path $env:TEMP ("kirschke-signaturprobe-{0}.rdp" -f [guid]::NewGuid().ToString('N'))
    try {
        [IO.File]::WriteAllText($probe, "full address:s:Remote-Ettlingen`r`nscreen mode id:i:1`r`n", [Text.Encoding]::Unicode)
        $rdpsign = Join-Path $env:SystemRoot 'System32\rdpsign.exe'
        # Fehlerausgabe eines nativen Programms ist unter 'Stop' sonst ein Abbruch.
        $ErrorActionPreference = 'Continue'
        $output = & $rdpsign '/sha256' $sha1 '/q' $probe 2>&1
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        $signed = [IO.File]::ReadAllText($probe) -match 'signature:s:'
        if ($exitCode -eq 0 -and $signed) {
            'Probe: Testdatei erfolgreich signiert.'
        } else {
            Write-Warning "Probe fehlgeschlagen (rdpsign $exitCode): $output"
        }
    } finally {
        Remove-Item -LiteralPath $probe -ErrorAction SilentlyContinue
    }
}

$policyKey = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services'
New-Item -Path $policyKey -Force | Out-Null
$existing = (Get-ItemProperty -Path $policyKey -Name 'TrustedCertThumbprints' -ErrorAction SilentlyContinue).TrustedCertThumbprints
$thumbprints = @(@($existing -split '[,;\s]+') | Where-Object { $_ } | ForEach-Object { $_.ToUpperInvariant() })
if ($thumbprints -notcontains $sha1) { $thumbprints += $sha1 }
New-ItemProperty -Path $policyKey -Name 'TrustedCertThumbprints' -Value ($thumbprints -join ',') -PropertyType String -Force | Out-Null
"Vertrauenswuerdiger .rdp-Herausgeber: SHA-1 $sha1"
