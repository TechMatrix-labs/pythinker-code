# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Pythinker Code Linux native packages (.deb / .rpm
# / tarball). Mode: --onedir — fpm wraps the directory into the package and
# install-native.sh tar-gzips it for the curl-bash flow.

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
    # runtime (settings.cfg, stoplists/). Unlike the tarball build
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
    # tool descriptions, etc. as package data. Without explicit
    # collect_data_files() PyInstaller misses them and the frozen binary
    # crashes the first time it tries to load init.md / coder.yaml / etc.
    try:
        datas.extend(collect_data_files(pkg, include_py_files=False))
    except Exception:
        pass

a = Analysis(
    ["entrypoint.py"],
    pathex=[],
    binaries=[],
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
