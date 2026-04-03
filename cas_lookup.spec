# PyInstaller spec file for CAS Lookup
# Run:  pyinstaller cas_lookup.spec

import os
import sys
import subprocess

# ── Locate the streamlit package folder ──────────────────────────────────────
result = subprocess.run(
    [sys.executable, "-c", "import streamlit; print(streamlit.__file__)"],
    capture_output=True, text=True
)
streamlit_init = result.stdout.strip()
streamlit_dir  = os.path.dirname(streamlit_init)

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # Bundle app.py alongside the launcher
        ("app.py", "."),
        # Streamlit's web frontend (HTML/JS/CSS)
        (os.path.join(streamlit_dir, "static"),     "streamlit/static"),
        # Streamlit runtime modules (needed for script execution)
        (os.path.join(streamlit_dir, "runtime"),    "streamlit/runtime"),
        # Streamlit component library
        (os.path.join(streamlit_dir, "components"), "streamlit/components"),
    ],
    hiddenimports=[
        # Streamlit core
        "streamlit",
        "streamlit.web",
        "streamlit.web.cli",
        "streamlit.web.server",
        "streamlit.web.server.server",
        "streamlit.web.server.routes",
        "streamlit.web.server.media_file_handler",
        "streamlit.runtime",
        "streamlit.runtime.scriptrunner",
        "streamlit.runtime.scriptrunner.magic_funcs",
        "streamlit.runtime.state",
        "streamlit.runtime.caching",
        "streamlit.runtime.legacy_caching",
        "streamlit.components.v1",
        "streamlit.elements",
        # App dependencies
        "bs4",
        "requests",
        "requests.adapters",
        "urllib3",
        # Streamlit dependencies
        "pandas",
        "numpy",
        "pyarrow",
        "altair",
        "pydeck",
        "tornado",
        "tornado.web",
        "tornado.websocket",
        "tornado.httpserver",
        "tornado.ioloop",
        "click",
        "toml",
        "tomli",
        "validators",
        "rich",
        "pympler",
        "packaging",
        "typing_extensions",
        "attr",
        "attrs",
        "importlib_metadata",
        "zipp",
        "watchdog",
        "watchdog.observers",
        "watchdog.events",
        "gitpython",
        "PIL",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "IPython", "jupyter"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="CAS_Lookup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,        # Keep console open so user sees the network IP
    icon=None,
)
