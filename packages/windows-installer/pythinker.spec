# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Pythinker Code Windows native build.
# Mode: --onedir (faster startup, fewer AV false-positives than --onefile).

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hiddenimports = []
datas = []
for pkg in (
    "pythinker_code",
    "pythinker_core",
    "fastmcp",
    "mcp",
    "typer",
    "aiohttp",
    "anyio",
    "rich",
    # trafilatura and its justext fallback read bundled data by path at
    # runtime (settings.cfg, stoplists/). Unlike the macOS/tarball build
    # (pythinker.spec, which imports the shared datas list), this installer
    # spec collects data per-package, so these must be listed explicitly or
    # the native web Fetch tool crashes on the first extraction.
    "trafilatura",
    "justext",
):
    try:
        hiddenimports.extend(collect_submodules(pkg))
    except Exception:
        pass
    # pythinker_code ships *.md prompts, *.yaml agent specs, SKILL.md,
    # tool descriptions, etc. as package data. Without collect_data_files()
    # PyInstaller silently omits them and the frozen binary crashes the
    # first time it tries to read init.md / coder.yaml / etc.
    try:
        datas.extend(collect_data_files(pkg, include_py_files=False))
    except Exception:
        pass

a = Analysis(
    ["entrypoint.py"],
    pathex=[],
    binaries=[],
    # NOTE: .pythinker-native is NOT bundled here on purpose. PyInstaller
    # >=6.1 places PyInstaller datas under dist/pythinker/_internal/, which
    # would hide the sentinel from is_native_build() (which probes alongside
    # pythinker.exe). installer.iss copies the sentinel directly to {app}.
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pythinker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/pythinker.ico",
    version="versioninfo.generated.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="pythinker",
)
