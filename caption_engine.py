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

# ── SRT from Whisper (segment-level) ───────────────────────────────────────────
def transcribe_to_srt(audio_path: str, api_key: str,
                      language: str = "en") -> str:
    """Segment-level Whisper transcription → SRT string."""
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


# ── SRT + word data from Whisper (word-level, needed for karaoke) ──────────────
def transcribe_to_word_srt(audio_path: str, api_key: str,
                           language: str = "en") -> tuple[str, list[dict]]:
    """Word-level Whisper transcription.
    Returns (srt_text, word_data) where word_data = [{word, start, end}].
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["segment", "word"],
        )
    words = [{"word": w.word, "start": w.start, "end": w.end}
             for w in (transcript.words or [])]
    srt = _segments_to_srt(transcript.segments or [])
    return srt, words


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


# ── ASS karaoke generator ─────────────────────────────────────────────────────
_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Arial,28,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,4,2,0,2,30,30,35,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def word_data_to_ass(word_data: list[dict]) -> str:
    """Convert Whisper word data to ASS karaoke format.

    Groups words into lines of ≤7 words. Each word tagged with {\\kf<cs>}
    so ffmpeg highlights it as it's spoken (SecondaryColour = cyan).
    """
    if not word_data:
        return ""
    MAX_PER_LINE = 7
    dialogue_lines: list[str] = []
    i = 0
    while i < len(word_data):
        group = word_data[i:i + MAX_PER_LINE]
        i += MAX_PER_LINE
        line_start = group[0]["start"]
        line_end   = group[-1]["end"]
        parts: list[str] = []
        for j, w in enumerate(group):
            if j < len(group) - 1:
                # Highlight until next word starts
                dur_s = group[j + 1]["start"] - w["start"]
            else:
                dur_s = w["end"] - w["start"]
            cs = max(1, int(dur_s * 100))
            parts.append(f"{{\\kf{cs}}}{w['word'].strip()}")
        line_text = " ".join(parts)
        s = _fmt_ts_ass(line_start)
        e = _fmt_ts_ass(line_end)
        dialogue_lines.append(f"Dialogue: 0,{s},{e},Karaoke,,0,0,0,,{line_text}")
    return _ASS_HEADER + "\n".join(dialogue_lines) + "\n"


def _fmt_ts_ass(seconds: float) -> str:
    """H:MM:SS.cc timestamp for ASS format."""
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = seconds % 60
    cs = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


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
    ass_path: str | None = None,
    burn_captions: bool = True,
    caption_style: str = "standard",   # "standard" | "karaoke" | "none"
    music_path: str | None = None,
    music_volume: float = 0.08,
) -> tuple[str, int]:
    """Build final MP4: scene image + narration + optional captions + optional music.

    caption_style:
      "standard" — burn SRT with white-on-dark-bar style (uses srt_path)
      "karaoke"  — burn ASS karaoke word-highlight file (uses ass_path)
      "none"     — no burned captions
    """
    inputs = ["-loop", "1", "-i", image_path, "-i", audio_path]
    filter_parts: list[str] = []

    if music_path and os.path.isfile(music_path):
        inputs += ["-i", music_path]
        filter_parts.append(
            f"[1:a]volume=1.0[narr];"
            f"[2:a]volume={music_volume}[music];"
            f"[narr][music]amix=inputs=2:duration=first[aout]"
        )
    else:
        filter_parts.append("[1:a]volume=1.0[aout]")

    scale_pad = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    )

    use_ass = (caption_style == "karaoke" and ass_path and
               burn_captions and os.path.isfile(ass_path))
    use_srt = (caption_style == "standard" and srt_path and
               burn_captions and os.path.isfile(srt_path))

    if use_ass:
        ass_esc = ass_path.replace("\\", "/").replace(":", "\\:")
        filter_parts.append(
            f"[0:v]{scale_pad},ass='{ass_esc}'[vout]"
        )
    elif use_srt:
        srt_esc = srt_path.replace("\\", "/").replace(":", "\\:")
        filter_parts.append(
            f"[0:v]{scale_pad},"
            f"subtitles='{srt_esc}':force_style='"
            f"FontName=Arial,FontSize=22,PrimaryColour=&HFFFFFF,"
            f"OutlineColour=&H000000,Outline=2,BorderStyle=4,"
            f"BackColour=&H80000000,Alignment=2,MarginV=30'[vout]"
        )
    else:
        filter_parts.append(f"[0:v]{scale_pad}[vout]")

    cmd = [
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[vout]", "-map", "[aout]",
        "-shortest",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    return _ffmpeg(*cmd, timeout=600)


def build_intro_clip(
    image_path: str,
    audio_path: str,
    title_text: str,
    output_path: str,
) -> tuple[str, int]:
    """Build a short intro clip: scene image + teaser audio + centered title overlay.

    Duration is determined by the teaser audio length (-shortest).
    Title is drawn white-on-translucent-black box, centered vertically and horizontally.
    """
    # Escape special chars for ffmpeg drawtext
    safe_title = (title_text.replace("\\", "\\\\")
                             .replace("'", "\\'")
                             .replace(":", "\\:")
                             .replace("%", "\\%"))

    vf = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
        f"drawtext=text='{safe_title}'"
        ":fontfile=/Windows/Fonts/arialbd.ttf"
        ":fontcolor=white:fontsize=80"
        ":x=(w-text_w)/2:y=(h-text_h)/2"
        ":box=1:boxcolor=black@0.55:boxborderw=30"
        ":shadowcolor=black:shadowx=4:shadowy=4"
    )

    cmd = [
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-filter_complex", f"[0:v]{vf}[vout];[1:a]volume=1.0[aout]",
        "-map", "[vout]", "-map", "[aout]",
        "-shortest",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    log, rc = _ffmpeg(*cmd, timeout=120)
    if rc != 0 and "arialbd.ttf" in log:
        # Fallback: no fontfile spec (uses ffmpeg default font)
        vf_fallback = vf.replace(":fontfile=/Windows/Fonts/arialbd.ttf", "")
        cmd2 = [
            "-loop", "1", "-i", image_path,
            "-i", audio_path,
            "-filter_complex", f"[0:v]{vf_fallback}[vout];[1:a]volume=1.0[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-shortest",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ]
        log, rc = _ffmpeg(*cmd2, timeout=120)
    return log, rc


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
