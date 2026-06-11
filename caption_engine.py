"""
caption_engine.py — Story Teller Phase 4
Closed caption (SRT) generation via OpenAI Whisper transcription of the
narration audio. Also includes the ffmpeg video assembly pipeline.
"""
from __future__ import annotations
import io
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

# ── SRT from Whisper ───────────────────────────────────────────────────────────
def transcribe_to_srt(audio_path: str, api_key: str,
                      language: str = "en") -> str:
    """
    Send audio file to OpenAI Whisper and return SRT-formatted captions.
    Cost: ~$0.006/min of audio (≈$0.006/story for a 6k-word narration).
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    return _segments_to_srt(transcript.segments or [])


def _segments_to_srt(segments: list) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _fmt_ts(seg.get("start", 0))
        end   = _fmt_ts(seg.get("end",   0))
        text  = (seg.get("text") or "").strip()
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── SRT from word-timing (OpenAI TTS with timestamps) ─────────────────────────
def text_to_srt(text: str, words_per_minute: int = 140) -> str:
    """
    Estimate SRT timing from plain text at ~140 words/minute.
    Cheap approximation when whisper transcription isn't needed.
    """
    import re as _re
    sentences = _re.split(r'(?<=[.!?])\s+', text.strip())
    srt, t = [], 0.0
    for i, sent in enumerate(sentences, 1):
        words  = len(sent.split())
        dur    = max(1.5, (words / words_per_minute) * 60)
        start  = _fmt_ts(t)
        end    = _fmt_ts(t + dur)
        srt.append(f"{i}\n{start} --> {end}\n{sent}\n")
        t += dur
    return "\n".join(srt)


# ── ffmpeg helpers ─────────────────────────────────────────────────────────────
_CREATE_NO_WINDOW = 0x08000000

def _ffmpeg(*args: str, timeout: int = 300) -> tuple[str, int]:
    import platform
    cf = _CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", *args],
            capture_output=True, text=True,
            timeout=timeout, creationflags=cf,
        )
        return (r.stdout + r.stderr).strip(), r.returncode
    except FileNotFoundError:
        return "ffmpeg not found — install it from https://ffmpeg.org/", 1
    except Exception as exc:
        return str(exc), 1


def ffmpeg_available() -> bool:
    _, rc = _ffmpeg("-version", timeout=5)
    return rc == 0


def assemble_video(
    image_path: str,
    audio_path: str,
    output_path: str,
    srt_path: str | None = None,
    burn_captions: bool = True,
    music_path: str | None = None,
    music_volume: float = 0.08,
    intro_clip_path: str | None = None,
) -> tuple[str, int]:
    """
    Build final MP4 from components using ffmpeg:
      1. (Optional) Prepend intro_clip (5-sec animation)
      2. Freeze scene image as video background for the audio duration
      3. Mix narration + optional background music
      4. Burn in SRT captions if provided
    Returns (log_output, returncode).
    """
    # Build the filter graph
    # Input 0: scene image (loop for audio duration)
    # Input 1: narration audio
    # Input 2 (optional): background music
    inputs = ["-loop", "1", "-i", image_path, "-i", audio_path]
    filter_parts = []
    audio_map = "[aout]"

    if music_path and os.path.isfile(music_path):
        inputs += ["-i", music_path]
        # Mix narration (full volume) with music (low volume)
        filter_parts.append(
            f"[1:a]volume=1.0[narr];"
            f"[2:a]volume={music_volume}[music];"
            f"[narr][music]amix=inputs=2:duration=first[aout]"
        )
    else:
        filter_parts.append("[1:a]volume=1.0[aout]")

    if srt_path and burn_captions and os.path.isfile(srt_path):
        srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")
        filter_parts.append(
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
            f"subtitles='{srt_escaped}':force_style='FontName=Arial,"
            f"FontSize=18,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
            f"Outline=2,Alignment=2'[vout]"
        )
    else:
        filter_parts.append(
            "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2[vout]"
        )

    filter_complex = ";".join(filter_parts)

    cmd = [
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", audio_map,
        "-shortest",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    return _ffmpeg(*cmd, timeout=600)


def prepend_intro(intro_path: str, main_path: str, output_path: str) -> tuple[str, int]:
    """Concatenate intro clip + main video using ffmpeg concat demuxer."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(f"file '{intro_path}'\nfile '{main_path}'\n")
        concat_file = f.name
    try:
        return _ffmpeg(
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-c", "copy", output_path, timeout=300,
        )
    finally:
        try:
            os.unlink(concat_file)
        except Exception:
            pass
