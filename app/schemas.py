"""Pydantic schemas. Every AI JSON output is validated against one of these."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Priority = Literal["Low", "Medium", "High"]
FlagKind = Literal["duplicate", "contradiction", "assumption", "unclear", "none"]
Severity = Literal["low", "medium", "high"]


class BriefDraft(BaseModel):
    """The project brief the PM agent drafts."""
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1)
    goals: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """Render the brief as Markdown for display and editing."""
        parts = [f"# {self.title}", "", self.summary.strip(), ""]
        for heading, items in (("Goals", self.goals), ("Not in scope", self.non_goals),
                               ("Assumptions", self.assumptions)):
            if items:
                parts.append(f"## {heading}")
                parts += [f"- {i}" for i in items]
                parts.append("")
        return "\n".join(parts).strip()


class TicketProposal(BaseModel):
    """One proposed ticket: task, detail, priority, estimated hours, suggested owner."""
    title: str = Field(min_length=1, max_length=140)
    detail: str = ""
    priority: Priority = "Medium"
    estimated_hours: float = Field(default=4, ge=0.5, le=200)
    owner_hint: str = ""

    @field_validator("estimated_hours", mode="before")
    @classmethod
    def _coerce(cls, v):
        """Accept hours given as text ('4') and default to 4 when unreadable."""
        try:
            return float(v)
        except (TypeError, ValueError):
            return 4.0


class TicketSet(BaseModel):
    """The list of tickets the PM agent proposes."""
    tickets: list[TicketProposal] = Field(default_factory=list)


class ArchitectVerdict(BaseModel):
    """The Architect agent's verdict on two statements, with resolution options."""
    kind: FlagKind
    severity: Severity = "medium"
    headline: str = Field(min_length=1, max_length=140)
    explanation: str = ""
    options: list[str] = Field(default_factory=list)


class NumberedVerdict(ArchitectVerdict):
    """One verdict inside a batch, tied to its pair by number."""
    pair: int = Field(ge=1)


class ArchitectBatch(BaseModel):
    """Verdicts for several statement pairs from one batched Architect call."""
    verdicts: list[NumberedVerdict] = Field(default_factory=list)


class AcceptanceCriteria(BaseModel):
    """Acceptance criteria the QA agent writes for a ticket."""
    criteria: list[str] = Field(default_factory=list)


class FuturesComparison(BaseModel):
    """Result of comparing Parallel Futures answers."""
    summary: str = ""
    agreements: list[str] = Field(default_factory=list)
    hidden_assumptions: list[str] = Field(default_factory=list)


class UnitTestVerdict(BaseModel):
    """Result of a Human Unit Test: match or mismatch, and the differences."""
    verdict: Literal["match", "mismatch"]
    summary: str = ""
    differences: list[str] = Field(default_factory=list)


class Blocker(BaseModel):
    """Something that stops or delays planned work, found in a source document."""
    statement: str = Field(min_length=1)
    blocks: str = ""
    explanation: str = ""


class BlockerList(BaseModel):
    """The blockers the PM agent found in one source document."""
    blockers: list[Blocker] = Field(default_factory=list)


class TriageResult(BaseModel):
    """How the PM agent triages a bug ticket or issue."""
    category: Literal["bug", "feature", "question", "docs"] = "bug"
    priority: Priority = "Medium"
    estimated_hours: float = Field(default=4, ge=0.5, le=200)
    summary: str = ""

    @field_validator("estimated_hours", mode="before")
    @classmethod
    def _coerce(cls, v):
        """Accept hours given as text and default to 4 when unreadable."""
        try:
            return float(v)
        except (TypeError, ValueError):
            return 4.0
