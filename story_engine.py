"""
story_engine.py — AI story generation engine for Story Teller.

Supports Anthropic Claude, OpenAI GPT, and Google Gemini.
Each provider is imported lazily — if a package is not installed, a
RuntimeError with install instructions is raised only at generation time.
"""
from __future__ import annotations
from typing import Generator

# ── Genre catalogue ─────────────────────────────────────────────────────────────
# Each genre defines its display properties, narration defaults, and the
# genre-specific guidance injected into the AI system prompt.
GENRES: list[dict] = [
    {
        "slug": "horror",
        "name": "Horror",
        "icon": "moon-stars-fill",
        "color": "#dc3545",
        "description": "Dark, suspenseful tales of fear and dread",
        "age_rating": "PG-13",
        "default_words": 6000,
        "word_min": 4500,
        "word_max": 9000,
        "default_narrative": "third",
        "default_tone": "dark",
        "hint": (
            "Create atmospheric, psychologically terrifying horror. Build dread slowly. "
            "Avoid gratuitous gore — psychological horror is far more effective. "
            "End with a chilling revelation or lingering unease that haunts the listener."
        ),
    },
    {
        "slug": "fantasy",
        "name": "Fantasy",
        "icon": "stars",
        "color": "#6f42c1",
        "description": "Epic tales of magic, heroes, and mythical worlds",
        "age_rating": "All Ages",
        "default_words": 7000,
        "word_min": 5000,
        "word_max": 9000,
        "default_narrative": "third",
        "default_tone": "neutral",
        "hint": (
            "Build a rich world with consistent rules for magic and society. "
            "Include a clear hero's journey or quest arc. Vivid descriptions of "
            "fantastical locations and creatures that paint a clear visual image."
        ),
    },
    {
        "slug": "scifi",
        "name": "Sci-Fi / HFY",
        "icon": "rocket-fill",
        "color": "#0dcaf0",
        "description": "Humanity's triumph in the cosmos — the HFY tradition",
        "age_rating": "All Ages",
        "default_words": 7000,
        "word_min": 5000,
        "word_max": 9000,
        "default_narrative": "third",
        "default_tone": "uplifting",
        "hint": (
            "Write in the HFY (Humanity, F*** Yeah) tradition — stories where humans prove "
            "their unique worth to alien civilizations through ingenuity, resilience, "
            "compassion, or sheer stubbornness. Explore what makes humans remarkable "
            "from an outside perspective. Grand scale, powerful emotional payoff."
        ),
    },
    {
        "slug": "romance",
        "name": "Romance",
        "icon": "heart-fill",
        "color": "#e83e8c",
        "description": "Heartfelt stories of love, longing, and connection",
        "age_rating": "PG-13",
        "default_words": 6000,
        "word_min": 4000,
        "word_max": 8000,
        "default_narrative": "first",
        "default_tone": "uplifting",
        "hint": (
            "Focus on emotional depth and character chemistry above all. Build tension through "
            "misunderstandings, circumstances, and personal growth. Give each character "
            "a distinct, compelling voice. Resolution must be emotionally satisfying."
        ),
    },
    {
        "slug": "mystery",
        "name": "Mystery",
        "icon": "search",
        "color": "#fd7e14",
        "description": "Intricate whodunits, detective tales, and clever puzzles",
        "age_rating": "PG-13",
        "default_words": 6000,
        "word_min": 4500,
        "word_max": 8000,
        "default_narrative": "first",
        "default_tone": "neutral",
        "hint": (
            "Plant clues fairly — the listener should be able to solve it in retrospect. "
            "Build a compelling detective or amateur sleuth protagonist. Red herrings must "
            "be fair. Resolution follows logically from established facts. Satisfying click."
        ),
    },
    {
        "slug": "childrens",
        "name": "Children's",
        "icon": "balloon-fill",
        "color": "#198754",
        "description": "Joyful tales with moral lessons for young listeners",
        "age_rating": "All Ages",
        "default_words": 3000,
        "word_min": 1500,
        "word_max": 5000,
        "default_narrative": "third",
        "default_tone": "uplifting",
        "hint": (
            "Simple, clear language appropriate for children aged 4-10. Deliver a clear "
            "moral lesson organically through the story — never preachy. Colorful, vivid "
            "characters. Repetition and rhythm aid narration. Avoid all adult themes entirely."
        ),
    },
    {
        "slug": "bedtime",
        "name": "Bedtime",
        "icon": "moon-fill",
        "color": "#6ea8fe",
        "description": "Calm, soothing stories perfect for winding down",
        "age_rating": "All Ages",
        "default_words": 4000,
        "word_min": 2000,
        "word_max": 6000,
        "default_narrative": "third",
        "default_tone": "uplifting",
        "hint": (
            "Gentle, peaceful pacing throughout. Soothing imagery — nature, soft candlelight, "
            "warmth. Avoid all conflict or tension. Characters feel safe and content. "
            "Language should be rhythmic and gently hypnotic. "
            "The listener should feel calm and drowsy by the final paragraphs."
        ),
    },
    {
        "slug": "thriller",
        "name": "Thriller",
        "icon": "lightning-fill",
        "color": "#ffc107",
        "description": "High-stakes, fast-paced suspense that keeps you hooked",
        "age_rating": "PG-13",
        "default_words": 6000,
        "word_min": 4500,
        "word_max": 8000,
        "default_narrative": "first",
        "default_tone": "dark",
        "hint": (
            "Fast pacing, short punchy sentences in tense moments. High stakes — "
            "protagonist faces genuine danger or an impossible choice. Multiple plot twists "
            "that reframe everything. Exhausting but satisfying resolution. "
            "The listener must feel they cannot stop listening."
        ),
    },
    {
        "slug": "comedy",
        "name": "Comedy",
        "icon": "emoji-laughing-fill",
        "color": "#20c997",
        "description": "Lighthearted, funny stories to brighten any day",
        "age_rating": "All Ages",
        "default_words": 4000,
        "word_min": 2000,
        "word_max": 6000,
        "default_narrative": "first",
        "default_tone": "uplifting",
        "hint": (
            "Timing is everything — build to escalating absurdity. Characters react "
            "with exaggerated but totally relatable emotions. Self-deprecating humor "
            "works beautifully for audio narration. Leave the audience genuinely smiling "
            "and wanting more."
        ),
    },
    {
        "slug": "christian",
        "name": "Christian / Bible",
        "icon": "book-fill",
        "color": "#ffd700",
        "description": "Faith-based stories rooted in scripture and Christian values",
        "age_rating": "All Ages",
        "default_words": 5000,
        "word_min": 2500,
        "word_max": 8000,
        "default_narrative": "third",
        "default_tone": "uplifting",
        "hint": (
            "Draw from biblical themes, parables, and Christian values. Stories must be "
            "spiritually uplifting and faith-affirming. Weave relevant scripture references "
            "in naturally — never forced. Characters face moral challenges and find resolution "
            "through faith, prayer, forgiveness, or Christian community. "
            "Suitable for all ages including young families."
        ),
    },
]

GENRES_BY_SLUG: dict[str, dict] = {g["slug"]: g for g in GENRES}


# ── AI provider catalogue (with pricing) ────────────────────────────────────────
# cost_per_1k_words is the approximate output cost per 1,000 output words.
# Input cost is ~20% of output for story generation (short prompt, long output).
PROVIDERS: list[dict] = [
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "icon": "cpu",
        "setting_key": "anthropic_api_key",
        "models": [
            {
                "id": "claude-sonnet-4-6",
                "name": "Claude Sonnet 4.6",
                "label": "Recommended — best story quality",
                "cost_per_1k_words": 0.046,   # ~$3/M output tokens × 1.3 tok/word
                "cost_note": "~$0.046 per 1,000 words generated",
            },
            {
                "id": "claude-haiku-4-5-20251001",
                "name": "Claude Haiku 4.5",
                "label": "Fast & affordable",
                "cost_per_1k_words": 0.005,
                "cost_note": "~$0.005 per 1,000 words generated",
            },
            {
                "id": "claude-opus-4-8",
                "name": "Claude Opus 4.8",
                "label": "Maximum quality",
                "cost_per_1k_words": 0.195,
                "cost_note": "~$0.195 per 1,000 words generated",
            },
        ],
        "default_model": "claude-sonnet-4-6",
    },
    {
        "id": "openai",
        "name": "OpenAI GPT",
        "icon": "stars",
        "setting_key": "openai_api_key",
        "models": [
            {
                "id": "gpt-4o",
                "name": "GPT-4o",
                "label": "Recommended",
                "cost_per_1k_words": 0.013,
                "cost_note": "~$0.013 per 1,000 words generated",
            },
            {
                "id": "gpt-4o-mini",
                "name": "GPT-4o Mini",
                "label": "Fast & cheap",
                "cost_per_1k_words": 0.0002,
                "cost_note": "~$0.0002 per 1,000 words generated",
            },
            {
                "id": "gpt-4-turbo",
                "name": "GPT-4 Turbo",
                "label": "High quality",
                "cost_per_1k_words": 0.039,
                "cost_note": "~$0.039 per 1,000 words generated",
            },
        ],
        "default_model": "gpt-4o",
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "icon": "google",
        "setting_key": "gemini_api_key",
        "models": [
            {
                "id": "gemini-2.0-flash",
                "name": "Gemini 2.0 Flash",
                "label": "Recommended — fast & affordable",
                "cost_per_1k_words": 0.0015,
                "cost_note": "~$0.0015 per 1,000 words generated",
            },
            {
                "id": "gemini-1.5-pro",
                "name": "Gemini 1.5 Pro",
                "label": "Higher quality",
                "cost_per_1k_words": 0.0132,
                "cost_note": "~$0.013 per 1,000 words generated",
            },
            {
                "id": "gemini-2.0-flash-lite",
                "name": "Gemini 2.0 Flash Lite",
                "label": "Lowest cost",
                "cost_per_1k_words": 0.00004,
                "cost_note": "~$0.00004 per 1,000 words — near-free",
            },
        ],
        "default_model": "gemini-2.0-flash",
    },
]

PROVIDERS_BY_ID: dict[str, dict] = {p["id"]: p for p in PROVIDERS}


# ── Voice provider catalogue (Phase 2 — costs shown in UI now) ─────────────────
VOICE_PROVIDERS: list[dict] = [
    {
        "id": "openai_tts",
        "name": "OpenAI TTS",
        "label": "Recommended — best emotional range",
        "cost_per_1k_words": 0.015,
        "cost_note": "~$0.015 per 1,000 words (~$0.09 per 6,000-word story)",
        "voices": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
        "gender_note": "Male: onyx, echo, fable — Female: nova, shimmer, alloy",
        "available": False,  # Phase 2
    },
    {
        "id": "elevenlabs",
        "name": "ElevenLabs",
        "label": "Highest realism — signature character voices",
        "cost_per_1k_words": 0.033,
        "cost_note": "~$0.033 per 1,000 words (~$0.20 per 6,000-word story) + $22/mo plan",
        "voices": ["Rachel", "Domi", "Bella", "Antoni", "Elli", "Josh", "Arnold", "Adam", "Sam"],
        "gender_note": "Multiple voices available — clone your own",
        "available": False,  # Phase 2
    },
    {
        "id": "google_tts",
        "name": "Google TTS",
        "label": "Free tier available",
        "cost_per_1k_words": 0.000,
        "cost_note": "Free up to 1M characters/month (~100 stories) — then $0.004/1k chars",
        "voices": ["en-US-Standard-A", "en-US-Standard-B", "en-US-Neural2-A"],
        "gender_note": "Standard (robotic) and Neural2 (natural) voices",
        "available": False,  # Phase 2
    },
]


# ── Video intro catalogue (Phase 3 — costs shown in UI now) ───────────────────
INTRO_PROVIDERS: list[dict] = [
    {
        "id": "ltx2",
        "name": "LTX-2 API",
        "label": "Recommended — cinematic 5-sec image-to-video",
        "cost_per_clip": 0.30,
        "cost_note": "~$0.30 per 5-second clip at 1080p (Fast model)",
        "available": False,  # Phase 3
    },
    {
        "id": "runway",
        "name": "RunwayML Gen-3",
        "label": "High quality — cloud video generation",
        "cost_per_clip": 0.50,
        "cost_note": "~$0.50 per 5-second clip",
        "available": False,  # Phase 3
    },
    {
        "id": "title_card",
        "name": "Animated Title Card",
        "label": "Free — logo + title animation via ffmpeg",
        "cost_per_clip": 0.00,
        "cost_note": "Free — no AI video generation needed",
        "available": False,  # Phase 3
    },
]


# ── Image generation catalogue (Phase 2 — costs shown in UI now) ──────────────
IMAGE_PROVIDERS: list[dict] = [
    {
        "id": "dalle3",
        "name": "DALL-E 3",
        "label": "Recommended — best prompt adherence",
        "cost_per_image": 0.040,
        "cost_note": "~$0.040 per 1024×1024 image",
        "available": False,  # Phase 2
    },
    {
        "id": "stability",
        "name": "Stability AI",
        "label": "Good quality — affordable",
        "cost_per_image": 0.020,
        "cost_note": "~$0.020 per image (Stable Image Core)",
        "available": False,  # Phase 2
    },
    {
        "id": "ideogram",
        "name": "Ideogram",
        "label": "Best text-in-image — great for thumbnails",
        "cost_per_image": 0.080,
        "cost_note": "~$0.080 per image",
        "available": False,  # Phase 2
    },
]


# ── Prompt builder ─────────────────────────────────────────────────────────────
def build_prompt(genre_slug: str, params: dict) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the chosen genre and parameters."""
    genre = GENRES_BY_SLUG.get(genre_slug, GENRES[0])

    word_count = int(params.get("word_count", genre["default_words"]))
    narrative  = params.get("narrative", genre["default_narrative"])
    tone       = params.get("tone", genre["default_tone"])
    age_rating = params.get("age_rating", genre["age_rating"])
    characters = int(params.get("characters", 2))
    setting    = params.get("setting", "").strip()
    plot_hook  = params.get("plot_hook", "").strip()
    minutes    = round(word_count / 140)

    narr_label = {
        "first":      "first-person (I/me/my)",
        "third":      "third-person (he/she/they)",
        "omniscient": "omniscient third-person narrator",
    }.get(narrative, "third-person")

    tone_label = {
        "dark":     "dark and atmospheric",
        "neutral":  "balanced and engaging",
        "uplifting":"uplifting and hopeful",
    }.get(tone, "engaging")

    system = (
        f"You are a master storyteller creating {genre['name']} stories for a YouTube narration "
        f"channel in the style of HFY Cinema — an immersive audio experience where a narrator "
        f"reads the story while a single atmospheric background image is displayed with closed captions.\n\n"
        f"NARRATION FORMAT:\n"
        f"- The story is read aloud by an AI narrator voice over a static background image\n"
        f"- Write for spoken narration: natural rhythm, varied sentence length, clear to pronounce\n"
        f"- Avoid symbols, abbreviations, or formatting that doesn't translate to audio\n"
        f"- Do not use markdown headers, bullet points, or asterisks — plain prose only\n"
        f"- Separate scenes/chapters with a blank line; do not use '***' or '---' dividers\n\n"
        f"STORY PARAMETERS:\n"
        f"- Genre: {genre['name']}\n"
        f"- Narrative voice: {narr_label}\n"
        f"- Overall tone: {tone_label}\n"
        f"- Age rating: {age_rating}\n"
        f"- Main characters: {characters}\n"
        f"- Target length: ~{word_count:,} words (~{minutes} minutes of narration at 140 wpm)\n\n"
        f"GENRE GUIDANCE:\n"
        f"{genre['hint']}\n\n"
        f"STORY STRUCTURE:\n"
        f"- Open with a powerful hook — the first paragraph must grip the listener immediately\n"
        f"- Build naturally through rising action to a clear climax\n"
        f"- End memorably — the final line should linger with the listener\n"
        f"- Every scene must serve the story — no padding to hit the word count\n\n"
        f"YOUTUBE COMPLIANCE:\n"
        f"- Content must meet YouTube monetization guidelines\n"
        f"- No explicit sexual content, no gratuitous gore, no hate speech\n"
        f"- All content must be original — no reproduction of copyrighted text\n"
        f"- AI-generated label will be applied automatically — no disclosure needed in the story\n"
    )

    user_parts = [
        f"Write a complete, original {genre['name']} story of approximately {word_count:,} words.",
    ]
    if setting:
        user_parts.append(f"Setting: {setting}")
    else:
        user_parts.append("Create a vivid, original setting appropriate to the genre.")
    if plot_hook:
        user_parts.append(f"Story concept / opening premise: {plot_hook}")
    else:
        user_parts.append("Devise a compelling and original premise.")
    user_parts.append(
        "Begin the story immediately with the first word of the narrative. "
        "Do not include a title, word count, preamble, or any commentary — "
        "just the story itself, ready to be read aloud."
    )
    return system, "\n\n".join(user_parts)


# ── Streaming generation ────────────────────────────────────────────────────────
def stream_story(
    provider_id: str,
    model_id: str,
    genre_slug: str,
    params: dict,
    api_key: str,
) -> Generator[str, None, None]:
    """Yield story text chunks from the chosen AI provider."""
    system, user = build_prompt(genre_slug, params)
    word_count = int(params.get("word_count", 6000))
    max_tokens = min(int(word_count * 1.5), 14000)

    if provider_id == "anthropic":
        yield from _anthropic(api_key, model_id, system, user, max_tokens)
    elif provider_id == "openai":
        yield from _openai(api_key, model_id, system, user, max_tokens)
    elif provider_id == "gemini":
        yield from _gemini(api_key, model_id, system, user, max_tokens)
    else:
        raise ValueError(f"Unknown provider: {provider_id!r}")


def _anthropic(api_key: str, model: str, system: str,
               user: str, max_tokens: int) -> Generator[str, None, None]:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("Run: pip install anthropic")
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as s:
        for text in s.text_stream:
            yield text


def _openai(api_key: str, model: str, system: str,
            user: str, max_tokens: int) -> Generator[str, None, None]:
    try:
        import openai as _oa
    except ImportError:
        raise RuntimeError("Run: pip install openai")
    client = _oa.OpenAI(api_key=api_key)
    stream = client.chat.completions.create(
        model=model,
        max_tokens=min(max_tokens, 12000),
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user}],
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


def _gemini(api_key: str, model: str, system: str,
            user: str, max_tokens: int) -> Generator[str, None, None]:
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("Run: pip install google-generativeai")
    genai.configure(api_key=api_key)
    gm = genai.GenerativeModel(
        model_name=model,
        system_instruction=system,
        generation_config=genai.GenerationConfig(
            max_output_tokens=min(max_tokens, 12000),
        ),
    )
    for chunk in gm.generate_content(user, stream=True):
        if hasattr(chunk, "text") and chunk.text:
            yield chunk.text
