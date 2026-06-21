"""
models.py — Story Teller database schema and CRUD helpers.
Uses raw sqlite3 (WAL mode) — no ORM dependency.
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_PATH  = os.path.join(_BASE_DIR, "instance", "story_teller.db")


# ── Connection factory ──────────────────────────────────────────────────────────
def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


# ── Schema init ─────────────────────────────────────────────────────────────────
def init_db() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS stories (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT    DEFAULT '',
                genre_slug   TEXT    NOT NULL,
                word_count   INTEGER DEFAULT 0,
                content      TEXT    DEFAULT '',
                parameters   TEXT    DEFAULT '{}',
                ai_provider  TEXT    DEFAULT '',
                ai_model     TEXT    DEFAULT '',
                status       TEXT    DEFAULT 'saved',
                created_at   TEXT    DEFAULT (datetime('now')),
                updated_at   TEXT    DEFAULT (datetime('now')),
                notes        TEXT    DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS prompt_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                story_id    INTEGER,
                genre_slug  TEXT    DEFAULT '',
                section     TEXT    NOT NULL,
                provider    TEXT    DEFAULT '',
                model       TEXT    DEFAULT '',
                voice       TEXT    DEFAULT '',
                params      TEXT    DEFAULT '{}',
                created_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL DEFAULT '',
                enabled         INTEGER NOT NULL DEFAULT 1,
                genre_slug      TEXT NOT NULL DEFAULT 'scifi',
                params          TEXT NOT NULL DEFAULT '{}',
                ai_provider     TEXT NOT NULL DEFAULT 'anthropic',
                ai_model        TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
                voice_provider  TEXT NOT NULL DEFAULT 'openai_tts',
                voice_id        TEXT NOT NULL DEFAULT '',
                voice_model     TEXT NOT NULL DEFAULT '',
                image_provider  TEXT NOT NULL DEFAULT 'dalle3',
                yt_upload       INTEGER NOT NULL DEFAULT 0,
                yt_privacy      TEXT NOT NULL DEFAULT 'private',
                schedule_type   TEXT NOT NULL DEFAULT 'manual',
                schedule_time   TEXT NOT NULL DEFAULT '02:00',
                schedule_days   TEXT NOT NULL DEFAULT '',
                next_run        TEXT,
                last_run        TEXT,
                status          TEXT NOT NULL DEFAULT 'idle',
                last_error      TEXT NOT NULL DEFAULT '',
                run_count       INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS job_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          TEXT NOT NULL,
                story_id        INTEGER,
                started_at      TEXT NOT NULL,
                completed_at    TEXT,
                status          TEXT NOT NULL DEFAULT 'running',
                error           TEXT NOT NULL DEFAULT '',
                video_path      TEXT NOT NULL DEFAULT '',
                yt_video_id     TEXT NOT NULL DEFAULT '',
                cost_estimate   REAL NOT NULL DEFAULT 0.0
            );
        """)


# ── Story CRUD ─────────────────────────────────────────────────────────────────
def story_create(genre_slug: str, title: str, content: str,
                 parameters: dict, ai_provider: str, ai_model: str) -> int:
    wc = len(content.split())
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO stories
               (genre_slug, title, content, word_count, parameters, ai_provider, ai_model)
               VALUES (?,?,?,?,?,?,?)""",
            (genre_slug, title or _auto_title(genre_slug), content, wc,
             json.dumps(parameters), ai_provider, ai_model),
        )
        return cur.lastrowid


def story_list(genre_slug: str | None = None, limit: int = 200) -> list[dict]:
    sql  = ("SELECT id, title, genre_slug, word_count, ai_provider, ai_model, "
            "status, created_at FROM stories")
    args: list = []
    if genre_slug:
        sql += " WHERE genre_slug=?"; args.append(genre_slug)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def story_get(story_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM stories WHERE id=?", (story_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["parameters"] = json.loads(d.get("parameters") or "{}")
    except Exception:
        d["parameters"] = {}
    return d


def story_update(story_id: int, **fields) -> bool:
    allowed = {"title", "content", "word_count", "notes", "status"}
    upd = {k: v for k, v in fields.items() if k in allowed}
    if not upd:
        return False
    if "content" in upd and "word_count" not in upd:
        upd["word_count"] = len(str(upd["content"]).split())
    upd["updated_at"] = datetime.utcnow().isoformat()
    sql = "UPDATE stories SET " + ", ".join(f"{k}=?" for k in upd) + " WHERE id=?"
    with _conn() as c:
        c.execute(sql, list(upd.values()) + [story_id])
    return True


def story_delete(story_id: int) -> bool:
    with _conn() as c:
        c.execute("DELETE FROM stories WHERE id=?", (story_id,))
    return True


def story_stats() -> dict:
    with _conn() as c:
        total  = c.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
        this_w = c.execute(
            "SELECT COUNT(*) FROM stories WHERE created_at >= date('now','-7 days')"
        ).fetchone()[0]
        words  = c.execute("SELECT SUM(word_count) FROM stories").fetchone()[0] or 0
        by_g   = c.execute(
            "SELECT genre_slug, COUNT(*) n FROM stories GROUP BY genre_slug ORDER BY n DESC"
        ).fetchall()
    return {
        "total": total,
        "this_week": this_w,
        "total_words": words,
        "by_genre": [dict(r) for r in by_g],
    }


# ── Backup helpers ─────────────────────────────────────────────────────────────
_BACKUP_DIR = os.path.join(_BASE_DIR, "stories")


def story_backup(story: dict) -> str:
    """Write story JSON to stories/{genre}/{id}_{slug}.json. Returns path."""
    genre_dir = os.path.join(_BACKUP_DIR, story["genre_slug"])
    os.makedirs(genre_dir, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in story.get("title", "story"))
    safe = safe[:60].strip().replace(" ", "_")
    fname = f"{story['id']:05d}_{safe}.json"
    fpath = os.path.join(genre_dir, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2, ensure_ascii=False)
    return fpath


# ── Prompt history CRUD ───────────────────────────────────────────────────────
def prompt_save(
    story_id: int | None,
    genre_slug: str,
    section: str,
    provider: str = "",
    model: str = "",
    voice: str = "",
    params: dict | None = None,
) -> int:
    """Record a generation event. section: 'story' | 'voice' | 'image'."""
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO prompt_history
               (story_id, genre_slug, section, provider, model, voice, params)
               VALUES (?,?,?,?,?,?,?)""",
            (story_id, genre_slug or "", section,
             provider or "", model or "", voice or "",
             json.dumps(params or {})),
        )
        return cur.lastrowid


def prompt_list(
    genre_slug: str | None = None,
    section: str | None = None,
    limit: int = 150,
) -> list[dict]:
    sql  = "SELECT * FROM prompt_history"
    conds: list[str] = []
    args: list = []
    if genre_slug:
        conds.append("genre_slug=?"); args.append(genre_slug)
    if section:
        conds.append("section=?"); args.append(section)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["params"] = json.loads(d.get("params") or "{}")
        except Exception:
            d["params"] = {}
        result.append(d)
    return result


def prompt_genre_stats() -> list[dict]:
    """Return count of prompt_history records grouped by genre and section."""
    with _conn() as c:
        rows = c.execute(
            """SELECT genre_slug, section, COUNT(*) n
               FROM prompt_history
               GROUP BY genre_slug, section
               ORDER BY genre_slug, section"""
        ).fetchall()
    return [dict(r) for r in rows]


# ── Scheduled jobs CRUD ───────────────────────────────────────────────────────

_JOB_FIELDS = {
    "name", "enabled", "genre_slug", "params", "ai_provider", "ai_model",
    "voice_provider", "voice_id", "voice_model", "image_provider",
    "yt_upload", "yt_privacy", "schedule_type", "schedule_time",
    "schedule_days", "next_run", "last_run", "status", "last_error", "run_count",
}


def job_create(job_id: str, data: dict) -> None:
    cols, vals = ["id"], [job_id]
    for k, v in data.items():
        if k in _JOB_FIELDS:
            cols.append(k)
            vals.append(json.dumps(v) if isinstance(v, dict) else v)
    sql = f"INSERT OR REPLACE INTO scheduled_jobs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    with _conn() as c:
        c.execute(sql, vals)


def job_list() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM scheduled_jobs ORDER BY created_at DESC"
        ).fetchall()
    return [_job_row(r) for r in rows]


def job_get(job_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,)).fetchone()
    return _job_row(row) if row else None


def job_update(job_id: str, data: dict) -> None:
    upd = {k: v for k, v in data.items() if k in _JOB_FIELDS}
    if not upd:
        return
    sql = "UPDATE scheduled_jobs SET " + ", ".join(f"{k}=?" for k in upd) + " WHERE id=?"
    vals = [json.dumps(v) if isinstance(v, dict) else v for v in upd.values()]
    vals.append(job_id)
    with _conn() as c:
        c.execute(sql, vals)


def job_delete(job_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM scheduled_jobs WHERE id=?", (job_id,))


def job_due_list() -> list[dict]:
    """Return all enabled jobs whose next_run is <= now (or null with manual=no)."""
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM scheduled_jobs
               WHERE enabled=1 AND status NOT IN ('running')
               AND schedule_type != 'manual'
               AND (next_run IS NULL OR next_run <= ?)
               ORDER BY next_run ASC""",
            (now,)
        ).fetchall()
    return [_job_row(r) for r in rows]


def _job_row(row) -> dict:
    d = dict(row)
    try:
        d["params"] = json.loads(d.get("params") or "{}")
    except Exception:
        d["params"] = {}
    return d


# ── Job run log ───────────────────────────────────────────────────────────────

def job_run_start(job_id: str, started_at: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO job_runs (job_id, started_at) VALUES (?,?)",
            (job_id, started_at),
        )
        return cur.lastrowid


def job_run_finish(run_id: int, status: str, story_id: int | None = None,
                   error: str = "", video_path: str = "",
                   yt_video_id: str = "", cost: float = 0.0) -> None:
    with _conn() as c:
        c.execute(
            """UPDATE job_runs SET completed_at=datetime('now'), status=?,
               story_id=?, error=?, video_path=?, yt_video_id=?, cost_estimate=?
               WHERE id=?""",
            (status, story_id, error, video_path, yt_video_id, cost, run_id),
        )


def job_run_list(job_id: str, limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM job_runs WHERE job_id=? ORDER BY started_at DESC LIMIT ?",
            (job_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Internal helpers ──────────────────────────────────────────────────────────
def _auto_title(genre_slug: str) -> str:
    from datetime import date
    return f"{genre_slug.replace('_', ' ').title()} Story — {date.today().isoformat()}"
