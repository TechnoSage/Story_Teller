"""
image_engine.py — Story Teller Phase 3
Scene image generation via DALL-E 3, Stability AI, and Ideogram.
Returns raw image bytes (PNG or JPEG) so the caller can save or serve directly.
"""
from __future__ import annotations
import base64
import io
import json
import os
import urllib.request
import urllib.parse

# ── Image provider catalogue ───────────────────────────────────────────────────
IMAGE_PROVIDERS = [
    {
        "id":          "dalle3",
        "name":        "DALL-E 3",
        "icon":        "robot",
        "setting_key": "openai_api_key",
        "cost_note":   "$0.040 / image (1024×1024)",
        "cost":        0.040,
        "sizes": [
            {"id": "1024x1024", "name": "Square (1024×1024)"},
            {"id": "1792x1024", "name": "Landscape (1792×1024) — YouTube thumb"},
            {"id": "1024x1792", "name": "Portrait (1024×1792)"},
        ],
        "default_size": "1792x1024",
        "qualities": [
            {"id": "standard", "name": "Standard"},
            {"id": "hd",       "name": "HD"},
        ],
        "default_quality": "hd",
    },
    {
        "id":          "stability",
        "name":        "Stability AI",
        "icon":        "stars",
        "setting_key": "stability_api_key",
        "cost_note":   "$0.020 / image",
        "cost":        0.020,
        "sizes": [
            {"id": "1024x1024", "name": "Square (1024×1024)"},
            {"id": "1344x768",  "name": "Landscape (1344×768)"},
            {"id": "768x1344",  "name": "Portrait (768×1344)"},
        ],
        "default_size": "1344x768",
        "qualities": [
            {"id": "core",   "name": "Core (fast)"},
            {"id": "ultra",  "name": "Ultra (best quality, 2×)"},
        ],
        "default_quality": "core",
    },
    {
        "id":          "ideogram",
        "name":        "Ideogram",
        "icon":        "palette-fill",
        "setting_key": "ideogram_api_key",
        "cost_note":   "$0.080 / image",
        "cost":        0.080,
        "sizes": [
            {"id": "ASPECT_16_9",  "name": "16:9 Landscape — YouTube thumb"},
            {"id": "ASPECT_1_1",   "name": "1:1 Square"},
            {"id": "ASPECT_9_16",  "name": "9:16 Portrait"},
        ],
        "default_size": "ASPECT_16_9",
        "qualities": [
            {"id": "V_2",       "name": "Ideogram v2"},
            {"id": "V_2_TURBO", "name": "v2 Turbo (faster)"},
        ],
        "default_quality": "V_2",
    },
]
IMAGE_PROVIDERS_BY_ID = {p["id"]: p for p in IMAGE_PROVIDERS}


# ── Prompt builder for scene images ───────────────────────────────────────────
def build_image_prompt(genre_slug: str, story_title: str,
                       story_excerpt: str = "", custom_prompt: str = "") -> str:
    """Build a detailed image prompt from story metadata."""
    if custom_prompt:
        return custom_prompt

    # Extract first paragraph as setting context
    excerpt = story_excerpt[:600].strip() if story_excerpt else ""

    genre_styles = {
        "horror":    "dark gothic atmosphere, deep shadows, moonlight, fog, ominous",
        "fantasy":   "epic fantasy landscape, magical light, mountains, ancient architecture",
        "scifi":     "futuristic cityscape, neon lights, space, technology, cinematic",
        "romance":   "warm golden hour light, soft bokeh, flowers, romantic atmosphere",
        "mystery":   "noir atmosphere, moody lighting, shadows, old city, rain",
        "childrens": "bright colorful illustration, friendly characters, soft warm light",
        "bedtime":   "soft pastel colors, dreamy moonlit scene, cozy and peaceful",
        "thriller":  "tense urban environment, dramatic lighting, dark alley, suspense",
        "comedy":    "bright vibrant colors, whimsical exaggerated scene, sunny",
        "christian": "divine golden light, serene biblical landscape, peaceful holy scene",
    }
    style = genre_styles.get(genre_slug, "cinematic atmospheric scene")

    return (
        f"A dramatic atmospheric scene for a YouTube story titled '{story_title}'. "
        f"{style}. "
        f"{'Context: ' + excerpt[:200] + '.' if excerpt else ''} "
        "Cinematic quality, high detail, 4K, perfect for a YouTube video background. "
        "No text, no watermarks, no people faces — just the atmospheric environment."
    )


# ── DALL-E 3 ───────────────────────────────────────────────────────────────────
def generate_dalle3(prompt: str, api_key: str,
                    size: str = "1792x1024", quality: str = "hd") -> bytes:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    resp = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size=size,
        quality=quality,
        response_format="b64_json",
        n=1,
    )
    return base64.b64decode(resp.data[0].b64_json)


# ── Stability AI ───────────────────────────────────────────────────────────────
def generate_stability(prompt: str, api_key: str,
                       size: str = "1344x768", model: str = "core") -> bytes:
    """Stability AI via REST API."""
    w, h = (int(x) for x in size.split("x"))
    endpoint = f"https://api.stability.ai/v2beta/stable-image/generate/{model}"
    import urllib.error
    data = urllib.parse.urlencode({
        "prompt":       prompt,
        "output_format": "png",
        "width":        str(w),
        "height":       str(h),
    }).encode()
    req = urllib.request.Request(
        endpoint, data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept":        "image/*",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


# ── Ideogram ───────────────────────────────────────────────────────────────────
def generate_ideogram(prompt: str, api_key: str,
                      aspect: str = "ASPECT_16_9", model: str = "V_2") -> bytes:
    """Ideogram image generation via REST API."""
    payload = json.dumps({
        "image_request": {
            "prompt":       prompt,
            "aspect_ratio": aspect,
            "model":        model,
            "magic_prompt_option": "AUTO",
        }
    }).encode()
    req = urllib.request.Request(
        "https://api.ideogram.ai/generate",
        data=payload,
        headers={
            "Api-Key":      api_key,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())

    # Download the returned image URL
    img_url = result["data"][0]["url"]
    with urllib.request.urlopen(img_url, timeout=60) as img_resp:
        return img_resp.read()


# ── Unified dispatcher ─────────────────────────────────────────────────────────
def generate(provider_id: str, prompt: str, api_key: str,
             size: str = "", quality: str = "") -> bytes:
    """Dispatch to the correct image provider. Returns raw image bytes."""
    p = IMAGE_PROVIDERS_BY_ID.get(provider_id)
    if not p:
        raise ValueError(f"Unknown image provider: {provider_id!r}")
    s = size    or p["default_size"]
    q = quality or p["default_quality"]
    if provider_id == "dalle3":
        return generate_dalle3(prompt, api_key, size=s, quality=q)
    if provider_id == "stability":
        return generate_stability(prompt, api_key, size=s, model=q)
    if provider_id == "ideogram":
        return generate_ideogram(prompt, api_key, aspect=s, model=q)
    raise ValueError(f"Unimplemented provider: {provider_id!r}")
