import os
import sys

block_cipher = None

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, 'web')

a = Analysis(
    ['main.py'],
    pathex=[HERE],
    binaries=[],
    datas=[
        (WEB_DIR, 'web'),
        (os.path.join(WEB_DIR, 'templates'), 'web/templates'),
        ('config', 'config'),
    ],
    hiddenimports=[
        'engine',
        'matching',
        'db',
        'api',
        'tencent_mail',
        'fitz',
        'openpyxl',
        'imaplib',
        'email',
        'email.parser',
        'email.policy',
        'email.utils',
        'sqlite3',
        'tempfile',
        'zipfile',
        'base64',
        'json',
        'csv',
        're',
        'uuid',
        'datetime',
        'threading',
        'signal',
        'socket',
        'time',
        'io',
        'urllib.parse',
        'http.server',
        'webview',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='票归集',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='票归集.app',
        icon=None,
        bundle_identifier=None,
    )