# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['server_app.py'],
    pathex=[],
    binaries=[('C:\\Users\\a\\Documents\\stream-engine\\screen-broadcast-client\\ffmpeg\\ffmpeg.exe', 'ffmpeg')],
    datas=[],
    hiddenimports=['app', 'manager', 'single_engine', 'relay', 'config', 'flask', 'flask_cors', 'requests', 'dotenv', 'waitress'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StreamEngineServer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StreamEngineServer',
)
