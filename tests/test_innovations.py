"""Parallel Futures in demo mode: the built-in rules never report an agreement they did not find."""
# Each test's name states the rule it checks. Run this file alone with:
#   python -m pytest -q tests/test_innovations.py

from __future__ import annotations

import pytest

from app import agents
from app.llm import llm

SCENARIO = "A returning shopper opens checkout. What happens?"


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    """Run these checks on the built-in rules, the same as a run without an AI key."""
    monkeypatch.setattr(llm, "_client", None)


def _answers(first: str, second: str) -> list[dict]:
    """Two members' answers to the same scenario."""
    return [{"author": "Adrian Rohith", "answer": first}, {"author": "Sritharan N S", "answer": second}]


# Answers the rules can't classify are shown as different, never as "everyone agreed".
def test_answers_the_rules_cannot_classify_are_not_reported_as_agreement():
    result, source = agents.compare_futures(SCENARIO, _answers(
        "They check out as a guest with just an email address.",
        "They must log in to an account before they can pay."))
    assert source == "mock"
    assert "same way" not in result.summary
    assert "differ" in result.summary
    assert result.hidden_assumptions and "differently" in result.hidden_assumptions[0]


# A clear contradiction is reported as a hidden assumption.
def test_opposite_answers_surface_a_hidden_assumption():
    result, _ = agents.compare_futures(SCENARIO, _answers(
        "Checkout requires an account login before payment.",
        "Checkout does not require an account login before payment."))
    assert result.summary.startswith("1 hidden assumption")
    assert "disagree" in result.hidden_assumptions[0]


# Matching answers are still reported as an agreement.
def test_matching_answers_are_reported_as_the_same_outcome():
    result, _ = agents.compare_futures(SCENARIO, _answers(
        "Shoppers check out as guests with an email address for the receipt.",
        "Shoppers check out as guests with an email address for the receipt."))
    assert result.summary == "Everyone described the scenario the same way."
    assert result.agreements and not result.hidden_assumptions
