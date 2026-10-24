# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VHS-Sat Lite (Windows onedir)."""

block_cipher = None

datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("config.example.yaml", "."),
]

hiddenimports = [
    "jinja2", "werkzeug", "flask", "yaml", "sqlite3", "hls",
    "jinja2.ext",
]

excludes = [
    # DVB — must NOT be bundled
    "hardware",
    "hardware.base",
    "hardware.linux_backend",
    "hardware.windows_stub",
    "hardware.tools",
    # Heavyweight stdlib we don't need
    "tkinter", "unittest", "pydoc", "doctest", "lib2to3",
    "pdb", "distutils", "setuptools", "pip",
]

a = Analysis(
    ["server_lite.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VHS-Sat-Lite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon="assets/vhs-sat.ico",     # ← вот этой строки не хватало
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="VHS-Sat-Lite",
)