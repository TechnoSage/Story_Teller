"""
youtube_engine.py — Story Teller Phase 5
YouTube Data API v3 integration: OAuth2, channel info, video upload.
No extra dependencies — uses stdlib urllib only.
"""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# ── OAuth2 endpoints ───────────────────────────────────────────────────────────
_AUTH_BASE   = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URI   = "https://oauth2.googleapis.com/token"
_REVOKE_URI  = "https://oauth2.googleapis.com/revoke"
_YT_API      = "https://www.googleapis.com/youtube/v3"
_UPLOAD_URI  = "https://www.googleapis.com/upload/youtube/v3/videos"

_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# ── Constants exposed to UI ────────────────────────────────────────────────────
VIDEO_CATEGORIES = {
    "Entertainment":       "24",
    "Education":           "27",
    "Film & Animation":    "1",
    "People & Blogs":      "22",
    "Science & Technology":"28",
    "Howto & Style":       "26",
}

PRIVACY_OPTIONS = ["private", "unlisted", "public"]


# ── OAuth2 helpers ─────────────────────────────────────────────────────────────

def build_auth_url(client_id: str, redirect_uri: str) -> str:
    """Return the Google OAuth2 authorization URL to open in the browser."""
    params = {
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         " ".join(_SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",
    }
    return _AUTH_BASE + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str, client_id: str, client_secret: str,
                  redirect_uri: str) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    payload = urllib.parse.urlencode({
        "code":          code,
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  redirect_uri,
        "grant_type":    "authorization_code",
    }).encode()
    req = urllib.request.Request(
        _TOKEN_URI, data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _refresh(creds: dict, client_id: str, client_secret: str) -> str:
    """Refresh the access token if expired; mutates creds in place. Returns token."""
    now = time.time()
    if now < creds.get("expires_at", 0) - 60:
        return creds["access_token"]
    payload = urllib.parse.urlencode({
        "refresh_token": creds["refresh_token"],
        "client_id":     client_id,
        "client_secret": client_secret,
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request(
        _TOKEN_URI, data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        tok = json.loads(r.read())
    creds["access_token"] = tok["access_token"]
    creds["expires_at"]   = now + tok.get("expires_in", 3600)
    return creds["access_token"]


def revoke_credentials(access_token: str) -> None:
    """Revoke an access token so the app is fully disconnected."""
    url = f"{_REVOKE_URI}?token={urllib.parse.quote(access_token)}"
    try:
        urllib.request.urlopen(
            urllib.request.Request(url, method="POST"), timeout=10
        )
    except Exception:
        pass


# ── YouTube Data API helpers ───────────────────────────────────────────────────

def _yt_get(path: str, token: str, params: dict | None = None) -> dict:
    url = _YT_API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def get_channel_info(creds: dict, client_id: str, client_secret: str) -> dict:
    """Return dict with channel metadata for the authenticated user."""
    token = _refresh(creds, client_id, client_secret)
    data  = _yt_get("/channels", token,
                    {"part": "snippet,statistics", "mine": "true"})
    items = data.get("items", [])
    if not items:
        return {}
    ch    = items[0]
    snip  = ch.get("snippet", {})
    stats = ch.get("statistics", {})
    thumb = (snip.get("thumbnails", {}).get("default", {}) or {}).get("url", "")
    return {
        "id":          ch.get("id", ""),
        "title":       snip.get("title", ""),
        "description": snip.get("description", ""),
        "thumbnail":   thumb,
        "custom_url":  snip.get("customUrl", ""),
        "country":     snip.get("country", ""),
        "subscribers": int(stats.get("subscriberCount", 0)),
        "view_count":  int(stats.get("viewCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
    }


def list_uploads(creds: dict, client_id: str, client_secret: str,
                 max_results: int = 20) -> list[dict]:
    """Return a list of recent video uploads for the authenticated channel."""
    token = _refresh(creds, client_id, client_secret)
    ch_data = _yt_get("/channels", token,
                      {"part": "contentDetails", "mine": "true"})
    items = ch_data.get("items", [])
    if not items:
        return []
    playlist_id = (items[0].get("contentDetails", {})
                   .get("relatedPlaylists", {})
                   .get("uploads", ""))
    if not playlist_id:
        return []
    pl_data = _yt_get("/playlistItems", token,
                      {"part": "snippet", "playlistId": playlist_id,
                       "maxResults": str(min(max_results, 50))})
    results = []
    for item in pl_data.get("items", []):
        snip   = item.get("snippet", {})
        vid_id = (snip.get("resourceId", {}) or {}).get("videoId", "")
        thumb  = (snip.get("thumbnails", {}).get("medium", {}) or {}).get("url", "")
        results.append({
            "id":           vid_id,
            "title":        snip.get("title", ""),
            "description":  (snip.get("description", "") or "")[:200],
            "thumbnail":    thumb,
            "published_at": snip.get("publishedAt", ""),
            "url":          f"https://www.youtube.com/watch?v={vid_id}",
        })
    return results


def upload_video(
    creds: dict,
    client_id: str,
    client_secret: str,
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "24",
    privacy: str = "private",
    scheduled_at: str | None = None,
) -> dict:
    """
    Upload a video to YouTube using the resumable upload protocol.
    Returns {"id": video_id, "url": "https://www.youtube.com/watch?v=<id>"}.

    scheduled_at: ISO-8601 datetime string (e.g. "2026-07-01T12:00:00Z").
    For scheduled uploads: video is set to 'private' + publishAt date/time.
    """
    token = _refresh(creds, client_id, client_secret)

    if scheduled_at and privacy == "public":
        status_obj: dict = {"privacyStatus": "private", "publishAt": scheduled_at}
    else:
        status_obj = {"privacyStatus": privacy}

    metadata = {
        "snippet": {
            "title":       title[:100],
            "description": description[:5000],
            "tags":        tags,
            "categoryId":  category_id,
        },
        "status": status_obj,
    }
    meta_bytes = json.dumps(metadata).encode("utf-8")
    file_size  = os.path.getsize(video_path)
    mime_type  = "video/mp4"

    # ── Initiate resumable session ─────────────────────────────────────────────
    init_req = urllib.request.Request(
        _UPLOAD_URI + "?uploadType=resumable&part=snippet,status",
        data=meta_bytes,
        method="POST",
        headers={
            "Authorization":             f"Bearer {token}",
            "Content-Type":              "application/json; charset=UTF-8",
            "X-Upload-Content-Type":     mime_type,
            "X-Upload-Content-Length":   str(file_size),
        },
    )
    with urllib.request.urlopen(init_req, timeout=30) as r:
        upload_url = r.headers.get("Location", "")
    if not upload_url:
        raise RuntimeError("YouTube did not return a resumable upload URL.")

    # ── Upload in chunks ───────────────────────────────────────────────────────
    CHUNK = 8 * 1024 * 1024   # 8 MB
    uploaded  = 0
    video_id  = ""

    with open(video_path, "rb") as fh:
        while uploaded < file_size:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            end = uploaded + len(chunk) - 1
            chunk_req = urllib.request.Request(
                upload_url, data=chunk, method="PUT",
                headers={
                    "Authorization":  f"Bearer {token}",
                    "Content-Type":   mime_type,
                    "Content-Range":  f"bytes {uploaded}-{end}/{file_size}",
                    "Content-Length": str(len(chunk)),
                },
            )
            try:
                with urllib.request.urlopen(chunk_req, timeout=180) as r:
                    body = r.read()
                    if body:
                        resp_data = json.loads(body)
                        video_id = resp_data.get("id", "")
            except urllib.error.HTTPError as exc:
                if exc.code == 308:
                    pass   # Resume Incomplete — expected for non-final chunks
                else:
                    raise
            uploaded += len(chunk)

    if not video_id:
        raise RuntimeError("Upload complete but no video ID was returned.")

    return {
        "id":  video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }
