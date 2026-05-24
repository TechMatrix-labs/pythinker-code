# Pythinker Code — native Windows installer bootstrap.
#
# Downloads the latest PythinkerSetup-x.y.z.exe from GitHub Releases, verifies
# its SHA-256 file, and runs the per-user Inno Setup installer silently.
#
# Usage:
#   irm https://pythinker.com/install.ps1 | iex
#
# To pin a version when running the hosted script, set:
#   $env:PYTHINKER_VERSION = "0.14.0"; irm https://pythinker.com/install.ps1 | iex

$ErrorActionPreference = "Stop"

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$Repo = "mohamed-elkholy95/Pythinker-Code"
$Version = $env:PYTHINKER_VERSION
$NoColor = $env:NO_COLOR

$useColor = $Host.UI.RawUI -ne $null -and -not $NoColor
if ($useColor) {
  $IRIS  = "$([char]27)[38;5;152m"
  $CORAL = "$([char]27)[38;5;216m"
  $DIM   = "$([char]27)[2m"
  $BOLD  = "$([char]27)[1m"
  $RESET = "$([char]27)[0m"
} else {
  $IRIS = $CORAL = $DIM = $BOLD = $RESET = ""
}

function Step($msg) { Write-Host "  $IRIS⠿$RESET $msg" }
function OK($msg)   { Write-Host "  $IRIS✓$RESET $msg" }
function Fail($msg) { Write-Host "  $CORAL✗$RESET $msg" -ForegroundColor Red; exit 1 }

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
  Fail "This installer is for Windows. Use: curl -fsSL https://pythinker.com/install.sh | bash"
}

function Get-LatestVersion {
  Step "Looking up latest Pythinker release"
  $api = "https://api.github.com/repos/$Repo/releases/latest"
  try {
    $release = Invoke-RestMethod -UseBasicParsing -Uri $api
  } catch {
    Fail "could not fetch latest release from $api"
  }

  $tag = [string]$release.tag_name
  if (-not $tag) { Fail "latest release response did not include tag_name" }
  $latest = $tag.TrimStart('v')
  OK "Latest version is $latest"
  return $latest
}

function Read-ExpectedHash($Path) {
  $text = Get-Content -Raw -Path $Path
  $match = [regex]::Match($text, '(?i)[a-f0-9]{64}')
  if (-not $match.Success) { Fail "could not parse SHA-256 from $Path" }
  return $match.Value.ToLowerInvariant()
}

if (-not $Version) { $Version = Get-LatestVersion }
$Version = $Version.TrimStart('v')

$asset = "PythinkerSetup-$Version.exe"
$baseUrl = "https://github.com/$Repo/releases/download/v$Version"
$installerUrl = "$baseUrl/$asset"
$shaUrl = "$installerUrl.sha256"

$tempRoot = [System.IO.Path]::GetTempPath()
$tempDir = Join-Path $tempRoot ("pythinker-install-" + [System.Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempDir | Out-Null
$installerPath = Join-Path $tempDir $asset
$shaPath = "$installerPath.sha256"

try {
  Step "Downloading $asset"
  Invoke-WebRequest -UseBasicParsing -Uri $installerUrl -OutFile $installerPath
  Invoke-WebRequest -UseBasicParsing -Uri $shaUrl -OutFile $shaPath

  Step "Verifying SHA-256"
  $expected = Read-ExpectedHash $shaPath
  $actual = (Get-FileHash -Algorithm SHA256 -Path $installerPath).Hash.ToLowerInvariant()
  if ($expected -ne $actual) {
    Fail "SHA-256 mismatch: expected $expected, got $actual"
  }
  OK "Checksum OK"

  Step "Running Pythinker installer"
  $args = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER')
  $process = Start-Process -FilePath $installerPath -ArgumentList $args -Wait -PassThru
  if ($process.ExitCode -ne 0) {
    Fail "installer exited with code $($process.ExitCode)"
  }
  OK "Installed Pythinker $Version"

  $installDir = Join-Path $env:LOCALAPPDATA "Programs\Pythinker"
  if (Test-Path (Join-Path $installDir "pythinker.exe")) {
    if (($env:PATH -split ';') -notcontains $installDir) {
      $env:PATH = "$installDir;$env:PATH"
    }
  }

  Write-Host ""
  Write-Host "  $BOLD$IRIS`pythinker$RESET is ready. Open a fresh PowerShell and run $BOLD$IRIS`pythinker$RESET to start."
  Write-Host ""
} finally {
  Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
}
