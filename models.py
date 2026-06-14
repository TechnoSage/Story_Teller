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


# ── Internal helpers ──────────────────────────────────────────────────────────
def _auto_title(genre_slug: str) -> str:
    from datetime import date
    return f"{genre_slug.replace('_', ' ').title()} Story — {date.today().isoformat()}"
