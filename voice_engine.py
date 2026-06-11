"""
voice_engine.py — Story Teller Phase 2
Voice narration via OpenAI TTS, Google Cloud TTS (free tier), and ElevenLabs.
Returns raw audio bytes so the caller can stream or save directly.
"""
from __future__ import annotations
import io
import os
from pathlib import Path

# ── Voice provider catalogue (mirrors story_engine cost format) ────────────────
VOICE_PROVIDERS = [
    {
        "id":          "openai_tts",
        "name":        "OpenAI TTS",
        "icon":        "soundwave",
        "setting_key": "openai_api_key",
        "cost_note":   "~$0.015 / 1k chars (~$0.09 / story)",
        "cost_per_1k_chars": 0.015,
        "voices": [
            {"id": "alloy",   "name": "Alloy",   "desc": "Neutral, balanced"},
            {"id": "echo",    "name": "Echo",    "desc": "Male, warm"},
            {"id": "fable",   "name": "Fable",   "desc": "British, expressive"},
            {"id": "onyx",    "name": "Onyx",    "desc": "Male, deep"},
            {"id": "nova",    "name": "Nova",    "desc": "Female, energetic"},
            {"id": "shimmer", "name": "Shimmer", "desc": "Female, soft"},
        ],
        "default_voice": "onyx",
        "models": [
            {"id": "tts-1",    "name": "TTS-1",    "desc": "Standard quality, fast"},
            {"id": "tts-1-hd", "name": "TTS-1 HD", "desc": "High quality, slower"},
        ],
        "default_model": "tts-1-hd",
    },
    {
        "id":          "google_tts",
        "name":        "Google TTS",
        "icon":        "google",
        "setting_key": "gemini_api_key",
        "cost_note":   "Free up to 1M chars/month",
        "cost_per_1k_chars": 0.0,
        "voices": [
            {"id": "en-US-Journey-D", "name": "Journey D", "desc": "Male, natural"},
            {"id": "en-US-Journey-F", "name": "Journey F", "desc": "Female, natural"},
            {"id": "en-US-Neural2-A", "name": "Neural2-A", "desc": "Female, clear"},
            {"id": "en-US-Neural2-D", "name": "Neural2-D", "desc": "Male, deep"},
            {"id": "en-GB-Neural2-B", "name": "UK Neural2-B", "desc": "British male"},
        ],
        "default_voice": "en-US-Journey-D",
        "models": [
            {"id": "standard", "name": "Standard", "desc": "Free tier"},
            {"id": "neural2",  "name": "Neural2",  "desc": "Free tier (natural)"},
            {"id": "journey",  "name": "Journey",  "desc": "Free tier (most natural)"},
        ],
        "default_model": "journey",
    },
    {
        "id":          "elevenlabs",
        "name":        "ElevenLabs",
        "icon":        "mic-fill",
        "setting_key": "elevenlabs_api_key",
        "cost_note":   "~$0.33 / 10k chars (~$0.20 / story) + plan",
        "cost_per_1k_chars": 0.033,
        "voices": [
            {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel",  "desc": "Female, calm"},
            {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi",    "desc": "Female, strong"},
            {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella",   "desc": "Female, soft"},
            {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni",  "desc": "Male, well-rounded"},
            {"id": "VR6AewLTigWG4xSOukaG", "name": "Arnold",  "desc": "Male, crisp"},
            {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam",    "desc": "Male, deep"},
        ],
        "default_voice": "pNInz6obpgDQGcFmaJgB",
        "models": [
            {"id": "eleven_multilingual_v2", "name": "Multilingual v2", "desc": "Best quality"},
            {"id": "eleven_monolingual_v1",  "name": "English v1",      "desc": "Fast, English only"},
        ],
        "default_model": "eleven_multilingual_v2",
    },
]
VOICE_PROVIDERS_BY_ID = {p["id"]: p for p in VOICE_PROVIDERS}


# ── Narration chunking helpers ─────────────────────────────────────────────────
_MAX_CHUNK = 4000   # OpenAI TTS max is 4096 chars

def _split_text(text: str, max_chars: int = _MAX_CHUNK) -> list[str]:
    """Split story text into narration-safe chunks at sentence boundaries."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) + 1 <= max_chars:
            cur = (cur + " " + s).strip()
        else:
            if cur:
                chunks.append(cur)
            cur = s[:max_chars]
    if cur:
        chunks.append(cur)
    return chunks or [text[:max_chars]]


def _cost_estimate(text: str, provider_id: str) -> float:
    p = VOICE_PROVIDERS_BY_ID.get(provider_id, {})
    return (len(text) / 1000) * p.get("cost_per_1k_chars", 0)


# ── OpenAI TTS ─────────────────────────────────────────────────────────────────
def narrate_openai(text: str, api_key: str,
                   voice: str = "onyx", model: str = "tts-1-hd") -> bytes:
    """Return concatenated MP3 bytes for the full story text."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    chunks = _split_text(text)
    parts: list[bytes] = []
    for chunk in chunks:
        resp = client.audio.speech.create(
            model=model, voice=voice, input=chunk,
            response_format="mp3",
        )
        parts.append(resp.content)
    return b"".join(parts)


# ── Google Cloud TTS ──────────────────────────────────────────────────────────
def narrate_google(text: str, api_key: str,
                   voice_name: str = "en-US-Journey-D",
                   audio_encoding: str = "MP3") -> bytes:
    """
    Google Cloud Text-to-Speech via REST API (no SDK required).
    Uses the standard/neural2/journey voices — free tier.
    """
    import json, urllib.request, urllib.error
    chunks = _split_text(text, 5000)
    parts: list[bytes] = []
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    for chunk in chunks:
        payload = json.dumps({
            "input":       {"text": chunk},
            "voice":       {"languageCode": "en-US", "name": voice_name},
            "audioConfig": {"audioEncoding": audio_encoding},
        }).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        import base64
        parts.append(base64.b64decode(data["audioContent"]))
    return b"".join(parts)


# ── ElevenLabs TTS ─────────────────────────────────────────────────────────────
def narrate_elevenlabs(text: str, api_key: str,
                       voice_id: str = "pNInz6obpgDQGcFmaJgB",
                       model_id: str = "eleven_multilingual_v2") -> bytes:
    """ElevenLabs text-to-speech via REST API."""
    import json, urllib.request
    chunks = _split_text(text, 2500)
    parts: list[bytes] = []
    for chunk in chunks:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = json.dumps({
            "text":     chunk,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={
                "xi-api-key":   api_key,
                "Content-Type": "application/json",
                "Accept":       "audio/mpeg",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            parts.append(resp.read())
    return b"".join(parts)


# ── Unified dispatcher ─────────────────────────────────────────────────────────
def narrate(provider_id: str, text: str, api_key: str,
            voice: str = "", model: str = "") -> bytes:
    """Dispatch to the correct TTS provider. Returns raw MP3 bytes."""
    p = VOICE_PROVIDERS_BY_ID.get(provider_id)
    if not p:
        raise ValueError(f"Unknown voice provider: {provider_id!r}")
    v = voice or p["default_voice"]
    m = model or p["default_model"]
    if provider_id == "openai_tts":
        return narrate_openai(text, api_key, voice=v, model=m)
    if provider_id == "google_tts":
        return narrate_google(text, api_key, voice_name=v)
    if provider_id == "elevenlabs":
        return narrate_elevenlabs(text, api_key, voice_id=v, model_id=m)
    raise ValueError(f"Unimplemented provider: {provider_id!r}")


def cost_estimate(provider_id: str, text: str) -> float:
    return _cost_estimate(text, provider_id)
