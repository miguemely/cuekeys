# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('cuekeys')


a = Analysis(
    ['/Users/miguelr/git/pimoroni-macro-manager/packaging/launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('/Users/miguelr/git/pimoroni-macro-manager/firmware', 'cuekeys/firmware'), ('/Users/miguelr/git/pimoroni-macro-manager/src/cuekeys/devices/builtin', 'cuekeys/devices/builtin'), ('/Users/miguelr/git/pimoroni-macro-manager/LICENSE', '.'), ('/Users/miguelr/git/pimoroni-macro-manager/THIRD_PARTY_NOTICES.md', '.'), ('/Users/miguelr/git/pimoroni-macro-manager/COMMERCIAL-LICENSE.md', '.'), ('/Users/miguelr/git/pimoroni-macro-manager/licenses', 'licenses')],
    hiddenimports=hiddenimports,
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
    name='CueKeys',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    name='CueKeys',
)
app = BUNDLE(
    coll,
    name='CueKeys.app',
    icon=None,
    bundle_identifier='io.github.miguemely.cuekeys',
)
