"""
Story Teller — Flask application  (port 5005)
Scaffold: web_page_designs  |  Phase 1: Story Studio + Archive
"""
from __future__ import annotations
import io
import json
import os
import time as _time
import threading as _th
import time as _hbt

import subprocess as _sp

from flask import (Flask, Response, jsonify, render_template,
                   request, send_file, stream_with_context)

import models as _db
from story_engine import (GENRES, GENRES_BY_SLUG, PROVIDERS, PROVIDERS_BY_ID,
                          VOICE_PROVIDERS, INTRO_PROVIDERS, IMAGE_PROVIDERS,
                          stream_story)
import voice_engine   as _ve
import image_engine   as _ie
import caption_engine as _ce
import youtube_engine as _yt

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

    # ── API key status (which keys are set — no values exposed) ───────────────
    _KEY_NAMES = [
        "anthropic_api_key", "openai_api_key", "gemini_api_key",
        "elevenlabs_api_key", "stability_api_key", "ideogram_api_key",
    ]

    @app.route("/api/settings/key-status")
    def api_key_status():
        s = _load_settings()
        status = {k: bool(s.get(k, "").strip()) for k in _KEY_NAMES}
        return jsonify({"ok": True, "keys": status})

    # ── API key live test ──────────────────────────────────────────────────────
    @app.route("/api/settings/test-key", methods=["POST"])
    def api_test_key():
        import urllib.request, urllib.error
        d       = request.get_json(silent=True) or {}
        key_id  = d.get("key_id", "")
        s       = _load_settings()
        api_key = s.get(key_id, "").strip()
        if not api_key:
            return jsonify({"ok": False, "error": "No key saved — enter and save a key first."})

        def _req(url, headers=None, data=None, timeout=8):
            req = urllib.request.Request(url, data=data, headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.status, None
            except urllib.error.HTTPError as e:
                if e.code in (400, 401, 403):
                    return e.code, None
                return e.code, str(e)
            except Exception as exc:
                return None, str(exc)

        try:
            if key_id == "anthropic_api_key":
                code, err = _req("https://api.anthropic.com/v1/models",
                                 {"x-api-key": api_key, "anthropic-version": "2023-06-01"})
                if err:     return jsonify({"ok": False, "error": f"Connection error: {err}"})
                if code == 401: return jsonify({"ok": False, "error": "Key rejected — double-check you copied the full key."})
                if code and code < 400: return jsonify({"ok": True, "message": "Anthropic key is valid."})
                return jsonify({"ok": False, "error": f"Unexpected response: HTTP {code}"})

            elif key_id == "openai_api_key":
                code, err = _req("https://api.openai.com/v1/models",
                                 {"Authorization": f"Bearer {api_key}"})
                if err:     return jsonify({"ok": False, "error": f"Connection error: {err}"})
                if code == 401: return jsonify({"ok": False, "error": "Key rejected — check you copied the full key starting with sk-."})
                if code and code < 400: return jsonify({"ok": True, "message": "OpenAI key is valid."})
                return jsonify({"ok": False, "error": f"Unexpected response: HTTP {code}"})

            elif key_id == "gemini_api_key":
                code, err = _req(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}")
                if err:     return jsonify({"ok": False, "error": f"Connection error: {err}"})
                if code == 400: return jsonify({"ok": False, "error": "Key rejected — check the key starts with AIza."})
                if code and code < 400: return jsonify({"ok": True, "message": "Google Gemini key is valid."})
                return jsonify({"ok": False, "error": f"Unexpected response: HTTP {code}"})

            elif key_id == "elevenlabs_api_key":
                code, err = _req("https://api.elevenlabs.io/v1/voices",
                                 {"xi-api-key": api_key})
                if err:     return jsonify({"ok": False, "error": f"Connection error: {err}"})
                if code == 401: return jsonify({"ok": False, "error": "Key rejected — check your ElevenLabs API key."})
                if code and code < 400: return jsonify({"ok": True, "message": "ElevenLabs key is valid."})
                return jsonify({"ok": False, "error": f"Unexpected response: HTTP {code}"})

            elif key_id == "stability_api_key":
                code, err = _req("https://api.stability.ai/v1/user/account",
                                 {"Authorization": f"Bearer {api_key}"})
                if err:     return jsonify({"ok": False, "error": f"Connection error: {err}"})
                if code == 401: return jsonify({"ok": False, "error": "Key rejected — check your Stability AI API key."})
                if code and code < 400: return jsonify({"ok": True, "message": "Stability AI key is valid."})
                return jsonify({"ok": False, "error": f"Unexpected response: HTTP {code}"})

            else:
                return jsonify({"ok": False, "error": f"Testing not supported for '{key_id}'."})

        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

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
        # Record prompt history
        try:
            _db.prompt_save(sid, genre_slug, "story",
                            provider=provider_id, model=model_id,
                            params=parameters)
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
    # VOICE NARRATION API  (Phase 2)
    # ══════════════════════════════════════════════════════════════════════════

    @app.route("/api/voice/providers")
    def api_voice_providers():
        return jsonify({"ok": True, "providers": _ve.VOICE_PROVIDERS})

    @app.route("/api/voice/cost-estimate", methods=["POST"])
    def api_voice_cost():
        d = request.get_json(silent=True) or {}
        text        = d.get("text", "")
        provider_id = d.get("provider_id", "openai_tts")
        cost = _ve.cost_estimate(provider_id, text)
        return jsonify({"ok": True, "cost": cost, "chars": len(text)})

    @app.route("/api/voice/narrate/<int:sid>", methods=["POST"])
    def api_voice_narrate(sid):
        story = _db.story_get(sid)
        if not story:
            return jsonify({"ok": False, "error": "Story not found"}), 404

        d           = request.get_json(silent=True) or {}
        provider_id = d.get("provider_id", "openai_tts")
        voice       = d.get("voice", "")
        model       = d.get("model", "")
        stability   = float(d.get("stability", 0.50))
        style       = float(d.get("style", 0.25))

        settings = _load_settings()
        prov     = _ve.VOICE_PROVIDERS_BY_ID.get(provider_id, {})
        key_name = prov.get("setting_key", "")
        api_key  = settings.get(key_name, "") or os.environ.get(key_name.upper(), "")

        if not api_key and provider_id != "google_tts":
            return jsonify({
                "ok":    False,
                "error": f"No API key for {prov.get('name','provider')}. Add it in Settings → API Keys.",
            }), 400

        try:
            audio_bytes = _ve.narrate(provider_id, story["content"],
                                      api_key, voice=voice, model=model,
                                      stability=stability, style=style)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

        # Save audio file alongside JSON backup
        audio_dir = os.path.join(BASE_DIR, "stories", story["genre_slug"])
        os.makedirs(audio_dir, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                       for c in story.get("title", "story"))[:50].strip().replace(" ", "_")
        audio_path = os.path.join(audio_dir, f"{sid:05d}_{safe}.mp3")
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

        # Record prompt history
        try:
            _db.prompt_save(sid, story.get("genre_slug", ""), "voice",
                            provider=provider_id, model=model,
                            voice=voice or prov.get("default_voice", ""),
                            params={"stability": stability, "style": style})
        except Exception:
            pass

        buf = io.BytesIO(audio_bytes)
        buf.seek(0)
        return send_file(buf, mimetype="audio/mpeg",
                         as_attachment=True,
                         download_name=f"story_{sid}_narration.mp3")

    # ── Voice preview (short cached clip per voice) ────────────────────────────
    _PREVIEW_DIR = os.path.join(BASE_DIR, "instance", "voice_previews")

    @app.route("/api/voice/preview", methods=["POST"])
    def api_voice_preview():
        d           = request.get_json(silent=True) or {}
        provider_id = d.get("provider_id", "openai_tts")
        voice_id    = d.get("voice_id", "")
        model_id    = d.get("model_id", "")

        settings = _load_settings()
        prov     = _ve.VOICE_PROVIDERS_BY_ID.get(provider_id, {})
        key_name = prov.get("setting_key", "")
        api_key  = settings.get(key_name, "") or os.environ.get(key_name.upper(), "")

        if not api_key and provider_id != "google_tts":
            return jsonify({
                "ok":    False,
                "error": f"No API key for {prov.get('name','provider')}. Add it in Settings → API Keys.",
            }), 400

        try:
            audio_bytes = _ve.generate_preview(
                provider_id, voice_id, model_id, api_key, _PREVIEW_DIR
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

        buf = io.BytesIO(audio_bytes)
        buf.seek(0)
        return send_file(buf, mimetype="audio/mpeg",
                         as_attachment=False)

    @app.route("/api/voice/preview/clear", methods=["DELETE"])
    def api_voice_preview_clear():
        import shutil
        try:
            if os.path.isdir(_PREVIEW_DIR):
                shutil.rmtree(_PREVIEW_DIR)
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    # ══════════════════════════════════════════════════════════════════════════
    # IMAGE GENERATION API  (Phase 3)
    # ══════════════════════════════════════════════════════════════════════════

    @app.route("/api/image/providers")
    def api_image_providers():
        return jsonify({"ok": True, "providers": _ie.IMAGE_PROVIDERS})

    @app.route("/api/image/generate/<int:sid>", methods=["POST"])
    def api_image_generate(sid):
        story = _db.story_get(sid)
        if not story:
            return jsonify({"ok": False, "error": "Story not found"}), 404

        d           = request.get_json(silent=True) or {}
        provider_id = d.get("provider_id", "dalle3")
        size        = d.get("size", "")
        quality     = d.get("quality", "")
        custom_prompt = d.get("custom_prompt", "")

        settings = _load_settings()
        prov     = _ie.IMAGE_PROVIDERS_BY_ID.get(provider_id, {})
        key_name = prov.get("setting_key", "")
        api_key  = settings.get(key_name, "") or os.environ.get(key_name.upper(), "")

        if not api_key:
            return jsonify({
                "ok":    False,
                "error": f"No API key for {prov.get('name','provider')}. Add it in Settings → API Keys.",
            }), 400

        prompt = _ie.build_image_prompt(
            story.get("genre_slug", ""),
            story.get("title", "story"),
            story.get("content", "")[:600],
            custom_prompt=custom_prompt,
        )

        try:
            img_bytes = _ie.generate(provider_id, prompt, api_key,
                                     size=size, quality=quality)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

        img_dir = os.path.join(BASE_DIR, "stories", story["genre_slug"])
        os.makedirs(img_dir, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                       for c in story.get("title", "story"))[:50].strip().replace(" ", "_")
        img_path = os.path.join(img_dir, f"{sid:05d}_{safe}_scene.png")
        with open(img_path, "wb") as f:
            f.write(img_bytes)

        # Record prompt history
        try:
            _db.prompt_save(sid, story.get("genre_slug", ""), "image",
                            provider=provider_id,
                            params={"size": size, "quality": quality,
                                    "prompt": prompt[:400]})
        except Exception:
            pass

        buf = io.BytesIO(img_bytes)
        buf.seek(0)
        return send_file(buf, mimetype="image/png",
                         as_attachment=False)

    # ══════════════════════════════════════════════════════════════════════════
    # CAPTION + VIDEO ASSEMBLY API  (Phase 4)
    # ══════════════════════════════════════════════════════════════════════════

    @app.route("/api/ffmpeg/status")
    def api_ffmpeg_status():
        return jsonify({"ok": True, "available": _ce.ffmpeg_available()})

    @app.route("/api/captions/generate/<int:sid>", methods=["POST"])
    def api_captions_generate(sid):
        story = _db.story_get(sid)
        if not story:
            return jsonify({"ok": False, "error": "Story not found"}), 404

        d    = request.get_json(silent=True) or {}
        mode = d.get("mode", "estimate")  # "estimate" | "whisper" | "whisper_word"

        genre_dir = os.path.join(BASE_DIR, "stories", story.get("genre_slug", ""))
        safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                       for c in story.get("title", "story"))[:50].strip().replace(" ", "_")
        audio_path = os.path.join(genre_dir, f"{sid:05d}_{safe}.mp3")

        srt      = ""
        ass      = None
        word_data: list[dict] = []

        if mode in ("whisper", "whisper_word") and os.path.isfile(audio_path):
            settings = _load_settings()
            api_key  = settings.get("openai_api_key", "") or os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return jsonify({"ok": False,
                                "error": "OpenAI API key required for Whisper transcription."}), 400
            try:
                if mode == "whisper_word":
                    srt, word_data = _ce.transcribe_to_word_srt(audio_path, api_key)
                    if word_data:
                        ass = _ce.word_data_to_ass(word_data)
                else:
                    srt = _ce.transcribe_to_srt(audio_path, api_key)
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500
        else:
            srt = _ce.text_to_srt(story.get("content", ""))

        os.makedirs(genre_dir, exist_ok=True)
        srt_path = os.path.join(genre_dir, f"{sid:05d}_{safe}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt)

        ass_path = None
        if ass:
            ass_path = os.path.join(genre_dir, f"{sid:05d}_{safe}.ass")
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(ass)

        return jsonify({
            "ok":         True,
            "srt":        srt,
            "srt_path":   srt_path,
            "ass":        ass,
            "ass_path":   ass_path,
            "has_karaoke": ass is not None,
        })

    @app.route("/api/video/assemble/<int:sid>", methods=["POST"])
    def api_video_assemble(sid):
        story = _db.story_get(sid)
        if not story:
            return jsonify({"ok": False, "error": "Story not found"}), 404

        d             = request.get_json(silent=True) or {}
        burn_caps     = d.get("burn_captions", True)
        music_vol     = float(d.get("music_volume", 0.08))
        caption_style = d.get("caption_style", "standard")  # "standard"|"karaoke"|"none"
        include_intro = bool(d.get("include_intro", False))

        genre_dir = os.path.join(BASE_DIR, "stories", story.get("genre_slug", ""))
        safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                       for c in story.get("title", "story"))[:50].strip().replace(" ", "_")

        audio_path  = os.path.join(genre_dir, f"{sid:05d}_{safe}.mp3")
        image_path  = os.path.join(genre_dir, f"{sid:05d}_{safe}_scene.png")
        srt_path    = os.path.join(genre_dir, f"{sid:05d}_{safe}.srt")
        ass_path    = os.path.join(genre_dir, f"{sid:05d}_{safe}.ass")
        intro_path  = os.path.join(genre_dir, f"{sid:05d}_{safe}_intro.mp4")
        output_path = os.path.join(genre_dir, f"{sid:05d}_{safe}_video.mp4")
        final_path  = os.path.join(genre_dir, f"{sid:05d}_{safe}_final.mp4")

        if not os.path.isfile(audio_path):
            return jsonify({"ok": False,
                            "error": "Narration MP3 not found — generate voice narration first."}), 400
        if not os.path.isfile(image_path):
            return jsonify({"ok": False,
                            "error": "Scene image not found — generate scene image first."}), 400

        log, rc = _ce.assemble_video(
            image_path=image_path,
            audio_path=audio_path,
            output_path=output_path,
            srt_path=srt_path if os.path.isfile(srt_path) else None,
            ass_path=ass_path if os.path.isfile(ass_path) else None,
            burn_captions=burn_caps,
            caption_style=caption_style,
            music_volume=music_vol,
        )
        if rc != 0:
            return jsonify({"ok": False, "error": log[-1000:]}), 500

        serve_path = output_path
        if include_intro and os.path.isfile(intro_path):
            log2, rc2 = _ce.prepend_intro(intro_path, output_path, final_path)
            if rc2 == 0:
                serve_path = final_path

        return send_file(serve_path, mimetype="video/mp4",
                         as_attachment=True,
                         download_name=f"story_{sid}_video.mp4")

    # ── Intro Clip Generator API  (Phase 4b) ──────────────────────────────────

    @app.route("/api/intro/generate/<int:sid>", methods=["POST"])
    def api_intro_generate(sid):
        story = _db.story_get(sid)
        if not story:
            return jsonify({"ok": False, "error": "Story not found"}), 404

        d           = request.get_json(silent=True) or {}
        provider_id = d.get("provider_id", "openai_tts")
        voice       = d.get("voice", "")
        model       = d.get("model", "")
        stability   = float(d.get("stability", 0.50))
        style_v     = float(d.get("style", 0.25))

        settings = _load_settings()
        prov     = _ve.VOICE_PROVIDERS_BY_ID.get(provider_id, {})
        key_name = prov.get("setting_key", "")
        api_key  = settings.get(key_name, "") or os.environ.get(key_name.upper(), "")

        if not api_key and provider_id != "google_tts":
            return jsonify({
                "ok":    False,
                "error": f"No API key for {prov.get('name','provider')}. Add it in Settings → API Keys.",
            }), 400

        import re as _re
        sentences = _re.split(r'(?<=[.!?])\s+', story.get("content", "").strip())
        teaser_text = " ".join(sentences[:3])[:600]

        genre_dir = os.path.join(BASE_DIR, "stories", story.get("genre_slug", ""))
        os.makedirs(genre_dir, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                       for c in story.get("title", "story"))[:50].strip().replace(" ", "_")

        teaser_audio = os.path.join(genre_dir, f"{sid:05d}_{safe}_teaser.mp3")
        intro_path   = os.path.join(genre_dir, f"{sid:05d}_{safe}_intro.mp4")
        image_path   = os.path.join(genre_dir, f"{sid:05d}_{safe}_scene.png")

        if not os.path.isfile(image_path):
            return jsonify({"ok": False,
                            "error": "Scene image not found — generate it in Phase 3 first."}), 400

        try:
            audio_bytes = _ve.narrate(provider_id, teaser_text, api_key,
                                      voice=voice, model=model,
                                      stability=stability, style=style_v)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

        with open(teaser_audio, "wb") as f:
            f.write(audio_bytes)

        log, rc = _ce.build_intro_clip(
            image_path=image_path,
            audio_path=teaser_audio,
            title_text=story.get("title", ""),
            output_path=intro_path,
        )
        if rc != 0:
            return jsonify({"ok": False, "error": f"ffmpeg intro failed: {log[-600:]}"}), 500

        return jsonify({"ok": True, "teaser_text": teaser_text})

    @app.route("/api/intro/preview/<int:sid>")
    def api_intro_preview(sid):
        story = _db.story_get(sid)
        if not story:
            return jsonify({"ok": False, "error": "Not found"}), 404
        safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                       for c in story.get("title", "story"))[:50].strip().replace(" ", "_")
        intro_path = os.path.join(BASE_DIR, "stories",
                                  story.get("genre_slug", ""),
                                  f"{sid:05d}_{safe}_intro.mp4")
        if not os.path.isfile(intro_path):
            return jsonify({"ok": False, "error": "Intro clip not found"}), 404
        return send_file(intro_path, mimetype="video/mp4")

    # ══════════════════════════════════════════════════════════════════════════
    # PROMPT HISTORY API
    # ══════════════════════════════════════════════════════════════════════════

    @app.route("/api/prompts")
    def api_prompts_list():
        genre   = request.args.get("genre") or None
        section = request.args.get("section") or None
        rows    = _db.prompt_list(genre_slug=genre, section=section)
        stats   = _db.prompt_genre_stats()
        return jsonify({"ok": True, "prompts": rows, "stats": stats})

    @app.route("/api/prompts", methods=["POST"])
    def api_prompts_save():
        d = request.get_json(silent=True) or {}
        rid = _db.prompt_save(
            story_id   = d.get("story_id"),
            genre_slug = d.get("genre_slug", ""),
            section    = d.get("section", "story"),
            provider   = d.get("provider", ""),
            model      = d.get("model", ""),
            voice      = d.get("voice", ""),
            params     = d.get("params", {}),
        )
        return jsonify({"ok": True, "id": rid}), 201

    # ══════════════════════════════════════════════════════════════════════════
    # AI PROMPT OPTIMIZER AGENT
    # ══════════════════════════════════════════════════════════════════════════

    @app.route("/api/agent/optimize", methods=["POST"])
    def api_agent_optimize():
        """Analyze prompt history for a genre and return AI improvement suggestions."""
        d           = request.get_json(silent=True) or {}
        genre_slug  = d.get("genre_slug", "")
        provider_id = d.get("provider_id", "anthropic")
        model_id    = d.get("model_id", "claude-haiku-4-5-20251001")

        settings = _load_settings()
        from story_engine import PROVIDERS_BY_ID, GENRES_BY_SLUG
        prov     = PROVIDERS_BY_ID.get(provider_id, {})
        key_name = prov.get("setting_key", "")
        api_key  = settings.get(key_name, "") or os.environ.get(key_name.upper(), "")
        if not api_key:
            return jsonify({"ok": False,
                            "error": f"No API key for {prov.get('name','provider')}. Add it in Settings → API Keys."}), 400

        genre = GENRES_BY_SLUG.get(genre_slug, {})
        if not genre:
            return jsonify({"ok": False, "error": f"Unknown genre: {genre_slug}"}), 400

        # Gather prompt history for this genre
        story_prompts = _db.prompt_list(genre_slug=genre_slug, section="story", limit=30)
        voice_prompts = _db.prompt_list(genre_slug=genre_slug, section="voice", limit=15)
        image_prompts = _db.prompt_list(genre_slug=genre_slug, section="image", limit=15)

        if not story_prompts:
            return jsonify({
                "ok": False,
                "error": (f"No story data for '{genre['name']}' yet. "
                          "Generate at least one story in this genre first.")
            }), 400

        # Build story summary lines
        story_lines = []
        for p in story_prompts:
            params = p.get("params", {})
            wc   = params.get("word_count", "?")
            narr = params.get("narrative", "?")
            tone = params.get("tone", "?")
            hook = params.get("plot_hook", "")[:80]
            line = (f"  • Story #{p['story_id']} | {p['provider']}/{p['model']} | "
                    f"{wc} words | {narr} POV | {tone} tone")
            if hook:
                line += f" | Hook: \"{hook}\""
            story_lines.append(line)

        voice_lines = []
        for p in voice_prompts:
            params = p.get("params", {})
            voice_lines.append(
                f"  • {p['provider']} voice={p['voice']} "
                f"stability={params.get('stability','?')} style={params.get('style','?')}"
            )

        image_lines = []
        for p in image_prompts:
            params = p.get("params", {})
            image_lines.append(
                f"  • {p['provider']} size={params.get('size','?')} quality={params.get('quality','?')}"
            )

        system = (
            "You are an AI content optimization specialist for a YouTube story channel app called Story Teller. "
            "Your job is to analyze past story generation data and provide specific, actionable improvements "
            "to help create better YouTube storytelling content. Be concrete — name exact parameter values, "
            "prompt additions, or voice settings. Do not be vague. Format your response as clearly separated "
            "sections using markdown bold headers."
        )

        user = (
            f"I've generated {len(story_prompts)} stories in the **{genre['name']}** genre "
            f"for a YouTube narration channel.\n\n"
            f"**Story generation history:**\n" + "\n".join(story_lines) + "\n\n"
            + (f"**Voice narration history:**\n" + "\n".join(voice_lines) + "\n\n"
               if voice_lines else "")
            + (f"**Image generation history:**\n" + "\n".join(image_lines) + "\n\n"
               if image_lines else "")
            + f"**Genre description:** {genre.get('description','')}\n"
            f"**Genre guidance hint:** {genre.get('hint','')}\n\n"
            f"Based on this data, provide optimization suggestions in exactly these 4 sections:\n\n"
            f"**1. STORY PROMPTS** — What specific words, phrases, or parameters should I add to my "
            f"{genre['name']} story prompts to make them more compelling for YouTube audiences?\n\n"
            f"**2. VOICE SETTINGS** — What voice provider, specific voice, and ElevenLabs "
            f"stability/style values work best for {genre['name']} narration?\n\n"
            f"**3. SCENE IMAGE** — What visual keywords and style descriptions should I add to "
            f"image generation prompts for {genre['name']} to get better YouTube-worthy scenes?\n\n"
            f"**4. YOUTUBE OPTIMIZATION** — What specific elements (hook phrasing, pacing, "
            f"structural changes) would most improve viewer retention for {genre['name']} stories?\n\n"
            f"Be specific and actionable. Include example prompt text where relevant."
        )

        # Call the AI provider
        try:
            from story_engine import _anthropic, _openai, _gemini  # type: ignore
            chunks: list[str] = []
            if provider_id == "anthropic":
                for chunk in _anthropic(api_key, model_id, system, user, 1200):
                    chunks.append(chunk)
            elif provider_id == "openai":
                for chunk in _openai(api_key, model_id, system, user, 1200):
                    chunks.append(chunk)
            elif provider_id == "gemini":
                for chunk in _gemini(api_key, model_id, system, user, 1200):
                    chunks.append(chunk)
            else:
                return jsonify({"ok": False, "error": f"Unknown provider: {provider_id}"}), 400
            result_text = "".join(chunks)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

        return jsonify({
            "ok":        True,
            "genre":     genre["name"],
            "provider":  provider_id,
            "model":     model_id,
            "analysis":  result_text,
            "story_count": len(story_prompts),
        })

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

    @app.route("/api/git/set-remote", methods=["POST"])
    def api_git_set_remote():
        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        if not url:
            return jsonify({"ok": False, "error": "Remote URL is required."})
        _, rc = _git("remote", "get-url", "origin")
        if rc == 0:
            out, rc = _git("remote", "set-url", "origin", url)
        else:
            out, rc = _git("remote", "add", "origin", url)
        if rc != 0:
            return jsonify({"ok": False, "error": out})
        return jsonify({"ok": True, "remote": url})

    # ══════════════════════════════════════════════════════════════════════════
    # YOUTUBE API  (Phase 5)
    # ══════════════════════════════════════════════════════════════════════════

    _YT_CREDS_PATH = os.path.join(BASE_DIR, "instance", "youtube_credentials.json")

    def _yt_creds() -> dict | None:
        if not os.path.isfile(_YT_CREDS_PATH):
            return None
        try:
            with open(_YT_CREDS_PATH) as f:
                return json.load(f)
        except Exception:
            return None

    def _yt_save_creds(creds: dict) -> None:
        os.makedirs(os.path.dirname(_YT_CREDS_PATH), exist_ok=True)
        with open(_YT_CREDS_PATH, "w") as f:
            json.dump(creds, f, indent=2)

    def _yt_redirect_uri() -> str:
        s    = _load_settings()
        port = int(s.get("app_port", 5005))
        return f"http://127.0.0.1:{port}/api/youtube/callback"

    @app.route("/api/youtube/status")
    def api_yt_status():
        s         = _load_settings()
        client_id = s.get("yt_client_id", "").strip()
        if not client_id:
            return jsonify({"ok": True, "connected": False, "reason": "no_client_id"})
        creds = _yt_creds()
        if not creds or not creds.get("refresh_token"):
            return jsonify({"ok": True, "connected": False, "reason": "not_connected"})
        try:
            client_secret = s.get("yt_client_secret", "").strip()
            channel = _yt.get_channel_info(creds, client_id, client_secret)
            _yt_save_creds(creds)
            return jsonify({"ok": True, "connected": True, "channel": channel})
        except Exception as exc:
            return jsonify({"ok": True, "connected": False,
                            "reason": "error", "error": str(exc)})

    @app.route("/api/youtube/auth-url")
    def api_yt_auth_url():
        s         = _load_settings()
        client_id = s.get("yt_client_id", "").strip()
        if not client_id:
            return jsonify({"ok": False,
                            "error": "YouTube Client ID not set — add it in Settings → YouTube API."}), 400
        url = _yt.build_auth_url(client_id, _yt_redirect_uri())
        return jsonify({"ok": True, "url": url})

    @app.route("/api/youtube/callback")
    def api_yt_callback():
        from flask import render_template
        code  = request.args.get("code",  "")
        error = request.args.get("error", "")
        if error:
            return render_template("youtube_callback.html",
                                   success=False,
                                   message=f"Authorization denied: {error}")
        if not code:
            return render_template("youtube_callback.html",
                                   success=False,
                                   message="No authorization code was returned.")
        s             = _load_settings()
        client_id     = s.get("yt_client_id", "").strip()
        client_secret = s.get("yt_client_secret", "").strip()
        try:
            tok = _yt.exchange_code(code, client_id, client_secret, _yt_redirect_uri())
            creds = {
                "access_token":  tok["access_token"],
                "refresh_token": tok.get("refresh_token", ""),
                "expires_at":    _time.time() + tok.get("expires_in", 3600),
                "scope":         tok.get("scope", ""),
            }
            _yt_save_creds(creds)
            return render_template("youtube_callback.html",
                                   success=True,
                                   message="YouTube connected! You may close this tab.")
        except Exception as exc:
            return render_template("youtube_callback.html",
                                   success=False,
                                   message=f"Error: {exc}")

    @app.route("/api/youtube/disconnect", methods=["POST"])
    def api_yt_disconnect():
        creds = _yt_creds()
        if creds:
            _yt.revoke_credentials(creds.get("access_token", ""))
            try:
                os.remove(_YT_CREDS_PATH)
            except Exception:
                pass
        return jsonify({"ok": True})

    @app.route("/api/youtube/videos")
    def api_yt_videos():
        s             = _load_settings()
        client_id     = s.get("yt_client_id", "").strip()
        client_secret = s.get("yt_client_secret", "").strip()
        creds = _yt_creds()
        if not creds or not client_id:
            return jsonify({"ok": False, "error": "YouTube not connected."}), 400
        try:
            videos = _yt.list_uploads(creds, client_id, client_secret)
            _yt_save_creds(creds)
            return jsonify({"ok": True, "videos": videos})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route("/api/youtube/upload/<int:sid>", methods=["POST"])
    def api_yt_upload(sid):
        story = _db.story_get(sid)
        if not story:
            return jsonify({"ok": False, "error": "Story not found"}), 404
        s             = _load_settings()
        client_id     = s.get("yt_client_id", "").strip()
        client_secret = s.get("yt_client_secret", "").strip()
        creds = _yt_creds()
        if not creds or not client_id:
            return jsonify({"ok": False, "error": "YouTube not connected."}), 400

        d           = request.get_json(silent=True) or {}
        title       = (d.get("title") or story.get("title", "Story")).strip()[:100]
        description = (d.get("description") or
                       f"AI-generated story: {story.get('title','')}\n\nCreated by Story Teller.").strip()
        tags_str    = d.get("tags", "story,narration,ai story,audiobook")
        tags        = [t.strip() for t in tags_str.split(",") if t.strip()]
        cat_id      = str(d.get("category_id", "24"))
        privacy     = d.get("privacy", "private")
        sched_at    = d.get("scheduled_at")

        genre_dir = os.path.join(BASE_DIR, "stories", story.get("genre_slug", ""))
        safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                       for c in story.get("title", "story"))[:50].strip().replace(" ", "_")
        vid_path   = os.path.join(genre_dir, f"{sid:05d}_{safe}_video.mp4")
        final_path = os.path.join(genre_dir, f"{sid:05d}_{safe}_final.mp4")
        if os.path.isfile(final_path):
            vid_path = final_path
        if not os.path.isfile(vid_path):
            return jsonify({"ok": False,
                            "error": "No video file found — assemble the video in Production first."}), 400

        try:
            result = _yt.upload_video(creds, client_id, client_secret,
                                      vid_path, title, description, tags,
                                      category_id=cat_id, privacy=privacy,
                                      scheduled_at=sched_at)
            _yt_save_creds(creds)
            try:
                _db.prompt_save(sid, story.get("genre_slug", ""), "youtube",
                                provider="youtube",
                                params={"privacy": privacy, "title": title,
                                        "video_id": result["id"]})
            except Exception:
                pass
            return jsonify({"ok": True, "video_id": result["id"],
                            "url": result["url"]})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    # ══════════════════════════════════════════════════════════════════════════
    # SCHEDULER API  (Phase 6)
    # ══════════════════════════════════════════════════════════════════════════

    import uuid as _uuid

    @app.route("/api/scheduler/status")
    def api_scheduler_status():
        pid_file = os.path.join(BASE_DIR, "daemon.pid")
        running  = False
        pid      = None
        if os.path.isfile(pid_file):
            try:
                pid = int(open(pid_file).read().strip())
                import signal as _sig
                os.kill(pid, 0)
                running = True
            except Exception:
                running = False
        return jsonify({"ok": True, "running": running, "pid": pid})

    @app.route("/api/scheduler/jobs")
    def api_scheduler_jobs():
        return jsonify({"ok": True, "jobs": _db.job_list()})

    @app.route("/api/scheduler/jobs", methods=["POST"])
    def api_scheduler_create():
        d      = request.get_json(silent=True) or {}
        job_id = str(_uuid.uuid4())
        _db.job_create(job_id, d)
        return jsonify({"ok": True, "job": _db.job_get(job_id)}), 201

    @app.route("/api/scheduler/jobs/<job_id>", methods=["PUT"])
    def api_scheduler_update(job_id):
        d = request.get_json(silent=True) or {}
        _db.job_update(job_id, d)
        return jsonify({"ok": True, "job": _db.job_get(job_id)})

    @app.route("/api/scheduler/jobs/<job_id>", methods=["DELETE"])
    def api_scheduler_delete(job_id):
        _db.job_delete(job_id)
        return jsonify({"ok": True})

    @app.route("/api/scheduler/jobs/<job_id>/run-now", methods=["POST"])
    def api_scheduler_run_now(job_id):
        job = _db.job_get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Job not found"}), 404
        from datetime import datetime
        _db.job_update(job_id, {"next_run": datetime.utcnow().isoformat(),
                                "status":   "pending"})
        return jsonify({"ok": True})

    @app.route("/api/scheduler/jobs/<job_id>/runs")
    def api_scheduler_runs(job_id):
        return jsonify({"ok": True, "runs": _db.job_run_list(job_id)})

    @app.route("/api/scheduler/start", methods=["POST"])
    def api_scheduler_start():
        import subprocess as _subp
        import sys
        daemon_py = os.path.join(BASE_DIR, "daemon.py")
        flags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
        try:
            _subp.Popen(
                [sys.executable, daemon_py],
                creationflags=flags if os.name == "nt" else 0,
                close_fds=True,
                cwd=BASE_DIR,
            )
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route("/api/scheduler/stop", methods=["POST"])
    def api_scheduler_stop():
        pid_file = os.path.join(BASE_DIR, "daemon.pid")
        if not os.path.isfile(pid_file):
            return jsonify({"ok": True, "message": "Daemon not running."})
        try:
            pid = int(open(pid_file).read().strip())
            import signal as _sig
            os.kill(pid, _sig.SIGTERM)
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    # ══════════════════════════════════════════════════════════════════════════
    # TESTS API  (verify each pipeline component)
    # ══════════════════════════════════════════════════════════════════════════

    @app.route("/api/test/story", methods=["POST"])
    def api_test_story():
        """Generate a ~100-word mini test story to verify AI connectivity."""
        d           = request.get_json(silent=True) or {}
        provider_id = d.get("provider_id", "anthropic")
        model_id    = d.get("model_id", "")
        settings    = _load_settings()
        provider    = PROVIDERS_BY_ID.get(provider_id, {})
        key_name    = provider.get("setting_key", "")
        api_key     = settings.get(key_name, "") or os.environ.get(key_name.upper(), "")
        if not api_key:
            return jsonify({
                "ok":    False,
                "error": f"No API key for {provider.get('name','provider')}. "
                         "Add it in Settings → API Keys.",
            }), 400
        model_id = model_id or provider.get("default_model", "")
        params   = {
            "word_count": 100,
            "narrative":  "third",
            "tone":       "neutral",
            "age_rating": "All Ages",
            "characters": 1,
            "setting":    "A quiet lighthouse at dusk",
            "plot_hook":  "A keeper discovers a bottle with tomorrow's newspaper inside it",
        }
        try:
            text = "".join(stream_story(provider_id, model_id, "mystery", params, api_key))
            return jsonify({"ok": True, "text": text.strip(),
                            "words": len(text.split()),
                            "provider": provider_id, "model": model_id})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route("/api/test/image", methods=["POST"])
    def api_test_image():
        """Generate a test scene image to verify image API connectivity."""
        d           = request.get_json(silent=True) or {}
        provider_id = d.get("provider_id", "dalle3")
        settings    = _load_settings()
        prov        = _ie.IMAGE_PROVIDERS_BY_ID.get(provider_id, {})
        key_name    = prov.get("setting_key", "")
        api_key     = settings.get(key_name, "") or os.environ.get(key_name.upper(), "")
        if not api_key:
            return jsonify({
                "ok":    False,
                "error": f"No API key for {prov.get('name','provider')}. "
                         "Add it in Settings → API Keys.",
            }), 400
        prompt = (
            "A lone lighthouse standing at the edge of a dramatic rocky cliff at stormy night. "
            "Massive ocean waves crash below. A single beam of warm golden light sweeps the fog. "
            "Cinematic, atmospheric, digital art, 4K, ultra-detailed."
        )
        try:
            img_bytes = _ie.generate(provider_id, prompt, api_key)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        buf = io.BytesIO(img_bytes)
        buf.seek(0)
        return send_file(buf, mimetype="image/png", as_attachment=False)

    @app.route("/api/test/captions", methods=["GET"])
    def api_test_captions():
        """Convert a short sample text to SRT to verify the caption engine."""
        sample = (
            "The lighthouse stood alone. Its beam cut through the darkness like a blade. "
            "Inside, the keeper heard something unexpected. A knock at the iron door. "
            "No ship should have been close enough. He opened it slowly."
        )
        try:
            srt = _ce.text_to_srt(sample)
            return jsonify({"ok": True, "srt": srt, "sample": sample})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route("/api/test/video", methods=["POST"])
    def api_test_video():
        """Assemble a short test video from the first available story assets."""
        if not _ce.ffmpeg_available():
            return jsonify({"ok": False,
                            "error": "ffmpeg not found. Install ffmpeg and restart the app."}), 400
        # Find any story that has both an MP3 and a PNG
        stories = _db.story_list(limit=50)
        for s in stories:
            sid  = s["id"]
            gs   = s["genre_slug"]
            safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                           for c in (s.get("title") or "story"))[:50].strip().replace(" ", "_")
            gdir  = os.path.join(BASE_DIR, "stories", gs)
            apath = os.path.join(gdir, f"{sid:05d}_{safe}.mp3")
            ipath = os.path.join(gdir, f"{sid:05d}_{safe}_scene.png")
            if os.path.isfile(apath) and os.path.isfile(ipath):
                opath = os.path.join(gdir, f"{sid:05d}_{safe}_test.mp4")
                srt_p = os.path.join(gdir, f"{sid:05d}_{safe}.srt")
                log, rc = _ce.assemble_video(
                    image_path=ipath, audio_path=apath, output_path=opath,
                    srt_path=srt_p if os.path.isfile(srt_p) else None,
                    burn_captions=True, caption_style="standard",
                )
                if rc == 0:
                    return send_file(opath, mimetype="video/mp4", as_attachment=False)
                return jsonify({"ok": False, "error": log[-400:]}), 500
        return jsonify({"ok": False,
                        "error": "No story with both narration audio and scene image found. "
                                 "Generate a story in Production first (voice + image)."}), 400

    return app
