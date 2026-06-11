"""
Story Teller — Flask application  (port 5005)
Scaffold: web_page_designs  |  Phase 1: Story Studio + Archive
"""
from __future__ import annotations
import io
import json
import os
import threading as _th
import time as _hbt

import subprocess as _sp

from flask import (Flask, Response, jsonify, render_template,
                   request, send_file, stream_with_context)

import models as _db
from story_engine import (GENRES, GENRES_BY_SLUG, PROVIDERS, PROVIDERS_BY_ID,
                          VOICE_PROVIDERS, INTRO_PROVIDERS, IMAGE_PROVIDERS,
                          stream_story)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Version ────────────────────────────────────────────────────────────────────
def _read_version() -> str:
    vf = os.path.join(BASE_DIR, "VERSION")
    try:
        return open(vf).read().strip() or "1.0.0"
    except Exception:
        return "1.0.0"


# ── Settings ───────────────────────────────────────────────────────────────────
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


# ── App factory ────────────────────────────────────────────────────────────────
def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "stories"),  exist_ok=True)

    _db.init_db()
    _app_version = _read_version()

    @app.context_processor
    def _globals():
        s = _load_settings()
        return {
            "app_version":           _app_version,
            "app_name":              "Story Teller",
            "support_contact_email": s.get("support_email", ""),
        }

    # ── Main page ──────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Changelog ─────────────────────────────────────────────────────────────
    @app.route("/api/changelog/data")
    def api_changelog():
        cl = os.path.join(BASE_DIR, "CHANGELOG.json")
        try:
            if os.path.isfile(cl):
                data = json.load(open(cl, encoding="utf-8"))
                return jsonify(sorted(data.get("entries", []),
                                      key=lambda e: e.get("version", ""), reverse=True))
        except Exception:
            pass
        return jsonify([])

    # ── Notifications ──────────────────────────────────────────────────────────
    @app.route("/api/notifications")
    def api_notifications():
        return jsonify({"ok": True, "notifications": [], "count": 0})

    # ── App settings ───────────────────────────────────────────────────────────
    @app.route("/api/app-settings")
    def api_settings_get():
        return jsonify({"ok": True, "settings": _load_settings()})

    @app.route("/api/app-settings", methods=["POST"])
    def api_settings_save():
        d = request.get_json(silent=True) or {}
        s = _load_settings()
        s.update(d)
        _save_settings(s)
        return jsonify({"ok": True, "settings": s})

    # ── Platform / OS ──────────────────────────────────────────────────────────
    import platform as _plt
    _OS_SYSTEM = _plt.system()
    _OS_KEY    = {"Windows": "win", "Linux": "linux", "Darwin": "mac"}.get(_OS_SYSTEM, "win")

    @app.route("/api/platform")
    def api_platform():
        return jsonify({"ok": True, "os": _OS_KEY,
                        "os_display": _OS_SYSTEM,
                        "os_full": f"{_OS_SYSTEM} {_plt.release()}"})

    # ── Heartbeat / tab-close watchdog ────────────────────────────────────────
    _tabs:         dict[str, float] = {}
    _tabs_lock     = _th.Lock()
    _ever_had_tab: list[bool]       = [False]
    _CLOSE_GRACE   = 6.0
    _pending_close: dict[str, object] = {}
    _pc_lock        = _th.Lock()

    @app.route("/api/heartbeat", methods=["POST"])
    def api_heartbeat():
        tid = request.args.get("tab", "")
        if tid:
            with _tabs_lock:
                _tabs[tid] = _hbt.monotonic()
                _ever_had_tab[0] = True
            with _pc_lock:
                t = _pending_close.pop(tid, None)
                if t: t.cancel()
        return "", 204

    @app.route("/api/tab-close", methods=["POST", "GET"])
    def api_tab_close():
        tid = request.args.get("tab", "")
        if not tid:
            return "", 204
        def _remove(t=tid):
            with _tabs_lock: _tabs.pop(t, None)
            with _pc_lock:   _pending_close.pop(t, None)
        with _pc_lock:
            old = _pending_close.pop(tid, None)
            if old: old.cancel()
            timer = _th.Timer(_CLOSE_GRACE, _remove)
            timer.daemon = True
            timer.start()
            _pending_close[tid] = timer
        return "", 204

    app._tabs         = _tabs
    app._tabs_lock    = _tabs_lock
    app._ever_had_tab = _ever_had_tab
    app._beat_timeout = 120.0

    # ── Browse folder (tkinter) ────────────────────────────────────────────────
    @app.route("/api/browse/folder")
    def api_browse_folder():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
            path = filedialog.askdirectory(title="Select folder", parent=root)
            root.destroy()
            return jsonify({"ok": True, "path": path or ""})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ══════════════════════════════════════════════════════════════════════════
    # STORY TELLER API
    # ══════════════════════════════════════════════════════════════════════════

    # ── Genre catalogue ────────────────────────────────────────────────────────
    @app.route("/api/genres")
    def api_genres():
        return jsonify({"ok": True, "genres": GENRES})

    # ── Provider + cost catalogue ──────────────────────────────────────────────
    @app.route("/api/providers")
    def api_providers():
        return jsonify({
            "ok":              True,
            "providers":       PROVIDERS,
            "voice_providers": VOICE_PROVIDERS,
            "intro_providers": INTRO_PROVIDERS,
            "image_providers": IMAGE_PROVIDERS,
        })

    # ── Story generation — SSE streaming ──────────────────────────────────────
    @app.route("/api/stories/generate", methods=["POST"])
    def api_generate():
        data        = request.get_json(silent=True) or {}
        genre_slug  = data.get("genre_slug", "scifi")
        provider_id = data.get("provider_id", "anthropic")
        model_id    = data.get("model_id", "claude-sonnet-4-6")
        params      = data.get("params", {})

        settings = _load_settings()
        provider = PROVIDERS_BY_ID.get(provider_id, {})
        key_name = provider.get("setting_key", "")
        api_key  = (settings.get(key_name, "") or
                    os.environ.get(key_name.upper(), ""))

        if not api_key:
            return jsonify({
                "ok":    False,
                "error": (f"No API key found for {provider.get('name', 'provider')}. "
                          f"Go to Settings → API Keys and add your key."),
            }), 400

        def _sse():
            try:
                for chunk in stream_story(provider_id, model_id,
                                          genre_slug, params, api_key):
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            finally:
                yield f"data: {json.dumps({'done': True})}\n\n"

        return Response(
            stream_with_context(_sse()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Story CRUD ─────────────────────────────────────────────────────────────
    @app.route("/api/stories", methods=["GET"])
    def api_stories_list():
        genre   = request.args.get("genre")
        stories = _db.story_list(genre_slug=genre)
        return jsonify({"ok": True, "stories": stories})

    @app.route("/api/stories", methods=["POST"])
    def api_stories_create():
        d           = request.get_json(silent=True) or {}
        genre_slug  = d.get("genre_slug", "scifi")
        title       = d.get("title", "").strip()
        content     = d.get("content", "").strip()
        parameters  = d.get("parameters", {})
        provider_id = d.get("ai_provider", "")
        model_id    = d.get("ai_model", "")
        if not content:
            return jsonify({"ok": False, "error": "content is required"}), 400
        sid   = _db.story_create(genre_slug, title, content,
                                 parameters, provider_id, model_id)
        story = _db.story_get(sid)
        try:
            _db.story_backup(story)
        except Exception:
            pass
        return jsonify({"ok": True, "story": story}), 201

    @app.route("/api/stories/<int:sid>", methods=["GET"])
    def api_stories_get(sid):
        story = _db.story_get(sid)
        if not story:
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({"ok": True, "story": story})

    @app.route("/api/stories/<int:sid>", methods=["PUT"])
    def api_stories_update(sid):
        d = request.get_json(silent=True) or {}
        _db.story_update(sid, **d)
        return jsonify({"ok": True, "story": _db.story_get(sid)})

    @app.route("/api/stories/<int:sid>", methods=["DELETE"])
    def api_stories_delete(sid):
        _db.story_delete(sid)
        return jsonify({"ok": True})

    @app.route("/api/stories/<int:sid>/download")
    def api_stories_download(sid):
        story = _db.story_get(sid)
        if not story:
            return jsonify({"ok": False, "error": "Not found"}), 404
        fmt = request.args.get("fmt", "txt")
        if fmt == "json":
            buf  = io.BytesIO(json.dumps(story, indent=2,
                                         ensure_ascii=False).encode())
            name = f"story_{sid}.json"
            mime = "application/json"
        else:
            buf  = io.BytesIO(story["content"].encode())
            name = f"story_{sid}.txt"
            mime = "text/plain"
        buf.seek(0)
        return send_file(buf, mimetype=mime,
                         as_attachment=True, download_name=name)

    # ── Dashboard stats ────────────────────────────────────────────────────────
    @app.route("/api/stats")
    def api_stats():
        return jsonify({"ok": True, "stats": _db.story_stats()})

    # ══════════════════════════════════════════════════════════════════════════
    # GIT / VCS API  (repo = BASE_DIR — Story Teller's own directory)
    # ══════════════════════════════════════════════════════════════════════════
    _CREATE_NO_WINDOW = 0x08000000

    def _git(*args: str, timeout: int = 20) -> tuple[str, int]:
        import platform as _p
        cf = _CREATE_NO_WINDOW if _p.system() == "Windows" else 0
        try:
            r = _sp.run(
                ["git", *args], cwd=BASE_DIR,
                capture_output=True, text=True,
                timeout=timeout, creationflags=cf,
            )
            return (r.stdout + r.stderr).strip(), r.returncode
        except Exception as exc:
            return str(exc), 1

    @app.route("/api/git/status")
    def api_git_status():
        branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
        status, _ = _git("status", "--short")
        log,    _ = _git("log", "--oneline", "-12")
        diff_stat, _ = _git("diff", "--stat", "HEAD")
        remote, _ = _git("remote", "get-url", "origin")
        return jsonify({
            "ok":             True,
            "branch":         branch or "(unknown)",
            "dirty":          bool(status.strip()),
            "status":         status.strip() or "(clean — nothing to commit)",
            "recent_log":     log.strip() or "(no commits)",
            "diff_stat":      diff_stat.strip(),
            "remote":         remote.strip(),
        })

    @app.route("/api/git/commit-push", methods=["POST"])
    def api_git_commit_push():
        data   = request.get_json(silent=True) or {}
        msg    = (data.get("message") or "").strip()
        branch = (data.get("branch") or "development").strip()
        if not msg:
            return jsonify({"ok": False, "error": "Commit message is required."})
        add_out, rc = _git("add", "-A")
        if rc != 0:
            return jsonify({"ok": False, "error": f"git add failed:\n{add_out}"})
        cmt_out, rc = _git("commit", "-m", msg, timeout=30)
        if rc != 0 and "nothing to commit" not in cmt_out:
            return jsonify({"ok": False, "error": f"git commit failed:\n{cmt_out}"})
        psh_out, rc = _git("push", "origin", branch, timeout=60)
        if rc != 0:
            return jsonify({"ok": False, "error": f"git push failed:\n{psh_out}"})
        return jsonify({"ok": True, "output": f"{cmt_out}\n{psh_out}".strip()})

    @app.route("/api/git/pull", methods=["POST"])
    def api_git_pull():
        out, rc = _git("pull", "--rebase", timeout=60)
        if rc != 0:
            return jsonify({"ok": False, "error": f"git pull failed:\n{out}"})
        return jsonify({"ok": True, "output": out})

    @app.route("/api/git/merge-main", methods=["POST"])
    def api_git_merge_main():
        """Merge development → main, push main, return to development."""
        # Determine current/dev branch
        cur, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
        dev = cur.strip() or "development"
        # Checkout main
        out1, rc = _git("checkout", "main")
        if rc != 0:
            return jsonify({"ok": False, "error": f"checkout main failed:\n{out1}"})
        # Merge
        out2, rc = _git("merge", "--no-ff", dev,
                        "-m", f"release: merge {dev} → main", timeout=30)
        if rc != 0:
            _git("checkout", dev)
            return jsonify({"ok": False, "error": f"merge failed:\n{out2}"})
        # Push main
        out3, rc = _git("push", "origin", "main", timeout=60)
        if rc != 0:
            _git("checkout", dev)
            return jsonify({"ok": False, "error": f"push main failed:\n{out3}"})
        # Return to dev
        _git("checkout", dev)
        return jsonify({"ok": True, "output": f"{out2}\n{out3}".strip()})

    @app.route("/api/git/branches")
    def api_git_branches():
        out, _ = _git("branch", "-a")
        branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
        return jsonify({"ok": True, "branches": branches})

    return app
