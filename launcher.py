"""
CAS Lookup - Standalone launcher for PyInstaller exe.
Starts a local Streamlit server and opens the browser automatically.
Also binds to 0.0.0.0 so you can access from your phone on the same WiFi.
"""
import os
import sys
import threading
import time
import webbrowser
import socket


def get_local_ip():
    """Get the local network IP so the user can connect from their phone."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def open_browser(port):
    """Open browser after a short delay to let the server start."""
    time.sleep(4)
    webbrowser.open(f"http://localhost:{port}")


def get_app_path():
    """Return path to app.py whether running frozen (exe) or as a plain script."""
    if getattr(sys, "frozen", False):
        # Running inside a PyInstaller bundle
        return os.path.join(sys._MEIPASS, "app.py")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")


if __name__ == "__main__":
    PORT = 8501
    local_ip = get_local_ip()

    print("=" * 50)
    print("  CAS Lookup - Starting...")
    print("=" * 50)
    print(f"  Local:   http://localhost:{PORT}")
    print(f"  Network: http://{local_ip}:{PORT}  (use this on your phone)")
    print("=" * 50)
    print("  Close this window to stop the app.")
    print()

    # Open browser automatically
    threading.Thread(target=open_browser, args=(PORT,), daemon=True).start()

    app_path = get_app_path()

    sys.argv = [
        "streamlit", "run", app_path,
        f"--server.port={PORT}",
        "--server.address=0.0.0.0",   # allows phone access on same WiFi
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--server.enableCORS=false",
        "--server.enableXsrfProtection=false",
    ]

    from streamlit.web import cli as stcli
    sys.exit(stcli.main())
