# Build with PyInstaller in the existing overlay-venv.
from pathlib import Path

assets = Path(SPECPATH)
a = Analysis(
    [str(assets / 'airoot_overlay.py')],
    pathex=[], binaries=[],
    datas=[(str(assets / 'airoot-spritesheet.png'), '.'),
           (str(assets / 'airoot-logo.png'), '.'),
           (str(assets / 'airoot-icon.ico'), '.')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False, optimize=0,
)
# Preserve the Windows Qt workaround: PATH's ICU 78 conflicts with Qt.
a.binaries = [entry for entry in a.binaries
              if entry[0].lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='AirootVoiceOverlay', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, upx_exclude=[], runtime_tmpdir=None,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon=[str(assets / 'airoot-icon.ico')],
)
