"""LLM adapter: Groq when a key is present, a clearly labelled mock otherwise.

Every structured call is validated with Pydantic and retried; responses are
cached and rate limits are handled with exponential backoff.
With a key configured the app always stays in live mode: if the provider still
fails after the retries, chat replies ask the user to try again and agent steps
use the built-in rules for that one step. Demo mode is only for runs without a key.
The API key is never printed, logged or returned to the client.
"""
# How to read this file
# ---------------------
# One shared object, `llm` (bottom of the file), is used by the whole app:
#   llm.complete(...)   -> a full text answer       (group AI replies)
#   llm.stream(...)     -> text pieces as they come (individual chat)
#   llm.structured(...) -> a validated Pydantic object (every agent in app/agents.py)
# Reliability: answers are cached; rate limits switch to the backup model or wait;
# timeouts back off and retry; invalid JSON is sent back to the model to correct.

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

# ---------------------------------------------------------------- settings
DEFAULT_MODEL = "openai/gpt-oss-120b"          # OpenAI open-weight model, served by Groq
DEFAULT_FALLBACK_MODEL = "openai/gpt-oss-20b"  # smaller OpenAI model with its own Groq limits
MAX_RETRIES = 3          # attempts to get JSON that validates
TRANSPORT_RETRIES = 5    # attempts per provider call (rate limits, timeouts), with backoff
MAX_WAIT_PER_TRY = 8     # seconds to wait for a rate limit before trying again
CACHE_MAX = 512
BUSY_MESSAGE = ("Projecute AI couldn't reach the AI service just now. "
                "Please send your message again in a moment.")


class AIUnavailable(Exception):
    """The live AI service could not be reached after every retry."""


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


# Load .env as soon as this module is imported, before the LLM object reads the key.
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
        # A second OpenAI open-weight model on the same key. Groq's free tier limits each
        # model separately (tokens per minute and per day), so this doubles the capacity.
        self.fallback_model = os.environ.get("GROQ_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL).strip()
        self._key = os.environ.get("GROQ_API_KEY", "").strip()
        self._client = None
        self._degraded_reason: str | None = None
        self._limited_until: dict[str, float] = {}     # model -> time its rate limit frees up
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
        """'live' whenever a Groq key is configured, otherwise 'mock' (demo mode, no key)."""
        return "live" if self._client is not None else "mock"

    def status(self) -> dict:
        """What the header shows: live or demo mode, which model, and why it degraded."""
        return {
            "mode": self.mode,
            "label": "Live AI" if self.mode == "live" else "Demo mode",
            "model": self.model if self.mode == "live" else "built-in demo responses",
            "backup_model": self.fallback_model if self.mode == "live" else None,
            "reason": self._degraded_reason,
        }

    def _note_problem(self, reason: str) -> None:
        """Remember the last provider problem (shown in Settings); live mode stays on."""
        self._degraded_reason = reason

    def _models(self) -> list[str]:
        """Models to try now: those not rate-limited first, then the one that frees up soonest."""
        models = [m for m in dict.fromkeys([self.model, self.fallback_model]) if m]
        now = time.time()
        free = [m for m in models if self._limited_until.get(m, 0) <= now]
        return free or sorted(models, key=lambda m: self._limited_until.get(m, 0))

    def _rate_limited(self, model: str, exc: Exception) -> float:
        """Record when `model` frees up (from Groq's hint) and return how long that is, in seconds."""
        wait = _retry_after(exc)
        self._limited_until[model] = time.time() + wait
        return wait

    def _request(self, model: str, messages: list[dict], temperature: float, max_tokens: int,
                 *, stream: bool = False, json_mode: bool = False):
        """One Groq call. OpenAI gpt-oss models use light reasoning for chat to save tokens."""
        kwargs: dict[str, Any] = dict(model=model, messages=messages, temperature=temperature,
                                      max_tokens=max_tokens, stream=stream)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        elif "gpt-oss" in model:
            kwargs["reasoning_effort"] = "low"
        return self._client.chat.completions.create(**kwargs)

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
        """Free-text answer for a chat history, cached.

        Without a key it returns the labelled demo answer. With a key it raises
        AIUnavailable if the provider fails after every retry, so callers can ask
        the user to try again instead of showing a demo answer.
        """
        # 1. Same question asked before? Return the cached answer (saves tokens).
        key = _hash(self.model, messages, temperature)
        if cache:
            hit = _cache.get(key)
            if hit is not None:
                return hit
        # 2. No key configured: the labelled demo answer.
        if self.mode != "live":
            return (mock or (lambda: demo_answer(_last_question(messages))))()
        # 3. Ask the provider (with retries); cache and return the answer.
        text = self._call_with_backoff(messages, temperature, max_tokens)
        if text is None:
            raise AIUnavailable(self._degraded_reason or "AI provider unavailable")
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
        """Yield text chunks. Without a key, chunks the labelled demo answer.

        With a key, a failed stream is retried with backoff; if nothing could be
        sent after every retry, the user is asked to try again (never a demo answer).
        """
        if self.mode == "live":
            # Live: try up to TRANSPORT_RETRIES times, each time with the best available model.
            delay = 1.0
            for attempt in range(TRANSPORT_RETRIES):
                model = self._models()[0]
                sent = False
                try:
                    for chunk in self._request(model, messages, temperature, max_tokens, stream=True):
                        piece = chunk.choices[0].delta.content or ""
                        if piece:
                            sent = True
                            yield piece
                    self._degraded_reason = None
                    return
                except Exception as exc:
                    self._note_problem(f"{type(exc).__name__} during streaming")
                    if sent:                      # part of the answer is already on screen
                        yield "\n\n_" + BUSY_MESSAGE + "_"
                        return
                    if attempt == TRANSPORT_RETRIES - 1:
                        break
                    if "RateLimit" in type(exc).__name__:
                        wait = self._rate_limited(model, exc)
                        if self._models()[0] != model:
                            continue              # the other model is free: switch at once
                        time.sleep(min(wait, MAX_WAIT_PER_TRY))
                    else:
                        time.sleep(delay + random.random() * 0.3)
                        delay *= 2
            yield BUSY_MESSAGE
            return
        # No key: send the demo answer word by word so it looks like streaming.
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
        Without a key, or if the provider still fails after every retry, the
        built-in rules (`mock`) decide that one step; live mode stays on.
        """
        if self.mode != "live":
            return schema.model_validate(mock()), "mock"

        # Tell the model the exact JSON shape (from the Pydantic schema) it must return.
        shape = json.dumps(schema.model_json_schema(), separators=(",", ":"))
        msgs = [
            {"role": "system", "content": f"{system}\n\nReply with JSON only, matching this schema:\n{shape}"},
            {"role": "user", "content": user},
        ]
        # Up to MAX_RETRIES tries: parse and validate; on failure, show the model its error.
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
            self._note_problem("AI output failed validation; built-in rules used for one step")
        return schema.model_validate(mock()), "rules"

    # ---------------- transport ----------------
    def _call_with_backoff(
        self, messages: list[dict], temperature: float, max_tokens: int, json_mode: bool = False
    ) -> str | None:
        """Call Groq, switching to the backup model on rate limits and backing off on timeouts."""
        # Rate limit: switch to the other model if it is free, else wait (at most
        # MAX_WAIT_PER_TRY). Timeout / connection / server error: exponential backoff.
        delay = 1.0
        for attempt in range(TRANSPORT_RETRIES):
            model = self._models()[0]
            try:
                resp = self._request(model, messages, temperature, max_tokens, json_mode=json_mode)
                self._degraded_reason = None          # the provider is healthy again
                return resp.choices[0].message.content or ""
            except Exception as exc:
                name = type(exc).__name__
                retryable = "RateLimit" in name or "Timeout" in name or "APIConnection" in name or "InternalServer" in name
                if retryable and attempt < TRANSPORT_RETRIES - 1:
                    if "RateLimit" in name:
                        wait = self._rate_limited(model, exc)
                        if self._models()[0] != model:
                            continue                  # the other model is free: switch at once
                        time.sleep(min(wait, MAX_WAIT_PER_TRY))
                    else:
                        time.sleep(delay + random.random() * 0.3)
                        delay *= 2
                    continue
                self._note_problem(f"{name} from the AI provider")
                return None
        return None


# ---------------------------------------------------------------- helpers
def _retry_after(exc: Exception) -> float:
    """Seconds until a rate limit frees up, from Groq's header or message (default 30 s)."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        if headers.get("retry-after"):
            return float(headers["retry-after"])
    except (TypeError, ValueError):
        pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(exc))
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    return 30.0


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


# The single shared instance imported everywhere (`from .llm import llm`).
llm = LLM()
