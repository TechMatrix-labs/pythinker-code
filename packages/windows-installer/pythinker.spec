# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Pythinker Code Windows native build.
# Mode: --onedir (faster startup, fewer AV false-positives than --onefile).

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hiddenimports = []
for pkg in (
    "pythinker_code",
    "pythinker_core",
    "fastmcp",
    "mcp",
    "typer",
    "aiohttp",
    "anyio",
    "rich",
):
    try:
        hiddenimports.extend(collect_submodules(pkg))
    except Exception:
        pass

a = Analysis(
    ["entrypoint.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("../.pythinker-native", "."),
    ],
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
