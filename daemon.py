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
APP_NAME    = "Story Teller"
APP_PORT    = 5005
ICON_TEXT   = "ST"
ICON_COLOUR = (108, 92, 231, 255)   # purple
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

_stop_event = threading.Event()   # signals the work loop to stop
_user_quit  = threading.Event()   # set ONLY on intentional exit (tray Exit / SIGTERM)
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
# Restart logic — up to _MAX_RESTARTS automatic restarts before giving up
# ---------------------------------------------------------------------------
_MAX_RESTARTS    = 5
_RESTART_BACKOFF = [5, 15, 30, 60, 120]   # seconds to wait before each attempt


def _restart_self(reason: str, restart_count: int) -> None:
    """Spawn a replacement daemon process, tracking how many times we've done this.

    Tries sys.executable first, then sys._base_executable, then real .exe files
    found next to sys.executable — handles MS Store Python stubs that
    CreateProcess cannot spawn directly (WinError 2).

    If restart_count >= _MAX_RESTARTS the daemon stops permanently and logs the
    failure. The caller should call os._exit() after this returns.
    """
    if restart_count >= _MAX_RESTARTS:
        logger.error(
            "RESTART LIMIT REACHED (%d/%d) — reason: %s"
            " — daemon will not restart automatically.",
            restart_count, _MAX_RESTARTS, reason,
        )
        return

    attempt  = restart_count + 1
    wait     = _RESTART_BACKOFF[min(restart_count, len(_RESTART_BACKOFF) - 1)]
    logger.warning(
        "DAEMON RESTART %d/%d in %d s — reason: %s",
        attempt, _MAX_RESTARTS, wait, reason,
    )
    time.sleep(wait)

    import subprocess as _sp
    _flags  = 0
    if sys.platform == "win32":
        _flags = _sp.CREATE_NO_WINDOW | _sp.DETACHED_PROCESS

    _script     = os.path.abspath(__file__)
    _candidates: list[str] = [sys.executable]
    _base = getattr(sys, "_base_executable", None)
    if _base and _base != sys.executable:
        _candidates.append(_base)
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    for _name in ("pythonw.exe", "python.exe"):
        _p = os.path.join(_exe_dir, _name)
        if os.path.isfile(_p) and os.path.getsize(_p) > 0 and _p not in _candidates:
            _candidates.append(_p)

    for _exe in _candidates:
        try:
            _cmd = [_exe, _script, f"--restart-count={attempt}"]
            logger.info("Restart via: [%s] %s (attempt %d/%d)", _exe, _script, attempt, _MAX_RESTARTS)
            _sp.Popen(_cmd, creationflags=_flags, close_fds=True)
            logger.info("Replacement process launched successfully.")
            return
        except Exception as _exc:
            logger.warning("Launch via %s failed: %s", _exe, _exc)

    logger.error(
        "All Python exe candidates failed for restart attempt %d — daemon will not restart.",
        attempt,
    )


# ---------------------------------------------------------------------------
# Background task — Story Teller scheduled job runner
# ---------------------------------------------------------------------------

def _next_run_iso(job: dict) -> str | None:
    """Calculate the next run time (UTC ISO string) for a job after it completes."""
    import datetime as _dt
    stype = job.get("schedule_type", "manual")
    stime = job.get("schedule_time", "02:00")
    try:
        h, m = int(stime.split(":")[0]), int(stime.split(":")[1])
    except Exception:
        h, m = 2, 0

    now   = _dt.datetime.utcnow()
    today = now.replace(hour=h, minute=m, second=0, microsecond=0)

    if stype == "daily":
        nxt = today if today > now else today + _dt.timedelta(days=1)
        return nxt.isoformat()

    if stype == "weekly":
        # schedule_days: comma-separated day names "mon,wed,fri"
        day_map = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}
        days    = [day_map[d.strip().lower()[:3]]
                   for d in job.get("schedule_days","").split(",")
                   if d.strip().lower()[:3] in day_map]
        if not days:
            return None
        curr_wd = now.weekday()
        for d in sorted(days):
            delta = (d - curr_wd) % 7
            candidate = today + _dt.timedelta(days=delta)
            if candidate > now:
                return candidate.isoformat()
        # Wrap to next week
        delta = (min(days) - curr_wd) % 7 or 7
        return (today + _dt.timedelta(days=delta)).isoformat()

    return None   # manual jobs don't auto-schedule


def _run_scheduled_job(job: dict) -> None:
    """Execute the full pipeline for one scheduled job."""
    import models as _m
    from story_engine import stream_story, PROVIDERS_BY_ID
    import voice_engine   as _ve
    import image_engine   as _ie
    import caption_engine as _ce

    job_id    = job["id"]
    job_name  = job.get("name", job_id)
    logger.info("Starting scheduled job '%s'", job_name)

    from datetime import datetime
    started_at = datetime.utcnow().isoformat()
    run_id     = _m.job_run_start(job_id, started_at)
    _m.job_update(job_id, {"status": "running", "last_error": ""})

    s = _read_settings()
    story_id  = None
    error_msg = ""
    vid_path  = ""
    yt_vid_id = ""

    try:
        # ── 1. Generate story ────────────────────────────────────────────────
        provider_id = job.get("ai_provider", "anthropic")
        model_id    = job.get("ai_model", "claude-sonnet-4-6")
        genre_slug  = job.get("genre_slug", "scifi")
        params      = dict(job.get("params") or {})

        prov     = PROVIDERS_BY_ID.get(provider_id, {})
        key_name = prov.get("setting_key", "")
        api_key  = s.get(key_name, "") or os.environ.get(key_name.upper(), "")
        if not api_key:
            raise RuntimeError(f"No API key for {prov.get('name', provider_id)}")

        logger.info("  → Generating story (%s / %s)", provider_id, model_id)
        chunks = list(stream_story(provider_id, model_id, genre_slug, params, api_key))
        content = "".join(chunks).strip()
        if not content:
            raise RuntimeError("Story generation produced no content")

        # Save story to DB
        import re as _re
        first_line = _re.split(r'\n', content)[0][:80].strip()
        title = params.get("title") or first_line or f"{genre_slug.title()} Story"
        story_id = _m.story_create(genre_slug, title, content, params,
                                   provider_id, model_id)
        _m.story_backup(_m.story_get(story_id))
        _m.prompt_save(story_id, genre_slug, "story",
                       provider=provider_id, model=model_id, params=params)

        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)[:50].strip().replace(" ", "_")
        genre_dir = os.path.join(PROJECT_DIR, "stories", genre_slug)
        os.makedirs(genre_dir, exist_ok=True)

        # ── 2. Voice narration ───────────────────────────────────────────────
        vp_id    = job.get("voice_provider", "openai_tts")
        voice_id = job.get("voice_id", "")
        voice_m  = job.get("voice_model", "")
        vprov    = _ve.VOICE_PROVIDERS_BY_ID.get(vp_id, {})
        vkey     = vprov.get("setting_key", "")
        vapi     = s.get(vkey, "") or os.environ.get(vkey.upper(), "")
        if not vapi and vp_id != "google_tts":
            raise RuntimeError(f"No API key for voice provider {vp_id}")

        logger.info("  → Narrating with %s", vp_id)
        audio_bytes = _ve.narrate(vp_id, content, vapi,
                                  voice=voice_id, model=voice_m)
        audio_path  = os.path.join(genre_dir, f"{story_id:05d}_{safe}.mp3")
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)
        _m.prompt_save(story_id, genre_slug, "voice",
                       provider=vp_id, voice=voice_id or vprov.get("default_voice",""))

        # ── 3. Scene image ───────────────────────────────────────────────────
        img_prov = job.get("image_provider", "dalle3")
        iprov    = _ie.IMAGE_PROVIDERS_BY_ID.get(img_prov, {})
        ikey     = s.get(iprov.get("setting_key",""), "") or os.environ.get(
            iprov.get("setting_key","").upper(), "")
        if not ikey:
            raise RuntimeError(f"No API key for image provider {img_prov}")

        logger.info("  → Generating scene image (%s)", img_prov)
        prompt    = _ie.build_image_prompt(genre_slug, title, content[:600])
        img_bytes = _ie.generate(img_prov, prompt, ikey)
        img_path  = os.path.join(genre_dir, f"{story_id:05d}_{safe}_scene.png")
        with open(img_path, "wb") as f:
            f.write(img_bytes)
        _m.prompt_save(story_id, genre_slug, "image", provider=img_prov)

        # ── 4. Captions (text estimate — free, no extra API call) ────────────
        logger.info("  → Generating captions")
        srt      = _ce.text_to_srt(content)
        srt_path = os.path.join(genre_dir, f"{story_id:05d}_{safe}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt)

        # ── 5. Assemble video ────────────────────────────────────────────────
        if _ce.ffmpeg_available():
            logger.info("  → Assembling video")
            vid_path = os.path.join(genre_dir, f"{story_id:05d}_{safe}_video.mp4")
            log, rc  = _ce.assemble_video(
                image_path=img_path,
                audio_path=audio_path,
                output_path=vid_path,
                srt_path=srt_path,
                burn_captions=True,
                caption_style="standard",
            )
            if rc != 0:
                logger.warning("  ffmpeg error: %s", log[-300:])
                vid_path = ""
        else:
            logger.warning("  ffmpeg not found — skipping video assembly")
            vid_path = ""

        # ── 6. YouTube upload (if configured) ────────────────────────────────
        if job.get("yt_upload") and vid_path and os.path.isfile(vid_path):
            import youtube_engine as _yt
            creds_path = os.path.join(PROJECT_DIR, "instance", "youtube_credentials.json")
            if os.path.isfile(creds_path):
                with open(creds_path) as f:
                    creds = json.load(f)
                client_id     = s.get("yt_client_id", "")
                client_secret = s.get("yt_client_secret", "")
                if client_id and client_secret and creds.get("refresh_token"):
                    logger.info("  → Uploading to YouTube")
                    desc = (f"AI-generated {genre_slug} story: {title}\n\n"
                            f"Generated by Story Teller.\n"
                            f"Genre: {genre_slug.title()} | Words: {len(content.split())}")
                    tags = [genre_slug, "story", "narration", "ai story", "audiobook"]
                    result = _yt.upload_video(
                        creds, client_id, client_secret,
                        vid_path, title, desc, tags,
                        privacy=job.get("yt_privacy", "private"),
                    )
                    yt_vid_id = result.get("id", "")
                    with open(creds_path, "w") as f:
                        json.dump(creds, f, indent=2)
                    logger.info("  YouTube video ID: %s", yt_vid_id)
                    _m.prompt_save(story_id, genre_slug, "youtube",
                                   provider="youtube",
                                   params={"video_id": yt_vid_id})

        _m.job_update(job_id, {
            "status":    "idle",
            "last_run":  datetime.utcnow().isoformat(),
            "next_run":  _next_run_iso(job),
            "run_count": job.get("run_count", 0) + 1,
            "last_error": "",
        })
        _m.job_run_finish(run_id, "success",
                          story_id=story_id, video_path=vid_path,
                          yt_video_id=yt_vid_id)
        logger.info("Job '%s' completed — story #%s", job_name, story_id)

    except Exception as exc:
        error_msg = str(exc)
        logger.error("Job '%s' failed: %s", job_name, error_msg, exc_info=True)
        from datetime import datetime as _dt2
        _m.job_update(job_id, {
            "status":     "idle",
            "last_run":   _dt2.utcnow().isoformat(),
            "next_run":   _next_run_iso(job),
            "last_error": error_msg,
        })
        _m.job_run_finish(run_id, "failed", story_id=story_id, error=error_msg)


def _run_background_task() -> None:
    """Check for due scheduled jobs and execute them."""
    logger.info("Checking for due scheduled jobs…")
    try:
        import models as _m
        _m.init_db()
        due = _m.job_due_list()
        if not due:
            logger.info("No jobs due.")
            return
        logger.info("%d job(s) due.", len(due))
        for job in due:
            _run_scheduled_job(job)
    except Exception as exc:
        logger.error("Background task error: %s", exc, exc_info=True)


def _task_interval_secs() -> float:
    """Return seconds between task check cycles. Default: 15 minutes."""
    mins = float(_get("scheduler_check_minutes", 15))
    return max(60.0, mins * 60)


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
            _python = _shutil.which("python") or _shutil.which("python3") or sys.executable  # type: ignore
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
        logger.info("Tray exit — stopping daemon.")
        _user_quit.set()   # intentional stop — suppress restart in main()
        _stop_event.set()
        icon.stop()

    # Watchdog: if the task loop thread dies while the tray is still up,
    # stop the tray so main() can detect the unexpected exit and restart.
    def _loop_watchdog() -> None:
        loop_thread.join()
        if not _user_quit.is_set():
            logger.error(
                "Task loop thread exited unexpectedly — triggering daemon restart."
            )
            _stop_event.set()
            if _tray_icon is not None:
                try:
                    _tray_icon.stop()
                except Exception:
                    pass
            time.sleep(2)
            os._exit(1)   # fallback if tray doesn't stop

    threading.Thread(target=_loop_watchdog, name="loop-watchdog", daemon=True).start()

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
    logger.info("Tray icon started — right-click for options.")
    icon.run()   # blocks until on_exit() calls icon.stop()

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
        logger.info("Stop signal received.")
        _user_quit.set()
        _stop_event.set()

    signal.signal(signal.SIGTERM, _handle_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle_stop)

    try:
        _check_loop()
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        _user_quit.set()
        _stop_event.set()
    finally:
        _remove_pid()
        logger.info("Daemon exited.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Background Daemon")
    parser.add_argument("--once",          action="store_true", help="Run one task cycle and exit.")
    parser.add_argument("--no-tray",       action="store_true", help="Force headless mode.")
    parser.add_argument("--restart-count", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.once:
        _run_background_task()
        return

    if args.restart_count > 0:
        logger.info(
            "Daemon restarted (attempt %d/%d).",
            args.restart_count, _MAX_RESTARTS,
        )

    _write_pid()
    use_tray = not args.no_tray and bool(_get("show_tray_icon", True))

    _crash: Exception | None = None
    try:
        if use_tray and _ensure_tray_deps():
            run_with_tray()
        else:
            run_daemon()
    except Exception as exc:
        _crash = exc
        logger.error("Daemon crashed unexpectedly: %s", exc, exc_info=True)
        _remove_pid()

    # If _user_quit is set the user (or OS) intentionally stopped the daemon.
    # Anything else — crash, pystray exit, loop death — triggers a restart.
    if not _user_quit.is_set():
        _reason = (
            f"unhandled exception: {_crash}"
            if _crash is not None
            else "unexpected exit without clean stop request"
        )
        _restart_self(_reason, args.restart_count)
        os._exit(1)


if __name__ == "__main__":
    main()
