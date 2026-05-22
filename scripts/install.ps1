$ErrorActionPreference = "Stop"

# UTF-8 output so the box-drawing logo renders correctly on Windows hosts.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# Colors — match src/pythinker_code/ui/shell/__init__.py logo palette.
$useColor = $Host.UI.RawUI -ne $null -and -not $env:NO_COLOR
if ($useColor) {
  $NAVY  = "$([char]27)[38;5;24m"
  $FACE  = "$([char]27)[38;5;255m"
  $CORAL = "$([char]27)[38;5;216m"
  $IRIS  = "$([char]27)[38;5;152m"
  $DIM   = "$([char]27)[2m"
  $BOLD  = "$([char]27)[1m"
  $RESET = "$([char]27)[0m"
  $ESC   = "$([char]27)"
} else {
  $NAVY = $FACE = $CORAL = $IRIS = $DIM = $BOLD = $RESET = ""
  $ESC = ""
}

# Static logo. Used as the animation fallback (non-host, NO_COLOR, dumb term,
# CI, or PYTHINKER_NO_ANIMATION=1) and as the source of truth for the final
# settled frame.
function Print-LogoStatic {
  Write-Host ""
  Write-Host "      $CORAL●$RESET"
  Write-Host "      $NAVY│$RESET"
  Write-Host "  $NAVY▛$RESET$FACE▀▀▀▀▀▀▀$RESET$NAVY▜$RESET"
  Write-Host " $CORAL◖$RESET$NAVY█$RESET $IRIS◉$RESET   $IRIS◉$RESET $NAVY█$RESET$CORAL◗$RESET"
  Write-Host "  $NAVY▙▄▄▄$RESET$FACE≡$RESET$NAVY▄▄▄▟$RESET"
  Write-Host ""
  Write-Host "  $BOLD$FACE`pythinker code$RESET $DIM`· your next CLI agent$RESET"
  Write-Host ""
}

# Tetris-style animated logo. 5×13 grid; pieces fall from above the canvas
# one at a time and settle. Order matches install.sh.
function Print-LogoAnimated {
  $ROWS = 5
  $COLS = 13
  $frameDelayMs = 60
  if ($env:PYTHINKER_LOGO_FRAME_DELAY_MS) { $frameDelayMs = [int]$env:PYTHINKER_LOGO_FRAME_DELAY_MS }
  $staggerDelayMs = 40
  if ($env:PYTHINKER_LOGO_STAGGER_DELAY_MS) { $staggerDelayMs = [int]$env:PYTHINKER_LOGO_STAGGER_DELAY_MS }

  $gridChars  = New-Object 'string[]' ($ROWS * $COLS)
  $gridColors = New-Object 'string[]' ($ROWS * $COLS)
  for ($i = 0; $i -lt $gridChars.Length; $i++) { $gridChars[$i] = ' '; $gridColors[$i] = '' }

  $renderFrame = {
    param($pieceR, $pieceC, $cells)
    $tc = [string[]]$gridChars.Clone()
    $tk = [string[]]$gridColors.Clone()
    if ($null -ne $pieceR) {
      foreach ($cell in $cells) {
        $rr = $pieceR + $cell.dr
        $cc = $pieceC + $cell.dc
        if ($rr -ge 0 -and $rr -lt $ROWS -and $cc -ge 0 -and $cc -lt $COLS) {
          $tc[$rr * $COLS + $cc] = $cell.ch
          $tk[$rr * $COLS + $cc] = $cell.color
        }
      }
    }
    $sb = [System.Text.StringBuilder]::new()
    for ($r = 0; $r -lt $ROWS; $r++) {
      for ($c = 0; $c -lt $COLS; $c++) {
        $idx = $r * $COLS + $c
        $col = $tk[$idx]; $ch = $tc[$idx]
        if ($col) { [void]$sb.Append($col).Append($ch).Append($RESET) }
        else      { [void]$sb.Append($ch) }
      }
      [void]$sb.Append("$ESC[K`n")
    }
    [Console]::Write($sb.ToString())
  }

  $dropPiece = {
    param($targetR, $targetC, $cells)
    for ($r = -1; $r -le $targetR; $r++) {
      [Console]::Write("$ESC[$($ROWS)A`r")
      & $renderFrame $r $targetC $cells
      Start-Sleep -Milliseconds $frameDelayMs
    }
    foreach ($cell in $cells) {
      $rr = $targetR + $cell.dr; $cc = $targetC + $cell.dc
      $gridChars[$rr * $COLS + $cc]  = $cell.ch
      $gridColors[$rr * $COLS + $cc] = $cell.color
    }
    if ($staggerDelayMs -gt 0) { Start-Sleep -Milliseconds $staggerDelayMs }
  }

  function _C($dr, $dc, $ch, $color) { [pscustomobject]@{ dr=$dr; dc=$dc; ch=$ch; color=$color } }

  $pieces = @(
    @{ r=2; c=2;  cells=@((_C 0 0 '▛' $NAVY), (_C 1 0 '█' $NAVY), (_C 2 0 '▙' $NAVY)) },
    @{ r=2; c=10; cells=@((_C 0 0 '▜' $NAVY), (_C 1 0 '█' $NAVY), (_C 2 0 '▟' $NAVY)) },
    @{ r=2; c=3;  cells=@((_C 0 0 '▀' $FACE), (_C 0 1 '▀' $FACE), (_C 0 2 '▀' $FACE), (_C 0 3 '▀' $FACE), (_C 0 4 '▀' $FACE), (_C 0 5 '▀' $FACE), (_C 0 6 '▀' $FACE)) },
    @{ r=4; c=3;  cells=@((_C 0 0 '▄' $NAVY), (_C 0 1 '▄' $NAVY), (_C 0 2 '▄' $NAVY), (_C 0 3 '≡' $FACE), (_C 0 4 '▄' $NAVY), (_C 0 5 '▄' $NAVY), (_C 0 6 '▄' $NAVY)) },
    @{ r=3; c=4;  cells=@((_C 0 0 '◉' $IRIS)) },
    @{ r=3; c=8;  cells=@((_C 0 0 '◉' $IRIS)) },
    @{ r=3; c=1;  cells=@((_C 0 0 '◖' $CORAL)) },
    @{ r=3; c=11; cells=@((_C 0 0 '◗' $CORAL)) },
    @{ r=1; c=6;  cells=@((_C 0 0 '│' $NAVY)) },
    @{ r=0; c=6;  cells=@((_C 0 0 '●' $CORAL)) }
  )

  [Console]::Write("$ESC[?25l")
  try {
    for ($i = 0; $i -lt $ROWS; $i++) { [Console]::Write("`n") }
    foreach ($p in $pieces) { & $dropPiece $p.r $p.c $p.cells }
    Write-Host ""
    Write-Host "  $BOLD$FACE`pythinker code$RESET $DIM`· your next CLI agent$RESET"
    Write-Host ""
  } finally {
    [Console]::Write("$ESC[?25h")
  }
}

function Print-Logo {
  $isInteractive = $Host.UI.RawUI -ne $null -and -not [Console]::IsOutputRedirected
  if ($env:PYTHINKER_NO_ANIMATION -or $env:CI -or $env:NO_COLOR `
      -or $env:TERM -eq 'dumb' -or -not $isInteractive) {
    Print-LogoStatic
  } else {
    Print-LogoAnimated
  }
}

function Step($msg) { Write-Host "  $IRIS⠿$RESET $msg" }
function OK($msg)   { Write-Host "  $IRIS✓$RESET $msg" }
function Fail($msg) { Write-Host "  $CORAL✗$RESET $msg" -ForegroundColor Red; exit 1 }

function Spin-Run($label, [scriptblock]$action) {
  Step $label
  $log = New-TemporaryFile
  try {
    & $action *>&1 | Out-File -FilePath $log -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
      Get-Content $log | Write-Host
      Fail $label
    }
  } finally {
    Remove-Item $log -ErrorAction SilentlyContinue
  }
}

# Idempotently append a directory to the User PATH (HKCU\Environment) and
# broadcast WM_SETTINGCHANGE so already-running shells / Explorer pick up the
# change for any future child processes. Returns $true if the registry was
# updated, $false if the directory was already present.
function Add-ToUserPath($Dir) {
  if (-not $Dir) { return $false }
  $current = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (-not $current) { $current = '' }
  $existing = $current.Split(';', [System.StringSplitOptions]::RemoveEmptyEntries) |
              ForEach-Object { $_.TrimEnd('\').ToLowerInvariant() }
  if ($existing -contains $Dir.TrimEnd('\').ToLowerInvariant()) { return $false }

  $newValue = if ($current.TrimEnd(';')) {
    "$($current.TrimEnd(';'));$Dir"
  } else {
    $Dir
  }
  [Environment]::SetEnvironmentVariable('Path', $newValue, 'User')

  # Broadcast WM_SETTINGCHANGE so Explorer and existing shells see the new PATH
  # for newly-spawned child processes. Best-effort: failure is non-fatal.
  try {
    if (-not ('PythinkerNative' -as [type])) {
      Add-Type -Namespace PythinkerNative -Name WinApi -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError=true, CharSet=System.Runtime.InteropServices.CharSet.Auto)]
public static extern System.IntPtr SendMessageTimeout(System.IntPtr hWnd, uint Msg, System.UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out System.UIntPtr lpdwResult);
'@
    }
    $HWND_BROADCAST = [IntPtr]0xffff
    $WM_SETTINGCHANGE = 0x1A
    $SMTO_ABORTIFHUNG = 0x2
    $result = [UIntPtr]::Zero
    [void][PythinkerNative.WinApi]::SendMessageTimeout(
      $HWND_BROADCAST, $WM_SETTINGCHANGE, [UIntPtr]::Zero, 'Environment',
      $SMTO_ABORTIFHUNG, 5000, [ref]$result)
  } catch {}

  return $true
}

function Refresh-Path {
  $MachinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  if (-not $MachinePath) { $MachinePath = '' }
  $UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (-not $UserPath) { $UserPath = '' }

  $ExtraPaths = @(
    Join-Path $env:USERPROFILE ".local\bin"
    Join-Path $env:USERPROFILE ".cargo\bin"
  )

  $env:PATH = (@(
    $MachinePath.TrimEnd(';'),
    $UserPath.TrimEnd(';')
  ) + $ExtraPaths).Where({ $_ }) -join ';'
}

function Install-Uv {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Step "Installing uv with winget"
    $wingetLog = New-TemporaryFile
    try {
      & winget install --id astral-sh.uv -e --accept-package-agreements --accept-source-agreements --silent *>&1 | Out-File -FilePath $wingetLog -Encoding utf8
      Refresh-Path
      if (Get-Command uv -ErrorAction SilentlyContinue) {
        OK "Installing uv with winget"
        return
      }
    } finally {
      Remove-Item $wingetLog -ErrorAction SilentlyContinue
    }
  }

  Step "Fetching uv (Python package installer)"
  $uvInstaller = Join-Path ([System.IO.Path]::GetTempPath()) "uv-install.ps1"
  try {
    Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/install.ps1" -OutFile $uvInstaller
    # Run in the current process (so $env:PATH / registry updates land here) but
    # inside an anonymous scope so Astral's variables and $ErrorActionPreference
    # don't leak into the rest of our script.
    & { . $uvInstaller }
  } finally {
    Remove-Item $uvInstaller -ErrorAction SilentlyContinue
  }
  OK "Fetching uv (Python package installer)"

  Refresh-Path
}

Print-Logo

# ---------------------------------------------------------------------------
# DEPRECATION NOTICE
#
# This uv-based PowerShell installer is now a legacy install path. The
# canonical Windows install is the native PythinkerSetup-x.y.z.exe wizard
# from the GitHub Releases page (no Python/uv prereq, no UAC prompt, real
# uninstall via Apps & Features).
#
# Set PYTHINKER_INSTALL_QUIET_DEPRECATION=1 to suppress this banner.
# ---------------------------------------------------------------------------
if (-not $env:PYTHINKER_INSTALL_QUIET_DEPRECATION) {
  Write-Host ""
  Write-Host "  $BOLD$CORAL[DEPRECATED]$RESET This uv-based installer is now a legacy path."
  Write-Host "  Prefer the native installer:"
  Write-Host "    $IRIS Download:$RESET https://github.com/mohamed-elkholy95/Pythinker-Code/releases/latest"
  Write-Host "    $IRIS Artifact:$RESET PythinkerSetup-x.y.z.exe (per-user, no UAC, signed once cert lands)"
  Write-Host "  Continuing with the legacy uv install in 3s... (Ctrl-C to abort)"
  Write-Host ""
  Start-Sleep -Seconds 3
}

# Make sure ~/.local/bin (uv's tool-shim directory) is permanently on the
# User PATH so the `pythinker` shim is found in any future shell. Idempotent.
$pythinkerToolDir = Join-Path $env:USERPROFILE ".local\bin"
if (Add-ToUserPath $pythinkerToolDir) {
  OK "Added $pythinkerToolDir to your User PATH"
}

if (Get-Command uv -ErrorAction SilentlyContinue) {
  $uvVersion = (& uv --version) -replace '^uv\s+', ''
  OK "uv already installed ($uvVersion)"
} else {
  Install-Uv
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Fail "uv not found after installation. Open a new shell and re-run."
}

Spin-Run "Installing pythinker-code" {
  & uv tool install --quiet --python 3.13 pythinker-code
}

# uv tool install drops shims in $USERPROFILE\.local\bin. Make sure the current
# session can find them even if uv didn't refresh the parent PATH.
Refresh-Path

Write-Host ""
Write-Host "  $BOLD$FACE`pythinker$RESET is ready."
if (Get-Command pythinker -ErrorAction SilentlyContinue) {
  Write-Host "  $DIM`Run$RESET $BOLD$IRIS`pythinker$RESET $DIM`to start.$RESET"
} else {
  $toolBin = Join-Path $env:USERPROFILE ".local\bin"
  Write-Host "  $DIM`pythinker is installed at$RESET $toolBin\pythinker.exe"
  Write-Host "  $DIM`Open a new PowerShell window and run$RESET $BOLD$IRIS`pythinker$RESET$DIM`, or run it by full path now.$RESET"
}
Write-Host ""
