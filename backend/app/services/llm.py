"""One way to ask the AI for JSON. DeepSeek first when its key is set, then Groq; both speak the OpenAI chat API,
so plain httpx does it without vendor SDKs. AI routes must be plain `def` (this blocks), never `async def`."""

import logging
import time
from typing import TypeVar

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError

from app.core.config import settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def _providers():
    if settings.DEEPSEEK_API_KEY:
        yield "deepseek", "https://api.deepseek.com/chat/completions", settings.DEEPSEEK_API_KEY, settings.DEEPSEEK_MODEL
    if settings.GROQ_API_KEY:
        yield "groq", "https://api.groq.com/openai/v1/chat/completions", settings.GROQ_API_KEY, settings.AI_MODEL


def _ask(url: str, key: str, model: str, system: str, user: str) -> str:
    body = {
        "model": model,
        "temperature": settings.AI_TEMPERATURE,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"  # its thinking counts against max_tokens; at medium it can leave no answer
    response = httpx.post(url, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=120)
    response.raise_for_status()
    try:
        choice = response.json()["choices"][0]
        content = (choice["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise ValueError(f"unexpected response shape: {e}") from e
    if not content:
        raise ValueError(f"empty answer (finish_reason={choice.get('finish_reason')})")
    start, end = content.find("{"), content.rfind("}")  # drops any code fence or chatter around the object
    if start == -1 or end < start:
        raise ValueError("no JSON object in the answer")
    return content[start:end + 1]


def transcribe(audio: bytes, filename: str, hint: str = "") -> str:
    """Speech to text with Groq Whisper. `hint` (names, task words) helps it spell them; the audio isn't kept."""
    if not settings.GROQ_API_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Voice isn't set up yet: add GROQ_API_KEY to backend/.env.")
    try:
        response = httpx.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            data={"model": settings.WHISPER_MODEL, "prompt": hint[:800], "response_format": "json", "temperature": "0"},
            files={"file": (filename, audio)},
            timeout=60,
        )
        response.raise_for_status()
        return str(response.json().get("text", "")).strip()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Transcription with %s failed: %s", settings.WHISPER_MODEL, str(e)[:300])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Couldn't make out the recording. Try again, or type it.")


def complete_json(system: str, user: str, schema: type[T]) -> T:
    """The first answer that parses as `schema`. Each provider gets two tries (rate limits, empty answers and
    invalid JSON are usually one-offs). Raises a clear 503/502 instead of returning anything made up."""
    providers = list(_providers())
    if not providers:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI isn't set up yet: add GROQ_API_KEY to backend/.env.")
    for name, url, key, model in providers:
        for attempt in range(2):
            try:
                return schema.model_validate_json(_ask(url, key, model, system, user))
            except (httpx.HTTPError, ValueError, ValidationError) as e:
                # Log the reason only; the answer itself can hold characters the Windows console can't print.
                log.warning("AI call to %s (%s) failed, attempt %d: %s", name, model, attempt + 1, str(e)[:300])
                time.sleep(1 + attempt)
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI didn't give a usable answer. Try again in a minute.")
