"""
voice_engine.py — Story Teller Phase 2
Voice narration via OpenAI TTS, Google Cloud TTS (free tier), and ElevenLabs.
Returns raw audio bytes so the caller can stream or save directly.
"""
from __future__ import annotations
import io
import os
import re as _re
from pathlib import Path

# ── Sample text used for voice preview clips ───────────────────────────────────
VOICE_PREVIEW_TEXT = (
    "The old lighthouse stood at the edge of the world, "
    "its beacon cutting through the dark like a blade of light. "
    "Inside, a lone keeper tended the flame — "
    "unaware that tonight, the sea had other plans."
)

# ── Voice provider catalogue (mirrors story_engine cost format) ────────────────
# gender: "M" = Male, "F" = Female, "N" = Neutral/Unspecified
VOICE_PROVIDERS = [
    {
        "id":          "openai_tts",
        "name":        "OpenAI TTS",
        "icon":        "soundwave",
        "setting_key": "openai_api_key",
        "cost_note":   "~$0.015 / 1k chars (~$0.09 / story)",
        "cost_per_1k_chars": 0.015,
        "voices": [
            {"id": "onyx",    "name": "Onyx",    "gender": "M", "desc": "Deep, powerful narrator"},
            {"id": "echo",    "name": "Echo",    "gender": "M", "desc": "Warm, engaging storyteller"},
            {"id": "ash",     "name": "Ash",     "gender": "M", "desc": "Confident, conversational"},
            {"id": "fable",   "name": "Fable",   "gender": "F", "desc": "British, expressive narrator"},
            {"id": "nova",    "name": "Nova",    "gender": "F", "desc": "Energetic, dynamic voice"},
            {"id": "shimmer", "name": "Shimmer", "gender": "F", "desc": "Soft, calming storyteller"},
            {"id": "coral",   "name": "Coral",   "gender": "F", "desc": "Warm, natural tone"},
            {"id": "sage",    "name": "Sage",    "gender": "F", "desc": "Thoughtful, measured pace"},
            {"id": "alloy",   "name": "Alloy",   "gender": "N", "desc": "Neutral, balanced tone"},
        ],
        "default_voice": "onyx",
        "models": [
            {"id": "tts-1-hd", "name": "TTS-1 HD", "desc": "High quality, slightly slower"},
            {"id": "tts-1",    "name": "TTS-1",    "desc": "Standard quality, fast"},
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
            {"id": "en-US-Journey-D",  "name": "Journey D",     "gender": "M", "desc": "American male, natural"},
            {"id": "en-US-Neural2-D",  "name": "Neural2-D",     "gender": "M", "desc": "American male, deep"},
            {"id": "en-US-Neural2-J",  "name": "Neural2-J",     "gender": "M", "desc": "American male, authoritative"},
            {"id": "en-GB-Neural2-B",  "name": "UK Neural2-B",  "gender": "M", "desc": "British male, clear"},
            {"id": "en-AU-Neural2-B",  "name": "AU Neural2-B",  "gender": "M", "desc": "Australian male"},
            {"id": "en-US-Journey-F",  "name": "Journey F",     "gender": "F", "desc": "American female, natural"},
            {"id": "en-US-Neural2-A",  "name": "Neural2-A",     "gender": "F", "desc": "American female, clear"},
            {"id": "en-GB-Neural2-A",  "name": "UK Neural2-A",  "gender": "F", "desc": "British female, warm"},
            {"id": "en-AU-Neural2-A",  "name": "AU Neural2-A",  "gender": "F", "desc": "Australian female"},
        ],
        "default_voice": "en-US-Journey-D",
        "models": [
            {"id": "journey",  "name": "Journey",  "desc": "Most natural (free tier)"},
            {"id": "neural2",  "name": "Neural2",  "desc": "Natural voices (free tier)"},
            {"id": "standard", "name": "Standard", "desc": "Basic quality (free tier)"},
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
            {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam",      "gender": "M", "desc": "Deep, authoritative narrator"},
            {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni",    "gender": "M", "desc": "Well-rounded storyteller"},
            {"id": "VR6AewLTigWG4xSOukaG", "name": "Arnold",    "gender": "M", "desc": "Crisp, confident"},
            {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh",      "gender": "M", "desc": "Dynamic, energetic narrator"},
            {"id": "yoZ06aMxZJJ28mfd3POQ", "name": "Sam",       "gender": "M", "desc": "Raspy, gritty voice"},
            {"id": "nPczCjzI2devNBz1zQrb", "name": "Brian",     "gender": "M", "desc": "Deep American, warm"},
            {"id": "onwK4e9ZLuTAKqWW03F9", "name": "Daniel",    "gender": "M", "desc": "Deep British narrator"},
            {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel",    "gender": "F", "desc": "Calm, professional narrator"},
            {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi",      "gender": "F", "desc": "Strong, powerful storyteller"},
            {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella",     "gender": "F", "desc": "Soft, intimate narrator"},
            {"id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli",      "gender": "F", "desc": "Emotional, expressive voice"},
            {"id": "XB0fDUnXU5powFXDhCwa", "name": "Charlotte", "gender": "F", "desc": "British female, measured"},
            {"id": "oWAxZDx7w5VEj9dCyTzz", "name": "Grace",     "gender": "F", "desc": "Southern US, warm & inviting"},
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
    # Determine language code from voice name
    lang = "-".join(voice_name.split("-")[:2]) if voice_name else "en-US"
    for chunk in chunks:
        payload = json.dumps({
            "input":       {"text": chunk},
            "voice":       {"languageCode": lang, "name": voice_name},
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
                       model_id: str = "eleven_multilingual_v2",
                       stability: float = 0.50,
                       style: float = 0.25) -> bytes:
    """ElevenLabs text-to-speech via REST API.

    stability: 0.0–1.0. 0.40–0.55 recommended for story narration (emotional range).
    style:     0.0–1.0. 0.10–0.50 for drama; 0 = neutral.
    """
    import json, urllib.request
    chunks = _split_text(text, 2500)
    parts: list[bytes] = []
    for chunk in chunks:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = json.dumps({
            "text":     chunk,
            "model_id": model_id,
            "voice_settings": {
                "stability":        max(0.0, min(1.0, stability)),
                "similarity_boost": 0.75,
                "style":            max(0.0, min(1.0, style)),
                "use_speaker_boost": True,
            },
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
            voice: str = "", model: str = "",
            stability: float = 0.50, style: float = 0.25) -> bytes:
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
        return narrate_elevenlabs(text, api_key, voice_id=v, model_id=m,
                                  stability=stability, style=style)
    raise ValueError(f"Unimplemented provider: {provider_id!r}")


def cost_estimate(provider_id: str, text: str) -> float:
    return _cost_estimate(text, provider_id)


# ── Voice preview (cached short clip) ─────────────────────────────────────────
def generate_preview(
    provider_id: str,
    voice_id: str,
    model_id: str,
    api_key: str,
    cache_dir: str,
) -> bytes:
    """Generate (or return cached) a short voice preview clip as MP3 bytes."""
    safe = _re.sub(r'[^\w]', '_', voice_id)[:48]
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{provider_id}_{safe}.mp3")
    if os.path.isfile(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()
    audio = narrate(provider_id, VOICE_PREVIEW_TEXT, api_key,
                    voice=voice_id, model=model_id or "")
    with open(cache_path, "wb") as f:
        f.write(audio)
    return audio
