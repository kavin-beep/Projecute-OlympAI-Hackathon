"""LLM adapter: Groq when a key is present, a clearly labelled mock otherwise.

Every structured call is validated with Pydantic and retried; responses are
cached and rate limits are handled with exponential backoff.
The API key is never printed, logged or returned to the client.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_RETRIES = 3
RETRY_LIVE_AFTER = 30   # seconds of demo answers after a provider error before trying live AI again
CACHE_MAX = 512


def _load_dotenv() -> None:
    """Read KEY=value lines from .env into the environment (without overriding real env vars)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


class _Cache:
    """Small thread-safe cache of LLM answers, oldest entry evicted first."""
    def __init__(self) -> None:
        """Start with an empty cache."""
        self._d: dict[str, str] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        """Cached answer for a key, or None."""
        with self._lock:
            return self._d.get(key)

    def put(self, key: str, value: str) -> None:
        """Store an answer, evicting the oldest entry when full."""
        with self._lock:
            if key not in self._d and len(self._order) >= CACHE_MAX:
                oldest = self._order.pop(0)
                self._d.pop(oldest, None)
            if key not in self._d:
                self._order.append(key)
            self._d[key] = value


_cache = _Cache()


class LLM:
    """Thin provider adapter. `mode` is 'live' (Groq) or 'mock'."""

    def __init__(self) -> None:
        """Read the model and key from the environment and create the Groq client if a key exists."""
        self.model = os.environ.get("GROQ_MODEL") or DEFAULT_MODEL
        self._key = os.environ.get("GROQ_API_KEY", "").strip()
        self._client = None
        self._degraded_reason: str | None = None
        self._retry_at = 0.0          # after a provider error, live AI resumes at this time
        if self._key:
            try:
                from groq import Groq

                self._client = Groq(api_key=self._key)
            except Exception as exc:  # pragma: no cover - import/setup failure
                self._client = None
                self._degraded_reason = f"Groq client unavailable ({type(exc).__name__})"

    # ---------------- status ----------------
    @property
    def mode(self) -> str:
        """'live' when the Groq client is usable, otherwise 'mock' (demo mode)."""
        return "live" if self._client is not None and time.time() >= self._retry_at else "mock"

    def status(self) -> dict:
        """What the header shows: live or demo mode, which model, and why it degraded."""
        return {
            "mode": self.mode,
            "label": "Live AI" if self.mode == "live" else "Demo mode",
            "model": self.model if self.mode == "live" else "built-in demo responses",
            "reason": self._degraded_reason,
        }

    def _degrade(self, reason: str) -> None:
        """Use demo answers for a short cool-down after a provider error, then try live AI again."""
        self._retry_at = time.time() + RETRY_LIVE_AFTER
        self._degraded_reason = reason

    # ---------------- free text ----------------
    def complete(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1200,
        mock: Callable[[], str] | None = None,
        cache: bool = True,
    ) -> str:
        """Free-text answer for a chat history, cached; uses the mock answer without a provider."""
        key = _hash(self.model, messages, temperature)
        if cache:
            hit = _cache.get(key)
            if hit is not None:
                return hit
        text: str | None = None
        if self.mode == "live":
            text = self._call_with_backoff(messages, temperature, max_tokens)
        if text is None:
            # Not cached, so the same question gets a live answer once the AI is back.
            return (mock or (lambda: demo_answer(_last_question(messages))))()
        if cache:
            _cache.put(key, text)
        return text

    def stream(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1200,
        mock: Callable[[], str] | None = None,
    ) -> Iterator[str]:
        """Yield text chunks. Falls back to chunking a mock answer."""
        if self.mode == "live":
            try:
                stream = self._client.chat.completions.create(
                    model=self.model, messages=messages, temperature=temperature,
                    max_tokens=max_tokens, stream=True,
                )
                for chunk in stream:
                    piece = chunk.choices[0].delta.content or ""
                    if piece:
                        yield piece
                return
            except Exception as exc:
                self._degrade(f"{type(exc).__name__} during streaming")
        text = (mock or (lambda: demo_answer(_last_question(messages))))()
        for part in re.findall(r"\S+\s*", text):
            yield part
            time.sleep(0.012)

    # ---------------- structured ----------------
    def structured(
        self,
        schema: type[T],
        *,
        system: str,
        user: str,
        mock: Callable[[], dict],
        temperature: float = 0.1,
        max_tokens: int = 1600,
    ) -> tuple[T, str]:
        """Return (validated model, source) where source is 'live' or 'mock'.

        Retries on invalid JSON, feeding the validation error back to the model.
        Falls back to the supplied mock when the provider is unavailable.
        """
        if self.mode != "live":
            return schema.model_validate(mock()), "mock"

        shape = json.dumps(schema.model_json_schema(), separators=(",", ":"))
        msgs = [
            {"role": "system", "content": f"{system}\n\nReply with JSON only, matching this schema:\n{shape}"},
            {"role": "user", "content": user},
        ]
        last_error = ""
        for _attempt in range(MAX_RETRIES):
            raw = self._call_with_backoff(msgs, temperature, max_tokens, json_mode=True)
            if raw is None:
                break
            try:
                return schema.model_validate(_extract_json(raw)), "live"
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                last_error = str(exc)[:600]
                msgs = msgs[:2] + [
                    {"role": "assistant", "content": raw[:2000]},
                    {"role": "user", "content": f"That did not validate: {last_error}\nReturn corrected JSON only."},
                ]
        if last_error:
            self._degraded_reason = "AI output failed validation; using demo response"
        return schema.model_validate(mock()), "mock"

    # ---------------- transport ----------------
    def _call_with_backoff(
        self, messages: list[dict], temperature: float, max_tokens: int, json_mode: bool = False
    ) -> str | None:
        """Call Groq, retrying rate limits and timeouts with exponential backoff."""
        delay = 0.8
        for attempt in range(MAX_RETRIES):
            try:
                kwargs: dict[str, Any] = dict(
                    model=self.model, messages=messages,
                    temperature=temperature, max_tokens=max_tokens,
                )
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = self._client.chat.completions.create(**kwargs)
                self._degraded_reason = None          # the provider is healthy again
                return resp.choices[0].message.content or ""
            except Exception as exc:
                name = type(exc).__name__
                retryable = "RateLimit" in name or "Timeout" in name or "APIConnection" in name or "InternalServer" in name
                if retryable and attempt < MAX_RETRIES - 1:
                    time.sleep(delay + random.random() * 0.3)
                    delay *= 2
                    continue
                self._degrade(f"{name} from the AI provider")
                return None
        return None


def _hash(model: str, messages: list[dict], temperature: float) -> str:
    """Cache key for a request: model, messages and temperature."""
    blob = json.dumps([model, messages, temperature], sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _extract_json(raw: str) -> Any:
    """Pull the JSON object out of a model reply (handles code fences and preambles)."""
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    start = min([i for i in (raw.find("{"), raw.find("[")) if i != -1], default=-1)
    if start > 0:
        raw = raw[start:]
    return json.loads(raw)


def _last_question(messages: list[dict]) -> str:
    """The user's actual question, even when it arrives wrapped in context."""
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    marker = last.rfind("Question: ")
    if marker != -1:
        return last[marker + len("Question: "):].strip()
    return last.strip().split("\n")[-1][:160]


def demo_answer(question: str) -> str:
    """The labelled stand-in reply used when no provider key is configured."""
    topic = " ".join(question.split())[:140] or "your question"
    return (
        "**Demo mode answer**\n\nThis prototype is running without an AI provider key, so this reply is "
        f"generated locally rather than by a model.\n\nYou asked: {topic}\n\n"
        "- Add `GROQ_API_KEY` to `.env` and restart to get live answers.\n"
        "- Everything else in the prototype — chat history, the workspace, the project pipeline "
        "and all privacy rules — works exactly the same in this mode.\n"
    )


llm = LLM()
