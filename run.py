"""
run.py — Entry point for Story Teller
  • Hides the console window on Windows
  • Opens the browser after startup
  • Shuts down when all browser tabs are closed (heartbeat watchdog)

Usage:
    python run.py

BD_HEADLESS=1 suppresses the browser tab (used during automated testing).
"""
import os
import sys
import threading
import time

# ── Suppress the console window on Windows ────────────────────────────────────
if sys.platform == "win32":
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)   # SW_HIDE = 0
    except Exception:
        pass

from app import create_app

HOST = "127.0.0.1"
PORT = 5000
URL  = f"http://{HOST}:{PORT}"

flask_app = create_app()


def _open_browser():
    time.sleep(1.2)
    import webbrowser
    webbrowser.open(URL)


def _heartbeat_watchdog():
    """Daemon thread: exit the process when every open browser tab has closed."""
    ever = getattr(flask_app, "_ever_had_tab", None)
    tabs = getattr(flask_app, "_tabs",         None)
    lock = getattr(flask_app, "_tabs_lock",    None)
    if ever is None or tabs is None:
        return
    # Wait until at least one tab has connected
    while not ever[0]:
        time.sleep(2)
    while True:
        time.sleep(10)
        now = time.monotonic()
        with lock:
            timeout = getattr(flask_app, "_beat_timeout", 120.0)
            stale = [tid for tid, t in list(tabs.items()) if now - t > timeout]
            for tid in stale:
                tabs.pop(tid, None)
            alive = bool(tabs)
        if not alive:
            os._exit(0)


if __name__ == "__main__":
    _headless = os.environ.get("BD_HEADLESS", "0").strip() not in ("", "0", "false", "no")
    if not _headless:
        threading.Thread(target=_open_browser, daemon=True).start()
    threading.Thread(target=_heartbeat_watchdog, daemon=True).start()
    flask_app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
