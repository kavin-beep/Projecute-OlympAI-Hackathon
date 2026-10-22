"""With a key configured, the app stays in live mode: no demo answers after a provider error."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import llm as llm_module
from app.llm import BUSY_MESSAGE, LLM, AIUnavailable


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


class DownClient:
    """Always fails, like a provider outage."""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **_kwargs):
        raise BadRequestError("provider down")


def test_a_provider_error_never_switches_the_app_to_demo_mode():
    llm = LLM()
    llm._client = FlakyClient()
    question = [{"role": "user", "content": "Is checkout guest-only?"}]

    with pytest.raises(AIUnavailable):          # the caller asks the user to try again
        llm.complete(question, mock=lambda: "demo answer")
    assert llm.mode == "live"                   # the header still says Live AI
    assert llm.status()["label"] == "Live AI"

    assert llm.complete(question, mock=lambda: "demo answer") == "live answer"   # next call is live
    assert llm.status()["reason"] is None


def test_streamed_chat_asks_to_try_again_instead_of_a_demo_answer(monkeypatch):
    monkeypatch.setattr(llm_module.time, "sleep", lambda _s: None)   # skip the backoff waits
    llm = LLM()
    llm._client = DownClient()
    reply = "".join(llm.stream([{"role": "user", "content": "hello"}]))
    assert reply == BUSY_MESSAGE
    assert "Demo mode" not in reply
    assert llm.mode == "live"


def test_agent_steps_use_the_rules_for_that_step_and_stay_live(monkeypatch):
    from app.schemas import AcceptanceCriteria

    monkeypatch.setattr(llm_module.time, "sleep", lambda _s: None)
    llm = LLM()
    llm._client = DownClient()
    result, source = llm.structured(AcceptanceCriteria, system="s", user="u",
                                    mock=lambda: {"criteria": ["rule-based criterion"]})
    assert result.criteria == ["rule-based criterion"] and source == "rules"
    assert llm.mode == "live"


class RateLimitError(Exception):
    """Stands in for Groq's rate-limit error (daily or per-minute)."""


class MainModelLimitedClient:
    """The main model is out of daily tokens; the backup model answers."""

    def __init__(self) -> None:
        self.models: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.models.append(kwargs["model"])
        if kwargs["model"] == "openai/gpt-oss-120b":
            raise RateLimitError("Rate limit reached on tokens per day (TPD). Please try again in 3m20.016s.")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="backup answer"))])


def test_a_rate_limited_main_model_switches_to_the_backup_at_once(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(llm_module.time, "sleep", slept.append)
    llm = LLM()
    llm.model, llm.fallback_model = "openai/gpt-oss-120b", "openai/gpt-oss-20b"
    client = MainModelLimitedClient()
    llm._client = client
    question = [{"role": "user", "content": "hi"}]

    assert llm.complete(question, cache=False) == "backup answer"
    assert client.models == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert slept == []                                   # no waiting: the backup was free

    client.models.clear()
    assert llm.complete(question, cache=False) == "backup answer"
    assert client.models == ["openai/gpt-oss-20b"]       # remembers the main model is limited for ~3 min
