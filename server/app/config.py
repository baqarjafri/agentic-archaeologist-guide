"""Settings from environment variables (a local .env file is loaded by uvicorn --env-file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
TRUE_WORDS = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class Settings:
    pack_dir: Path
    model_path: Path
    web_dist: Path
    access_codes: frozenset[str] = field(repr=False)
    llm_base_url: str
    llm_api_key: str = field(repr=False)
    llm_model: str
    llm_reasoning_effort: str | None
    tts_provider: str
    gemini_api_key: str = field(repr=False)
    gemini_tts_model: str
    gemini_tts_voice: str
    gemini_tts_fallbacks: tuple[str, ...]
    gemini_tts_per_minute: int
    elevenlabs_api_key: str = field(repr=False)
    elevenlabs_voice_id: str
    elevenlabs_model: str
    respell_names: bool
    strict_citations: bool
    demo_dir: Path | None = None  # laptop demos only: prepared gallery footage served at /demo-media


def _value(e: dict[str, str], key: str, default: str) -> str:
    """An unset or blank variable means the default, so `KEY=` never switches a setting to an empty value."""
    return e.get(key, "").strip() or default


def _flag(e: dict[str, str], key: str) -> bool:
    return e.get(key, "").strip().lower() in TRUE_WORDS


def load_settings(env: dict[str, str] | None = None) -> Settings:
    e = dict(os.environ if env is None else env)
    gemini_key = _value(e, "GEMINI_API_KEY", "")
    effort = e.get("LLM_REASONING_EFFORT", "minimal").strip()  # blank turns it off, for providers that reject it
    demo = e.get("DEMO_DIR", "").strip()
    return Settings(
        pack_dir=Path(_value(e, "PACK_DIR", str(SERVER_DIR.parent / "packs" / "burrell-pilot"))),
        model_path=Path(_value(e, "MODEL_PATH", str(SERVER_DIR / "models" / "dinov2-small-int8.onnx"))),
        web_dist=Path(_value(e, "WEB_DIST", str(SERVER_DIR.parent / "web" / "dist"))),
        access_codes=frozenset(c.strip() for c in e.get("ACCESS_CODES", "").split(",") if c.strip()),
        llm_base_url=_value(e, "LLM_BASE_URL", GEMINI_OPENAI_URL),
        llm_api_key=_value(e, "LLM_API_KEY", gemini_key),
        llm_model=_value(e, "LLM_MODEL", "gemini-3.5-flash-lite"),
        llm_reasoning_effort=effort or None,
        tts_provider=_value(e, "TTS_PROVIDER", "gemini"),
        gemini_api_key=gemini_key,
        gemini_tts_model=_value(e, "GEMINI_TTS_MODEL", "gemini-3.8-flash-lite-tts"),  # the fastest first audio measured, 0.66 s
        gemini_tts_voice=_value(e, "GEMINI_TTS_VOICE", "Sulafat"),
        gemini_tts_fallbacks=tuple(m.strip() for m in _value(
            e, "GEMINI_TTS_FALLBACKS", "gemini-3.8-flash-tts,gemini-3.1-flash-tts-preview,gemini-2.5-flash-preview-tts",
        ).split(",") if m.strip()),  # voice models tried in turn when one has used its per-minute quota
        gemini_tts_per_minute=int(_value(e, "GEMINI_TTS_PER_MINUTE", "10")),  # Gemini allows 10 voice requests a minute per model
        elevenlabs_api_key=_value(e, "ELEVENLABS_API_KEY", ""),
        elevenlabs_voice_id=_value(e, "ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb"),
        elevenlabs_model=_value(e, "ELEVENLABS_MODEL", "eleven_flash_v2_5"),
        respell_names=_flag(e, "RESPELL_NAMES"),
        strict_citations=_flag(e, "STRICT_CITATIONS"),
        demo_dir=Path(demo) if demo else None,
    )
