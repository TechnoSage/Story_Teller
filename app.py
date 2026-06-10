"""
Story Teller — Flask application
Port: 5000

Generated from web_page_designs scaffold.
"""
from __future__ import annotations
import io
import json
import os
from datetime import datetime

# ---------------------------------------------------------------------------
# Upgrade-safe schema migration
# ---------------------------------------------------------------------------
# Call _auto_migrate(db) inside the app context after db.create_all().
# It inspects the live SQLite schema and adds any columns/tables that the
# SQLAlchemy models define but the database is missing — without touching
# existing data.  This runs on every startup so upgrades are always safe.
#
# Usage (inside create_app, after db.create_all()):
#   with app.app_context():
#       db.create_all()
#       _auto_migrate(db)
#
# NOTE: This scaffold stub is a no-op unless the app uses SQLAlchemy (db).
# Delete this block if your app has no database.
def _auto_migrate(db_instance) -> None:
    """Add missing tables/columns from SQLAlchemy models to the live DB.
    Safe to call every startup — existing data is never modified.
    """
    try:
        import sqlalchemy as _sa
        inspector = _sa.inspect(db_instance.engine)
        existing_tables = set(inspector.get_table_names())

        for table_name, table in db_instance.metadata.tables.items():
            if table_name not in existing_tables:
                continue  # db.create_all() handles brand-new tables

            existing_cols = {col["name"] for col in inspector.get_columns(table_name)}

            for col in table.columns:
                if col.name in existing_cols:
                    continue

                try:
                    col_type = col.type.compile(dialect=db_instance.engine.dialect)
                except Exception:
                    col_type = "TEXT"

                default_clause = ""
                raw_default = None
                if col.default is not None and hasattr(col.default, "arg"):
                    arg = col.default.arg
                    if not callable(arg):
                        if isinstance(arg, bool):
                            raw_default = 1 if arg else 0
                        elif isinstance(arg, (int, float)):
                            raw_default = arg
                        elif isinstance(arg, str):
                            raw_default = f"'{arg}'"
                elif col.server_default is not None:
                    raw_default = col.server_default.arg

                if raw_default is not None:
                    default_clause = f" DEFAULT {raw_default}"
                elif not col.nullable:
                    default_clause = " DEFAULT 0"

                sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type}{default_clause}'
                try:
                    db_instance.session.execute(db_instance.text(sql))
                    db_instance.session.commit()
                except Exception:
                    db_instance.session.rollback()
    except Exception:
        pass  # No DB or SQLAlchemy not installed — skip silently

from flask import Flask, jsonify, request, render_template

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Version ────────────────────────────────────────────────────────────────────
def _read_app_version() -> str:
    vf = os.path.join(BASE_DIR, "VERSION")
    try:
        if os.path.isfile(vf):
            return open(vf).read().strip() or "1.0.0"
    except Exception:
        pass
    return "1.0.0"


# ── App Settings helpers ───────────────────────────────────────────────────────
_SETTINGS_PATH = os.path.join(BASE_DIR, "instance", "app_settings.json")


def _load_settings() -> dict:
    try:
        if os.path.isfile(_SETTINGS_PATH):
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_settings(data: dict) -> None:
    os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── Application factory ────────────────────────────────────────────────────────
def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

    _app_version = _read_app_version()

    @app.context_processor
    def inject_globals():
        _s = _load_settings()
        return {
            "app_version":           _app_version,
            "app_name":              "Story Teller",
            "support_contact_email": _s.get("support_email", ""),
        }

    # ── Main page ──────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Changelog ─────────────────────────────────────────────────────────────
    @app.route("/api/changelog/data")
    def api_changelog_data():
        cl_path = os.path.join(BASE_DIR, "CHANGELOG.json")
        try:
            if os.path.isfile(cl_path):
                with open(cl_path, encoding="utf-8") as f:
                    data = json.load(f)
                entries = data.get("entries", [])
                return jsonify(sorted(entries, key=lambda e: e.get("version", ""), reverse=True))
        except Exception:
            pass
        return jsonify([])

    # ── Notifications ──────────────────────────────────────────────────────────
    @app.route("/api/notifications")
    def api_notifications():
        # TODO: add app-specific notification logic here
        notes = []
        return jsonify({"ok": True, "notifications": notes, "count": len(notes)})

    # ── App Settings ───────────────────────────────────────────────────────────
    @app.route("/api/app-settings")
    def api_settings_get():
        return jsonify({"ok": True, "settings": _load_settings()})

    @app.route("/api/app-settings", methods=["POST"])
    def api_settings_save():
        d = request.get_json(silent=True) or {}
        current = _load_settings()
        current.update(d)
        _save_settings(current)
        return jsonify({"ok": True, "settings": current})

    # ── Heartbeat / tab-close watchdog ────────────────────────────────────────
    # Every browser tab POSTs /api/heartbeat every 5 s with a unique tabId.
    # The run.py watchdog thread calls os._exit(0) once all tabs go silent.
    #
    # Chrome fires sendBeacon('/api/tab-close') TWICE during same-tab navigation:
    # once on page unload and again ~2 s later as a delayed background delivery.
    # Without the grace period the second beacon wipes the tab after the new page
    # has already re-registered, causing a spurious server shutdown mid-session.
    # Fix: delay actual removal by _CLOSE_GRACE s; any heartbeat cancels the timer.
    import threading as _th
    import time as _hbt

    _tabs:         dict[str, float] = {}
    _tabs_lock     = _th.Lock()
    _ever_had_tab: list[bool]       = [False]
    _CLOSE_GRACE   = 6.0   # seconds before tab-close actually removes the tab

    _pending_close:      dict[str, object] = {}
    _pending_close_lock  = _th.Lock()

    @app.route("/api/heartbeat", methods=["POST"])
    def api_heartbeat():
        tab_id = request.args.get("tab", "")
        if tab_id:
            with _tabs_lock:
                _tabs[tab_id] = _hbt.monotonic()
                _ever_had_tab[0] = True
            # Cancel any pending removal — tab is still alive
            with _pending_close_lock:
                t = _pending_close.pop(tab_id, None)
                if t:
                    t.cancel()
        return "", 204

    @app.route("/api/tab-close", methods=["POST", "GET"])
    def api_tab_close():
        tab_id = request.args.get("tab", "")
        if not tab_id:
            return "", 204

        def _do_remove(tid=tab_id):
            with _tabs_lock:
                _tabs.pop(tid, None)
            with _pending_close_lock:
                _pending_close.pop(tid, None)

        with _pending_close_lock:
            old = _pending_close.pop(tab_id, None)
            if old:
                old.cancel()
            t = _th.Timer(_CLOSE_GRACE, _do_remove)
            t.daemon = True
            t.start()
            _pending_close[tab_id] = t
        return "", 204

    app._tabs         = _tabs
    app._tabs_lock    = _tabs_lock
    app._ever_had_tab = _ever_had_tab
    app._beat_timeout = 120.0   # seconds; Chrome throttles setInterval to ~60 s in bg

    # ── Platform / OS detection ───────────────────────────────────────────────
    # Returns the OS the server is running on so the UI can:
    #   • Display an OS badge in the topbar
    #   • Validate path fields (Windows paths on Linux, etc.)
    #   • Offer OS-appropriate file-browser paths
    # Works on Windows, Linux, and macOS — no dependencies beyond stdlib.
    import platform as _plt
    _OS_SYSTEM = _plt.system()                           # 'Windows' | 'Linux' | 'Darwin'
    _OS_KEY    = {"Windows": "win", "Linux": "linux",
                  "Darwin":  "mac"}.get(_OS_SYSTEM, "win")

    @app.route("/api/platform", methods=["GET"])
    def api_platform():
        return jsonify({
            "ok":         True,
            "os":         _OS_KEY,       # 'win' | 'linux' | 'mac'
            "os_display": _OS_SYSTEM,    # 'Windows' | 'Linux' | 'Darwin'
            "os_full":    f"{_OS_SYSTEM} {_plt.release()}",
        })

    # ── TODO: Add your application routes below ────────────────────────────────

    return app
