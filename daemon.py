"""
daemon.py — Background daemon with system tray icon.

Scaffold template for TechnoSage Flask applications.
Copy this file into your project and customise the following:
  • APP_NAME, APP_PORT         — display name and web-UI port
  • ICON_TEXT                  — 2-letter tray icon fallback text
  • ICON_COLOUR                — (R,G,B,A) tray circle colour
  • _run_background_task()     — the work done on each loop cycle
  • check interval             — _task_interval_secs()

Usage
-----
  python daemon.py             — start (tray icon if enabled in settings)
  python daemon.py --once      — run one task cycle and exit
  python daemon.py --no-tray   — force headless mode

Tray menu
---------
  <APP_NAME> Daemon  (disabled label)
  ─────────────────────────────────
  Run Task Now
  Open <APP_NAME>
  ─────────────────────────────────
  Exit

Requires: pystray, Pillow  (auto-installed on first tray launch)
Settings: reads/writes  instance/app_settings.json
PID file: <project_root>/daemon.pid
Log file: <project_root>/logs/daemon.log
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime

# ---------------------------------------------------------------------------
# ── CUSTOMISE THESE ──────────────────────────────────────────────────────────
APP_NAME    = "My App"       # Human-readable app name
APP_PORT    = 5000           # Default Flask port
ICON_TEXT   = "MA"           # 2-letter tray icon fallback
ICON_COLOUR = (0, 102, 204, 255)  # (R, G, B, A) for fallback circle
# ─────────────────────────────────────────────────────────────────────────────

# ---------------------------------------------------------------------------
# sys.path fix for MS Store Python running as a copied .exe
# ---------------------------------------------------------------------------
def _fix_sys_path() -> None:
    _exe_dir    = os.path.dirname(os.path.abspath(sys.executable))
    _local_dlls = os.path.join(_exe_dir, "DLLs")
    if os.path.isdir(_local_dlls) and _local_dlls not in sys.path:
        sys.path.insert(0, _local_dlls)
    if sys.platform == "win32":
        _appdata = os.environ.get("LOCALAPPDATA", "")
        _pkgs    = os.path.join(_appdata, "Packages")
        if os.path.isdir(_pkgs):
            _ver = f"Python{sys.version_info.major}{sys.version_info.minor}"
            for _d in os.listdir(_pkgs):
                if _d.startswith("PythonSoftwareFoundation.Python."):
                    _sp = os.path.join(
                        _pkgs, _d, "LocalCache", "local-packages", _ver, "site-packages"
                    )
                    if os.path.isdir(_sp) and _sp not in sys.path:
                        sys.path.insert(0, _sp)
                    break

_fix_sys_path()

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "daemon.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("daemon")

# ---------------------------------------------------------------------------
# PID / signal files
# ---------------------------------------------------------------------------
PID_FILE    = os.path.join(PROJECT_DIR, "daemon.pid")
ICON_SIGNAL = os.path.join(PROJECT_DIR, "icon_refresh_daemon.signal")

_stop_event = threading.Event()
_tray_icon  = None


def _write_pid() -> None:
    with open(PID_FILE, "w") as fh:
        fh.write(str(os.getpid()))


def _remove_pid() -> None:
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Settings (read directly from JSON)
# ---------------------------------------------------------------------------
SETTINGS_PATH = os.path.join(PROJECT_DIR, "instance", "app_settings.json")


def _read_settings() -> dict:
    try:
        if os.path.isfile(SETTINGS_PATH):
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _get(key: str, default):
    return _read_settings().get(key, default)


# ---------------------------------------------------------------------------
# Background task — CUSTOMISE THIS
# ---------------------------------------------------------------------------

def _run_background_task() -> None:
    """Override this function with the daemon's actual work."""
    logger.info("Running background task…")
    try:
        from app import create_app   # type: ignore
        flask_app = create_app()
        with flask_app.app_context():
            # ── do your work here ──────────────────────────────────────────
            pass
        logger.info("Background task complete.")
    except Exception as exc:
        logger.error("Background task error: %s", exc, exc_info=True)


def _task_interval_secs() -> float:
    """Return seconds between task runs. Read from settings or use a default."""
    hours = float(_get("task_interval_hours", 1))
    return max(60.0, hours * 3600)


def _task_due() -> bool:
    return _last_task is None or (
        datetime.now() - _last_task
    ).total_seconds() >= _task_interval_secs()


_last_task: datetime | None = None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _check_loop() -> None:
    _stop_event.wait(30)   # initial delay after startup
    if not _stop_event.is_set():
        _run_background_task()

    while not _stop_event.is_set():
        interval = _task_interval_secs()
        logger.info("Next task in %.0f min.", interval / 60)
        slept = 0.0
        while slept < interval and not _stop_event.is_set():
            chunk = min(30.0, interval - slept)
            _stop_event.wait(chunk)
            slept += chunk
        if _stop_event.is_set():
            break
        _run_background_task()


# ---------------------------------------------------------------------------
# System tray
# ---------------------------------------------------------------------------

def _ensure_tray_deps() -> bool:
    try:
        import pystray   # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        pass
    logger.info("Installing pystray and Pillow…")
    try:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "pystray", "Pillow"],
            timeout=120,
        )
        return True
    except Exception as exc:
        logger.warning("Could not install tray dependencies: %s", exc)
        return False


def _make_icon_image():
    from PIL import Image  # type: ignore

    for _name in ("Logo_Transparent_Color.ico", "Logo Transparent Color.ico"):
        _logo = os.path.join(PROJECT_DIR, "icons", _name)
        if os.path.isfile(_logo):
            try:
                src = Image.open(_logo)
                return src.convert("RGBA").resize((64, 64), Image.LANCZOS)
            except Exception:
                pass

    from PIL import ImageDraw, ImageFont  # type: ignore
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, size - 2, size - 2], fill=ICON_COLOUR)
    text = ICON_TEXT
    try:
        font = ImageFont.truetype("arialbd.ttf", 26)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 2), text, fill="white", font=font)
    return img


def _icon_refresh_loop() -> None:
    while not _stop_event.is_set():
        _stop_event.wait(3)
        if os.path.exists(ICON_SIGNAL):
            try:
                os.remove(ICON_SIGNAL)
            except OSError:
                pass
            if _tray_icon is not None:
                try:
                    _tray_icon.icon = _make_icon_image()
                except Exception:
                    pass


def run_with_tray() -> None:
    global _tray_icon
    import pystray  # type: ignore

    loop_thread    = threading.Thread(target=_check_loop,        name="task-loop",    daemon=True)
    refresh_thread = threading.Thread(target=_icon_refresh_loop, name="icon-refresh", daemon=True)
    loop_thread.start()
    refresh_thread.start()

    port = int(_get("app_port", APP_PORT))

    def on_run_now(icon, item):  # noqa: ANN001
        threading.Thread(target=_run_background_task, daemon=True).start()

    def on_open(icon, item):  # noqa: ANN001
        threading.Thread(target=_do_open, daemon=True).start()

    def _do_open() -> None:
        import shutil as _shutil
        import socket
        import subprocess as _sp
        import webbrowser

        _url = f"http://127.0.0.1:{port}"

        def _alive() -> bool:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    return True
            except OSError:
                return False

        if not _alive():
            _run_py = os.path.join(PROJECT_DIR, "run.py")
            _python = shutil.which("python") or shutil.which("python3") or sys.executable  # type: ignore
            _flags  = 0
            if sys.platform == "win32":
                _flags = _sp.CREATE_NO_WINDOW | _sp.DETACHED_PROCESS
            if os.path.isfile(_run_py):
                try:
                    _sp.Popen(
                        [_python, _run_py],
                        env={**os.environ},
                        creationflags=_flags,
                        close_fds=True,
                        cwd=PROJECT_DIR,
                    )
                except Exception as exc:
                    logger.error("Failed to start Flask server: %s", exc)
                for _ in range(80):
                    time.sleep(0.1)
                    if _alive():
                        break

        webbrowser.open(_url)

    def on_exit(icon, item):  # noqa: ANN001
        _stop_event.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(f"{APP_NAME} Daemon", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Run Task Now",      on_run_now),
        pystray.MenuItem(f"Open {APP_NAME}",  on_open),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit",              on_exit),
    )

    icon = pystray.Icon(
        f"{APP_NAME.replace(' ', '')}Daemon",
        _make_icon_image(),
        f"{APP_NAME} — background daemon",
        menu,
    )
    _tray_icon = icon
    icon.run()

    _stop_event.set()
    loop_thread.join(timeout=5)
    _remove_pid()
    logger.info("Daemon exited.")


# ---------------------------------------------------------------------------
# Headless daemon
# ---------------------------------------------------------------------------

def run_daemon() -> None:
    logger.info("%s Daemon starting (PID %d).", APP_NAME, os.getpid())
    _write_pid()

    def _handle_stop(sig, frame):  # noqa: ANN001
        _stop_event.set()

    signal.signal(signal.SIGTERM, _handle_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle_stop)

    try:
        _check_loop()
    except KeyboardInterrupt:
        pass
    finally:
        _remove_pid()
        logger.info("Daemon exited.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Background Daemon")
    parser.add_argument("--once",    action="store_true", help="Run one task cycle and exit.")
    parser.add_argument("--no-tray", action="store_true", help="Force headless mode.")
    args = parser.parse_args()

    if args.once:
        _run_background_task()
        return

    _write_pid()

    use_tray = not args.no_tray and bool(_get("show_tray_icon", True))

    if use_tray and _ensure_tray_deps():
        run_with_tray()
        return

    run_daemon()


if __name__ == "__main__":
    main()
