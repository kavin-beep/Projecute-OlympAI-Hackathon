"""Live AI must come back by itself after a provider error (no restart needed)."""
from __future__ import annotations

from types import SimpleNamespace

from app.llm import LLM


class BadRequestError(Exception):
    """Stands in for a non-retryable error from the provider."""


class FlakyClient:
    """Fails the first call, then answers normally."""

    def __init__(self) -> None:
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            raise BadRequestError("provider hiccup")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="live answer"))])


def test_live_ai_recovers_after_a_provider_error():
    llm = LLM()
    llm._client = FlakyClient()
    question = [{"role": "user", "content": "Is checkout guest-only?"}]

    first = llm.complete(question, mock=lambda: "demo answer")
    assert first == "demo answer"            # the error falls back to the demo answer...
    assert llm.mode == "mock"                # ...for a short cool-down only

    llm._retry_at = 0                        # cool-down over
    assert llm.mode == "live"
    assert llm.complete(question, mock=lambda: "demo answer") == "live answer"   # not stuck on the cached demo
    assert llm.status()["reason"] is None
