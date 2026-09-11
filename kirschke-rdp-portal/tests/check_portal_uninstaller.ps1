param([string]$Project, [string]$TestRoot)
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $Project 'deployment\install_portal.ps1'), [ref]$tokens, [ref]$errors)
if ($errors) { throw $errors }
foreach ($definition in $ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]}, $false)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
$installDirectory = Join-Path $TestRoot 'Programs\KirschkeRDPPortal'
$registry = Join-Path $TestRoot 'fake-registry-entry'
$shortcut = Join-Path $TestRoot 'fake-shortcut.lnk'
$data = Join-Path $TestRoot 'portal-state.json'
New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Set-Content -LiteralPath (Join-Path $installDirectory 'Kirschke-RDP-Portal.exe') -Value 'test payload'
Set-Content -LiteralPath $shortcut -Value 'test shortcut'
Set-Content -LiteralPath $data -Value '{}'
Remove-Portal
if ((Test-Path -LiteralPath $installDirectory) -or (Test-Path -LiteralPath $shortcut)) { throw 'Uninstall incomplete' }
if (-not (Test-Path -LiteralPath $data)) { throw 'Inventory deleted' }
