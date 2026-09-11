param([string]$Project, [string]$TestRoot)
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$source = [IO.File]::ReadAllText((Join-Path $Project 'deployment\setup_status_share.ps1'), [Text.Encoding]::UTF8)
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
if ($errors) { throw $errors }
foreach ($definition in $ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]}, $false)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
function Get-LocalUser { param($Name,$ErrorAction) if ($script:Existing) { return 'existing' } }
function Get-SmbShare { param($Name,$ErrorAction) }
function New-LocalUser {
    param($Name,$Password,$Description)
    $script:UserCreated = $true
    return [pscustomobject]@{ SID=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-111-222-333-1001') }
}
function Set-Acl { param($LiteralPath,$AclObject) $script:Acl = $AclObject }
function New-SmbShare {
    param($Name,$Path,$ReadAccess,$FullAccess,$CachingMode,$FolderEnumerationMode)
    if ($script:FailShare) { throw 'simulated share failure' }
    $script:ReadAccess=$ReadAccess
}
function Remove-LocalUser { param($SID) $script:UserRemoved=$true }
function Remove-SmbShare { param($Name,[switch]$Force) }
$script:Existing=$false; $script:FailShare=$false
$password = ConvertTo-SecureString 'test-only-secret' -AsPlainText -Force
$directory = Join-Path $TestRoot 'agenten-status'
$account = Initialize-StatusShare -Directory $directory -Name 'RDP-Status' -Reader 'PortalLeser' -Password $password
if ($account -ne "$env:COMPUTERNAME\PortalLeser" -or $script:ReadAccess -ne $account) { throw 'Wrong share reader' }
$rules = @($script:Acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]))
if ($rules.Count -ne 3 -or -not $script:Acl.AreAccessRulesProtected) { throw 'Unexpected ACL scope' }
$readerRule = $rules | Where-Object { $_.IdentityReference.Value -eq 'S-1-5-21-111-222-333-1001' }
if ($readerRule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::Write) { throw 'Reader can write' }
if (-not ($readerRule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::Read)) { throw 'Reader cannot read' }
$script:Existing=$true; $script:UserCreated=$false
try {
    Initialize-StatusShare -Directory (Join-Path $TestRoot 'other') -Name 'Other' -Reader 'PortalLeser' -Password $password
    throw 'Expected existing user rejection'
} catch { if ($script:UserCreated) { throw 'Existing user modified' } }
$script:Existing=$false; $script:FailShare=$true; $script:UserRemoved=$false
$failedDirectory = Join-Path $TestRoot 'failed'
try {
    Initialize-StatusShare -Directory $failedDirectory -Name 'Fail' -Reader 'NewReader' -Password $password
} catch { }
if (-not $script:UserRemoved -or (Test-Path -LiteralPath $failedDirectory)) { throw 'Rollback incomplete' }
if (-not (Test-Path -LiteralPath $directory)) { throw 'Existing status directory removed' }
$password.Dispose()
Write-Output 'Reader ACL, share identity, existing-account protection and failure rollback verified.'
