# Pythinker Native Windows Installer — Design

**Status:** Approved (2026-05-22)
**Owner:** mohamed-elkholy95
**Tracking:** Brings parity with Claude Code's native installer for the Windows distribution surface.

---

## 1. Goal

Ship a downloadable `PythinkerSetup-x.y.z.exe` that installs `pythinker` on Windows
with no prerequisites on the user's machine — no Python, no Node, no uv, no shell
script. One double-click → `pythinker` is on PATH and works in a fresh PowerShell.

The existing PyPI/uv install path (`pip install pythinker-code`, `scripts/install.ps1`)
stays available for developers; the native installer is **additive**, not a
replacement.

## 2. Non-goals

- Per-machine (HKLM) install as default. Available as an opt-in via `/ALLUSERS`,
  but the default is per-user, no UAC.
- MSI / WiX authoring. Inno Setup is sufficient and lower-overhead.
- Microsoft Store (MSIX) packaging. Possible later; out of scope here.
- macOS/Linux native installers. The existing PyPI + Homebrew (future) routes
  cover those platforms.

## 3. User-visible behavior

- Download `PythinkerSetup-x.y.z.exe` from the GitHub Releases page.
- Run it. Wizard appears (logo banner, Apache-2.0 EULA, optional
  "Add Pythinker to PATH" task pre-checked, optional "Launch pythinker after
  install" task).
- No UAC prompt. Files land in `%LOCALAPPDATA%\Programs\Pythinker`. PATH entry
  is added to `HKCU\Environment`. `WM_SETTINGCHANGE` is broadcast so already-open
  Explorer windows pick the new PATH up for newly-spawned child shells.
- Start Menu entry: *Pythinker → pythinker*. Uninstall entry in Apps & Features.
- A fresh PowerShell window can run `pythinker` immediately. Existing sessions
  pick it up once they're restarted.

Updates: `pythinker update` from a native build downloads the latest
`PythinkerSetup-*.exe` from the configured channel and runs it
`/VERYSILENT /SUPPRESSMSGBOXES`. Same UX as Claude Code's native auto-update.

## 4. Architecture

```
GitHub tag push (pythinker-code-vX.Y.Z)
        │
        ▼
.github/workflows/windows-installer.yml  (runs-on: windows-latest)
        │
        ├── pyinstaller pythinker.spec              → dist/pythinker/  (onedir)
        ├── signtool sign dist/pythinker/*.exe      (if cert secret present)
        ├── iscc installer.iss                      → dist/PythinkerSetup-X.Y.Z.exe
        ├── signtool sign  dist/PythinkerSetup-*.exe
        └── gh release upload                       (asset attached to the tag)

End user                                       Pythinker runtime
        │                                              │
        ▼                                              ▼
PythinkerSetup-X.Y.Z.exe                  `pythinker update` detects native build
        │                                              │
        ▼                                              ▼
%LOCALAPPDATA%\Programs\Pythinker\        GET releases JSON → download new setup
  pythinker.exe + DLLs                    → exec /VERYSILENT /UPDATEONLY
  .pythinker-native (sentinel)
```

## 5. Components

### 5.1 Repository layout

```
packages/
  windows-installer/
    build.ps1                 # local + CI orchestrator
    pythinker.spec            # PyInstaller spec (onedir)
    installer.iss             # Inno Setup script
    versioninfo.txt            # PyInstaller --version-file (Company, FileVersion, ProductName)
    assets/
      pythinker.ico           # 16/32/48/256 icon from docs/media/logo.png
      LICENSE.rtf             # Apache-2.0 in RTF for the EULA page
      pythinker-banner.bmp    # 164×314 wizard banner (optional but recommended)
      pythinker-header.bmp    # 150×57  wizard small image (optional)
    sign/
      sign.ps1                # signtool wrapper, no-op if cert env vars unset
    README.md                 # how to build locally

src/pythinker_code/cli/update.py          # extended to handle native-installer path
src/pythinker_code/_native.py             # tiny helper: is_native_build(), installer_url()

.github/workflows/windows-installer.yml   # tag-triggered build + sign + release upload

docs/superpowers/specs/
  2026-05-22-windows-native-installer-design.md   # this file
```

### 5.2 PyInstaller spec (`pythinker.spec`)

- Mode: `--onedir` (NOT `--onefile`). Rationale:
  - Onefile extracts to `%TEMP%` on every launch → 0.3–1.5 s startup penalty.
  - Onefile is the dominant cause of Defender/SmartScreen false positives
    (PyInstaller issue #6754 and many duplicates).
  - The wizard hides the `dist/pythinker/` folder under `%LOCALAPPDATA%`; the
    user sees only the Start Menu shortcut and the `pythinker` PATH entry.
- Entry point: a thin `cli/__main__.py` that imports `pythinker_code.cli.main`
  and calls `main()`.
- `hiddenimports`: enumerate every plugin / subagent module pythinker loads at
  runtime via importlib (`pythinker_code.subagents.*`, `pythinker_code.tools.*`,
  fastmcp / mcp transitive packages that PyInstaller can't trace).
- `--version-file versioninfo.txt` so the resulting `pythinker.exe` carries
  proper Windows version metadata (`CompanyName=Pythinker`,
  `ProductName=Pythinker Code`, `FileVersion=X.Y.Z.0`, `OriginalFilename=pythinker.exe`).
- Includes runtime hook that drops a marker file `.pythinker-native` next to
  `pythinker.exe` at install time.

### 5.3 Inno Setup script (`installer.iss`)

Key directives:

```
[Setup]
AppId={{4F4F2EAE-9D55-4E8E-92BC-7C1FA38B6F02}}    ; stable GUID across versions; regenerated once in advance
AppName=Pythinker Code
AppVersion={#AppVersion}
AppPublisher=Pythinker
AppPublisherURL=https://pythinker.com
DefaultDirName={localappdata}\Programs\Pythinker
DefaultGroupName=Pythinker
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=PythinkerSetup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardImageFile=assets\pythinker-banner.bmp
WizardSmallImageFile=assets\pythinker-header.bmp
SetupIconFile=assets\pythinker.ico
UninstallDisplayIcon={app}\pythinker.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=assets\LICENSE.rtf
; SignTool directive only used in CI builds where signtool is configured
; SignTool=signtool $f

[Files]
Source: "..\..\dist\pythinker\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "modifypath"; Description: "Add Pythinker to your PATH"; GroupDescription: "Shell integration:";

[Registry]
; Append {app} to HKCU\Environment\Path (idempotent — see [Code] InitializeWizard)
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; \
  Tasks: modifypath; \
  Check: NeedsAddPath('{app}')

[Icons]
Name: "{group}\Pythinker"; Filename: "{app}\pythinker.exe"

[Run]
Filename: "{app}\pythinker.exe"; Description: "Launch Pythinker"; \
  Flags: nowait postinstall skipifsilent unchecked

[Code]
function NeedsAddPath(Param: string): boolean;
var OrigPath: string;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', OrigPath) then begin
    Result := True; exit;
  end;
  Result := Pos(';' + UpperCase(Param) + ';',
                ';' + UpperCase(OrigPath) + ';') = 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Path: string;
begin
  if CurUninstallStep = usUninstall then begin
    if RegQueryStringValue(HKCU, 'Environment', 'Path', Path) then begin
      StringChangeEx(Path, ';' + ExpandConstant('{app}'), '', True);
      StringChangeEx(Path, ExpandConstant('{app}') + ';', '', True);
      StringChangeEx(Path, ExpandConstant('{app}'), '', True);
      RegWriteStringValue(HKCU, 'Environment', 'Path', Path);
    end;
  end;
end;
```

After both install and uninstall PATH edits, the installer broadcasts
`WM_SETTINGCHANGE` via Inno Setup's standard `Environment` parameter so newly
spawned shells see the change without a reboot. (Inno's `expandsz` write +
`Environment` value name triggers this for free.)

### 5.4 Build pipeline (`.github/workflows/windows-installer.yml`)

```
on:
  push:
    tags: [pythinker-code-v*]
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest
    permissions: { contents: write }
    steps:
      - checkout
      - setup-python 3.13
      - install uv; uv sync; uv pip install pyinstaller
      - pyinstaller packages/windows-installer/pythinker.spec
      - powershell packages/windows-installer/sign/sign.ps1 dist/pythinker/pythinker.exe
      - install Inno Setup 6 via choco
      - iscc /DAppVersion=${{ github.ref_name }} packages/windows-installer/installer.iss
      - powershell packages/windows-installer/sign/sign.ps1 dist/PythinkerSetup-*.exe
      - powershell -c "Get-FileHash dist\PythinkerSetup-*.exe -Algorithm SHA256 > dist\PythinkerSetup-*.exe.sha256"
      - gh release upload ${{ github.ref_name }} dist/PythinkerSetup-*.exe dist/PythinkerSetup-*.exe.sha256
```

`sign.ps1` reads `WINDOWS_CERT_PFX_BASE64` + `WINDOWS_CERT_PASSWORD` from the
environment. If unset, it logs a warning and exits 0 (unsigned build proceeds).
If set, it decodes the PFX into a temp file, calls

```
signtool sign /f $pfx /p $pw \
  /tr http://timestamp.digicert.com /td sha256 /fd sha256 \
  $target
```

then deletes the temp PFX. The cert never lands on disk in the repo, and never
appears in logs.

### 5.5 Update plumbing (`src/pythinker_code/cli/update.py`)

```
def update(channel: str = "latest") -> None:
    if not _is_native_build():
        return _update_via_uv()       # existing path, unchanged

    if os.environ.get("DISABLE_AUTOUPDATER"):
        log.info("Auto-update disabled via DISABLE_AUTOUPDATER; skipping")
        return

    rel = _gh_releases_lookup(channel)        # GET api.github.com/.../releases/{tag}
    if not _is_newer(rel.tag, __version__):
        log.info("Pythinker is up to date (%s)", __version__)
        return

    installer = _download(rel.installer_asset_url)
    if not _verify_sha256(installer, rel.sha256):
        raise UpdateError("installer checksum mismatch — aborting")

    log.info("Launching native installer (silent)…")
    subprocess.Popen([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES"])
    sys.exit(0)
```

`_is_native_build()` checks for `(Path(sys.executable).parent / ".pythinker-native").exists()`.
This file is dropped by `installer.iss` via:

```
[Files]
Source: "..\windows-installer\.pythinker-native"; DestDir: "{app}"
```

A file marker is the cheapest, most reliable signal — no env var, no registry
key, survives copy-installs.

### 5.6 Distribution surfaces

1. **GitHub Releases** — primary: `PythinkerSetup-x.y.z.exe` + `.sha256` attached to every `pythinker-code-v*` tag.
2. **README** — add a *Windows (native)* section above the current PyPI/uv block:
   - Direct download link to the latest Release asset.
   - One-line PowerShell installer (downloads + runs setup silently) for users who prefer the terminal:
     `irm https://pythinker.com/install/win | iex`  *(or the raw GitHub URL until DNS is configured)*
3. **Winget manifest** — auto-publish via `winget-releaser` GitHub Action triggered after a Release publishes. Defer to a follow-up PR; not blocking v1.

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Pre-cert window** — first releases ship unsigned, SmartScreen will warn. | `sign.ps1` is a no-op without the secret, so CI keeps producing installers; README documents the warning and how to verify SHA-256. Switching on signing is a single GitHub Secret addition, no code change. |
| **AV false positives** on PyInstaller-frozen binaries. | Onedir mode + Authenticode signing eliminates the majority. For the first 1-2 weeks we proactively submit the signed `.exe` to Microsoft Defender via the [false-positive portal](https://www.microsoft.com/wdsi/filesubmission) and run a pre-release VirusTotal scan. |
| **Installer size** — unknown until first freeze; could be 60-120 MB with all of fastmcp/mcp/pythinker-core transitive deps. | Track size in CI as a workflow artifact summary; if it exceeds 150 MB, audit `excludes` in `pythinker.spec` (PyInstaller's `--exclude-module` for unused optional deps). Acceptable target: ≤100 MB compressed installer. |
| **PATH conflict** — a user with both `uv tool install pythinker-code` *and* the native install will have two `pythinker.exe`s on PATH. | Installer's Finished page checks `where.exe pythinker` and shows a notice if more than one is found, suggesting `uv tool uninstall pythinker-code`. |
| **Stale releases JSON during update** — GitHub rate-limit (60 req/hr unanon) or transient 5xx. | `_gh_releases_lookup` retries with backoff once, then surfaces a clear error and points to the manual download URL. No silent failures. |
| **Per-machine vs per-user collision** — admin re-installs as ALLUSERS over an existing per-user install (or vice versa). | `[Code]` `InitializeSetup` probes both `HKCU` and `HKLM` Uninstall keys for our `AppId`; if it finds the other scope, refuses with a friendly "uninstall the existing one first" message. |
| **Frozen-binary update detection on dev installs** — `sys.frozen` is also True for PyInstaller dev builds someone may run locally. | The `.pythinker-native` sentinel is dropped only by the production installer, never by `pyinstaller` directly. Dev frozen builds fall through to the PyPI update path, which is correct. |

## 7. Acceptance criteria

A release is considered done when:

1. CI on a `pythinker-code-vX.Y.Z` tag push produces `PythinkerSetup-X.Y.Z.exe`
   attached to the GitHub Release, ≤150 MB.
2. On a fresh Windows 11 VM (no Python, no Node, no uv):
   - Double-clicking the `.exe` completes the wizard with **no UAC prompt**.
   - A new `pwsh` window shows `pythinker --version` matching the tag.
   - `pythinker` launches into the TUI and reaches the prompt without error.
3. `pythinker update` from inside the installed build successfully detects a
   newer pre-release, downloads, verifies SHA-256, and re-launches the installer
   silently. Post-update, `pythinker --version` reflects the new version.
4. Uninstall via Apps & Features removes `{app}` and the PATH entry; a new
   shell no longer finds `pythinker`.
5. Once the signing cert is in place, `signtool verify /pa /v
   PythinkerSetup-X.Y.Z.exe` reports a valid Authenticode chain and a valid RFC
   3161 timestamp.

## 8. Out of scope (deferred)

- Winget manifest automation (follow-up PR; manifest can be auto-generated by
  `winget-releaser` once the Release exists).
- Microsoft Store / MSIX packaging.
- Per-machine install as the default (admin-only enterprise scenarios).
- Localized installer strings beyond English.
- Auto-update channels beyond `latest` / `stable` (no `beta` / `nightly` yet).
- ARM64 Windows native build (PyInstaller support is workable but adds CI complexity; defer until there's demand).

## 9. Open questions

None blocking v1. The user has confirmed:
- Per-user install (no admin) is the default.
- In-app `pythinker update` channel backed by GitHub Releases.
- Code signing is required; cert acquisition is in flight and the build
  pipeline will accept it via GitHub Secret when ready.
- PyInstaller-onedir over onefile (research-driven: startup speed + AV false
  positives).
