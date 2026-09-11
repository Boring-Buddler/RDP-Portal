param([Parameter(Mandatory)][string]$Project, [Parameter(Mandatory)][string]$TestRoot)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $Project 'deployment\install_agent.ps1'), [ref]$tokens, [ref]$errors)
if ($errors) { throw $errors }
foreach ($definition in $ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]}, $false)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:InstallDirectory = Join-Path $TestRoot 'KirschkeRDPAgent'
$script:DataDirectory = Join-Path $TestRoot 'data'
$script:ConfigPath = Join-Path $script:DataDirectory 'agent-config.json'
$script:TestRoot = (Resolve-Path -LiteralPath $TestRoot).Path
$source = Join-Path $TestRoot 'source'
$status = Join-Path $TestRoot 'status'
New-Item -ItemType Directory -Path $source -Force | Out-Null
Set-Content -LiteralPath (Join-Path $source 'Kirschke-RDP-Agent.exe') -Value 'test payload'
# No real tasks, processes, ACLs or registry writes are made by this test.
function Get-CimInstance { param($ClassName, $Filter) return @() }
function Get-ScheduledTask { param($TaskName, $ErrorAction) return @() }
function Stop-ScheduledTask { param($TaskName, $ErrorAction) }
function Unregister-ScheduledTask { param($TaskName, $Confirm) }
function icacls.exe { $global:LASTEXITCODE = 0 }
function New-ScheduledTaskAction { param($Execute, $Argument) @{Execute=$Execute; Argument=$Argument} }
function New-ScheduledTaskTrigger { param([switch]$AtStartup) if (-not $AtStartup) { throw 'Expected startup trigger' }; 'startup' }
function New-ScheduledTaskPrincipal { param($UserId,$LogonType,$RunLevel) if ($UserId -ne 'SYSTEM' -or $LogonType -ne 'ServiceAccount' -or $RunLevel -ne 'Highest') { throw 'Wrong machine principal' }; 'system' }
function New-ScheduledTaskSettingsSet { param($ExecutionTimeLimit,$MultipleInstances,$RestartCount,$RestartInterval,[switch]$StartWhenAvailable,[switch]$AllowStartIfOnBatteries,[switch]$DontStopIfGoingOnBatteries) @{Limit=$ExecutionTimeLimit} }
function Register-ScheduledTask { param($TaskName,$Action,$Trigger,$Principal,$Settings,$Description,[switch]$Force) $script:Registered = $TaskName }
function New-ItemProperty { param($Path,$Name,$Value,[switch]$Force) if (-not $Path.StartsWith('HKLM:')) { throw 'Unexpected property path' } }
function New-Item {
    param($Path,$ItemType,[switch]$Force)
    if ($Path.StartsWith('HKLM:')) { return }
    Microsoft.PowerShell.Management\New-Item -Path $Path -ItemType $ItemType -Force:$Force
}
function Remove-Item {
    param($LiteralPath,[switch]$Recurse,[switch]$Force,$ErrorAction)
    if ($LiteralPath.StartsWith('HKLM:')) { return }
    if (-not ([IO.Path]::GetFullPath($LiteralPath)).StartsWith($script:TestRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Deletion outside test root' }
    Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath -Recurse:$Recurse -Force:$Force
}
Install-Agent -SelectedWorkstationId 'NB05' -SelectedStatusDirectory $status -SelectedSourceDirectory $source -SelectedPollInterval 15 -LaunchNow $false | Out-Null
if ($script:Registered -ne 'Kirschke RDP Agent - Machine') { throw 'No machine task registered' }
$config = Get-Content -LiteralPath $script:ConfigPath -Raw | ConvertFrom-Json
if ($config.workstation_id -ne 'NB05' -or $config.status_directory -ne $status) { throw 'Wrong saved config' }
Set-Content -LiteralPath (Join-Path $script:InstallDirectory 'obsolete.dll') -Value 'old file'
Install-Agent -SelectedWorkstationId 'NB05' -SelectedStatusDirectory $status -SelectedSourceDirectory $source -SelectedPollInterval 15 -LaunchNow $false | Out-Null
if (Test-Path -LiteralPath (Join-Path $script:InstallDirectory 'obsolete.dll')) { throw 'Old software not removed' }
Set-Content -LiteralPath (Join-Path $status 'preserve.json') -Value '{}'
Uninstall-Agent | Out-Null
if ((Test-Path -LiteralPath $script:InstallDirectory) -or (Test-Path -LiteralPath $script:ConfigPath)) { throw 'Uninstall incomplete' }
if (-not (Test-Path -LiteralPath (Join-Path $status 'preserve.json'))) { throw 'Shared data deleted' }
Write-Output 'Machine principal, upgrade cleanup, uninstall and shared-data preservation verified.'
