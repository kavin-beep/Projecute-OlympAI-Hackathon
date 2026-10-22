"""Agent orchestration (LangGraph).

Three agents from slide 5: PM (brief + tickets), Architect (meaning check over
retrieved claims) and QA (acceptance criteria), plus the two slide-8
innovations (Parallel Futures comparison, Human Unit Test comparison).

Each agent asks the LLM for JSON, validates it with Pydantic, and falls back to
a deterministic local heuristic when no provider key is present. The heuristics
are real rules over the text — nothing about a specific demo is hard-coded.
"""
from __future__ import annotations

import re
from typing import Any, TypedDict

from .llm import llm
from .retrieval import related, similarity
from .schemas import (
    AcceptanceCriteria,
    ArchitectVerdict,
    BriefDraft,
    FuturesComparison,
    TicketProposal,
    TicketSet,
    UnitTestVerdict,
)

try:  # LangGraph drives the multi-step pipelines
    from langgraph.graph import END, StateGraph

    HAS_LANGGRAPH = True
except Exception:  # pragma: no cover
    HAS_LANGGRAPH = False


# ---------------------------------------------------------------------------
# Local heuristics (also used as the mock fallback)
# ---------------------------------------------------------------------------
NEGATIVE = (r"\b(?:no|not|without|never|don'?t|doesn'?t|cannot|can'?t|optional|anonymous|unnecessary"
            r"|disable[sd]?)\b")
POSITIVE = (r"\b(?:must|required?|requires|mandatory|always|need(?:s|ed)?\s+to|forced?|enforce[sd]?"
            r"|compulsory|only\s+if)\b")
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    """Lower-case word set of a text, used for overlap checks."""
    return set(_WORD.findall(text.lower()))


_NEGATED_REQUIREMENT = re.compile(
    r"\b(?:do(?:es)?\s*n'?o?t|don'?t|doesn'?t|not|never|no)\s+"
    r"(?:(?:really|strictly|always)\s+)?(?:need\s+to|needs\s+to|require[sd]?|have\s+to|has\s+to|must)\b")


def _polarity(text: str) -> int:
    """-1 if the text says something is not needed, +1 if required, 0 if neither.

    "does not need to" reads as a requirement and a negation at the same time,
    so negated requirements are collapsed first.
    """
    t = _NEGATED_REQUIREMENT.sub(" without ", text.lower())
    neg = len(re.findall(NEGATIVE, t))
    pos = len(re.findall(POSITIVE, t))
    if neg > pos:
        return -1
    if pos > neg:
        return 1
    return 0


def _numbers(text: str) -> set[str]:
    """All numbers mentioned in a text (e.g. '3 days', '50 users')."""
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", text))


def _subject_overlap(a: str, b: str) -> float:
    """Share of words two texts have in common, relative to the shorter one."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def heuristic_verdict(a: str, b: str) -> ArchitectVerdict:
    """Rule-based meaning check between two related claims."""
    sim = similarity(a, b)
    overlap = _subject_overlap(a, b)
    pa, pb = _polarity(a), _polarity(b)
    na, nb = _numbers(a), _numbers(b)
    topic = _shared_topic(a, b)

    opposed = pa != 0 and pb != 0 and pa != pb
    number_clash = bool(na and nb and na != nb and overlap >= 0.3)

    if opposed and (sim >= 0.22 or overlap >= 0.3):
        earlier, later = (a, b) if pa == -1 else (b, a)
        return ArchitectVerdict(
            kind="contradiction",
            severity="high",
            headline=f"These two messages disagree about {topic}",
            explanation=(
                f"One message says {topic} is not needed, the other says it is required. "
                "The team has to pick one before work continues."
            ),
            options=[
                f"Keep it as first agreed — {_short(earlier)}",
                f"Change it — {_short(later)}",
                "Support both and split the work in two",
            ],
        )
    if number_clash:
        return ArchitectVerdict(
            kind="assumption",
            severity="medium",
            headline=f"People assumed different numbers for {topic}",
            explanation=(
                f"The messages give different values for {topic} "
                f"({', '.join(sorted(na))} vs {', '.join(sorted(nb))}). "
                "Agree on one number so estimates stay honest."
            ),
            options=[f"Use {sorted(na)[0]}", f"Use {sorted(nb)[0]}", "Ask the client to confirm"],
        )
    if sim >= 0.50 or overlap >= 0.72:
        return ArchitectVerdict(
            kind="duplicate",
            severity="low",
            headline="Looks like the same task",
            explanation="These two describe the same piece of work in different words. Merge them so nobody builds it twice.",
            options=["Merge into one task", "Keep both — they are different after all"],
        )
    if sim >= 0.40:
        return ArchitectVerdict(
            kind="unclear",
            severity="low",
            headline=f"Not sure these agree about {topic}",
            explanation="These messages are about the same thing but the prototype cannot tell whether they conflict. A person should read them.",
            options=["They agree — dismiss", "They conflict — decide now"],
        )
    return ArchitectVerdict(kind="none", severity="low", headline="No issue found", explanation="")


def _short(text: str, limit: int = 170) -> str:
    """Collapse whitespace and trim a text to `limit` characters for display."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,.;") + "…"


def _shared_topic(a: str, b: str) -> str:
    """Pick the most specific word both texts share, to name the topic in a headline."""
    shared = [w for w in _WORD.findall(a.lower()) if w in _words(b) and len(w) > 3]
    stop = {"that", "this", "with", "from", "they", "should", "will", "have", "need", "needs",
            "message", "messages", "think", "about", "make", "when", "also", "page", "flow",
            "every", "before", "their", "there", "would", "could", "because", "after"}
    shared = [w for w in shared if w not in stop]
    if not shared:
        return "this requirement"
    best: list[str] = []
    for w in sorted(set(shared), key=lambda x: -len(x)):
        if w not in best:
            best.append(w)
    return best[0]


# ---------------------------------------------------------------------------
# PM agent
# ---------------------------------------------------------------------------
PM_SYSTEM = (
    "You are the PM agent inside a team project tool. You read a team's chat messages and "
    "turn them into a short, concrete project brief, then into work tickets. "
    "Use only what the messages actually say. Plain language, no jargon."
)


META = re.compile(r"\b(brief|standup|stand-up|meeting|agenda|channel|slide|deck|welcome)\b", re.I)


def _mock_brief(messages: list[dict]) -> dict:
    """Demo-mode PM agent: build a brief from the chat with simple text rules."""
    texts = [m["content"].strip() for m in messages if m.get("kind", "user") == "user"]
    texts = [t for t in texts if len(t) > 25 and not META.search(t)]
    joined = " ".join(texts)
    topic = _top_phrase(joined) or "the project"
    assumption_re = re.compile(r"\b(assume|assuming|probably|i think|maybe|for now|presumably)\b", re.I)
    assumptions = [t for t in texts if assumption_re.search(t)][:3]
    goals = [t for t in texts if t not in assumptions][:4] or texts[:3]
    return {
        "title": f"Brief: {topic}",
        "summary": (
            f"The team discussed {topic}. This brief collects what was said in the group chat so "
            "everyone works from the same starting point."
        ),
        "goals": goals or ["Agree what we are building"],
        "non_goals": [],
        "assumptions": assumptions,
    }


def _top_phrase(text: str) -> str:
    """Most repeated two-word phrase (or word) in a text, used as the brief's topic."""
    words = [w for w in _WORD.findall(text.lower()) if len(w) > 3]
    stop = {"that", "this", "with", "from", "they", "should", "will", "have", "need", "needs",
            "think", "about", "make", "when", "also", "want", "going", "lets", "okay", "then",
            "just", "like", "right", "work", "which", "there", "been", "what", "much"}
    words = [w for w in words if w not in stop]
    if not words:
        return ""
    bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
    from collections import Counter

    for cand, count in Counter(bigrams).most_common():
        if count > 1:
            return cand
    return Counter(words).most_common(1)[0][0]


def _mock_tickets(brief_text: str, messages: list[dict]) -> dict:
    """Derive tickets from the sentences that read like work."""
    sentences: list[str] = []
    for m in messages:
        for part in re.split(r"(?<=[.!?])\s+|\n", m["content"]):
            part = part.strip(" -•")
            if len(part) > 18 and not META.search(part):
                sentences.append(part)
    verbs = ("add", "build", "implement", "create", "set up", "support", "allow", "make",
             "handle", "store", "send", "validate", "design", "write", "update", "need", "require")
    picks: list[str] = []
    for s in sentences:
        low = s.lower()
        if any(v in low for v in verbs) and not low.startswith(("what", "why", "how", "do we", "should we")):
            if not any(similarity(s, p) > 0.75 for p in picks):
                picks.append(s)
    picks = picks[:6] or sentences[:3]
    tickets = []
    for s in picks:
        words = len(s.split())
        est = 3.0 if words < 10 else (5.0 if words < 16 else 8.0)
        pri = "High" if re.search(POSITIVE, s.lower()) else "Medium"
        tickets.append({
            "title": _as_task_title(s),
            "detail": s,
            "priority": pri,
            "estimated_hours": est,
            "owner_hint": "",
        })
    return {"tickets": tickets}


_LEADER = re.compile(
    r"^(?:so|and|also|but|then|ok|okay|right|well|plus|actually|basically|anyway)\b[,\s]*", re.I)
_SUBJECT = re.compile(
    r"^(?:we|i|you|they)\s+(?:also\s+)?(?:should|could|need to|needs to|want to|will|must|have to|just|can)\s+",
    re.I)


def _as_task_title(sentence: str) -> str:
    """Turn a chat sentence into a short imperative task title."""
    s = " ".join(sentence.split()).strip(" .")
    for _ in range(3):
        before = s
        s = _LEADER.sub("", s)
        s = _SUBJECT.sub("", s)
        if s == before:
            break
    s = re.sub(r"^(?:we|i|they)\s+", "", s, flags=re.I)
    s = s[:1].upper() + s[1:]
    return s[:120]


def extract_brief(messages: list[dict]) -> tuple[BriefDraft, str]:
    """PM agent: read the team chat and draft a structured project brief."""
    convo = "\n".join(f"{m['author']}: {m['content']}" for m in messages)
    return llm.structured(
        BriefDraft,
        system=PM_SYSTEM,
        user=f"Team chat:\n{convo}\n\nWrite the project brief.",
        mock=lambda: _mock_brief(messages),
    )


def propose_tickets(brief_text: str, messages: list[dict], members: list[str]) -> tuple[TicketSet, str]:
    """PM agent: propose tickets (task, priority, estimated hours, owner) from the brief."""
    convo = "\n".join(f"{m['author']}: {m['content']}" for m in messages)
    return llm.structured(
        TicketSet,
        system=PM_SYSTEM,
        user=(
            f"Approved brief:\n{brief_text}\n\nTeam chat:\n{convo}\n\n"
            f"Team members: {', '.join(members)}\n\n"
            "Propose 3 to 6 tickets. Each needs a task title, short detail, priority "
            "(Low/Medium/High), estimated hours and a suggested owner from the team."
        ),
        mock=lambda: _mock_tickets(brief_text, messages),
    )


# ---------------------------------------------------------------------------
# Architect agent
# ---------------------------------------------------------------------------
ARCHITECT_SYSTEM = (
    "You are the Architect agent. You compare two statements made by a project team and decide "
    "whether they are a duplicate, a contradiction, an assumption mismatch, or unclear. "
    "Write for a reader who is not technical. Never mention models, embeddings or thresholds."
)


def architect_check(claim_a: str, claim_b: str) -> tuple[ArchitectVerdict, str]:
    """Architect agent: decide whether two statements duplicate or contradict each other."""
    return llm.structured(
        ArchitectVerdict,
        system=ARCHITECT_SYSTEM,
        user=(
            f"Statement A: {claim_a}\nStatement B: {claim_b}\n\n"
            "Decide: duplicate, contradiction, assumption (people assumed different things), "
            "unclear, or none. Give a short headline, a plain explanation, and 2-3 resolution options."
        ),
        mock=lambda: heuristic_verdict(claim_a, claim_b).model_dump(),
    )


def find_related(claim: str, corpus: list[tuple[str, str]], k: int = 4,
                 min_score: float = 0.18) -> list[tuple[str, float]]:
    """Retrieve the past claims most related to a new claim (embeddings + FAISS)."""
    return related(claim, corpus, k=k, min_score=min_score)


# ---------------------------------------------------------------------------
# QA agent
# ---------------------------------------------------------------------------
def acceptance_criteria(ticket_title: str, detail: str, decision: str) -> tuple[AcceptanceCriteria, str]:
    """QA agent: write checkable acceptance criteria for a ticket after a decision."""
    def mock() -> dict:
        """Demo-mode acceptance criteria built from the ticket and the decision."""
        base = [
            f"{ticket_title} works end to end for a normal user.",
            "The agreed decision is followed: " + (decision.strip() or "as recorded in the project decisions."),
            "Nothing that worked before this change is broken.",
        ]
        if detail.strip():
            base.insert(1, "Covers what the team described: " + detail.strip()[:140])
        return {"criteria": base}

    return llm.structured(
        AcceptanceCriteria,
        system="You are the QA agent. Write short, checkable acceptance criteria in plain language.",
        user=f"Ticket: {ticket_title}\nDetail: {detail}\nTeam decision: {decision}\n\nWrite 3-5 acceptance criteria.",
        mock=mock,
    )


# ---------------------------------------------------------------------------
# Parallel Futures / Human Unit Test
# ---------------------------------------------------------------------------
def compare_futures(scenario: str, answers: list[dict]) -> tuple[FuturesComparison, str]:
    """Parallel Futures: compare members' independent answers to surface hidden assumptions."""
    def mock() -> dict:
        """Demo-mode comparison: pairwise rule-based checks between answers."""
        if len(answers) < 2:
            return {"summary": "Waiting for more answers before comparing.", "agreements": [], "hidden_assumptions": []}
        agreements, hidden = [], []
        for i in range(len(answers)):
            for j in range(i + 1, len(answers)):
                a, b = answers[i], answers[j]
                v = heuristic_verdict(a["answer"], b["answer"])
                if v.kind in ("contradiction", "assumption"):
                    hidden.append(f"{a['author']} and {b['author']} disagree: {v.headline.lower()}")
                elif v.kind == "duplicate" or similarity(a["answer"], b["answer"]) >= 0.45:
                    agreements.append(f"{a['author']} and {b['author']} described the same outcome")
        return {
            "summary": ("Everyone described the scenario the same way." if not hidden
                        else f"{len(hidden)} hidden assumption(s) surfaced from {len(answers)} answers."),
            "agreements": agreements[:5],
            "hidden_assumptions": hidden[:5],
        }

    body = "\n\n".join(f"{a['author']} answered: {a['answer']}" for a in answers)
    return llm.structured(
        FuturesComparison,
        system="You compare independent answers to the same scenario and surface hidden assumptions, in plain language.",
        user=f"Scenario: {scenario}\n\n{body}\n\nWhat do they agree on, and where do they silently assume different things?",
        mock=mock,
    )


def compare_interpretations(ticket_title: str, creator_desc: str, assignee_desc: str) -> tuple[UnitTestVerdict, str]:
    """Human Unit Test: compare creator and assignee descriptions of the same task."""
    def mock() -> dict:
        """Demo-mode comparison: rule-based verdict plus words only one person used."""
        v = heuristic_verdict(creator_desc, assignee_desc)
        sim = similarity(creator_desc, assignee_desc)
        if v.kind in ("contradiction", "assumption") or sim < 0.3:
            diffs = []
            if v.kind in ("contradiction", "assumption"):
                diffs.append(v.headline)
            only_creator = _words(creator_desc) - _words(assignee_desc)
            only_assignee = _words(assignee_desc) - _words(creator_desc)
            big_c = [w for w in only_creator if len(w) > 5][:4]
            big_a = [w for w in only_assignee if len(w) > 5][:4]
            if big_c:
                diffs.append("Only the person who wrote the task mentioned: " + ", ".join(big_c))
            if big_a:
                diffs.append("Only the person doing the task mentioned: " + ", ".join(big_a))
            return {"verdict": "mismatch",
                    "summary": "The two descriptions of this task do not line up. Talk before starting.",
                    "differences": diffs or ["The two descriptions have little in common."]}
        return {"verdict": "match",
                "summary": "Both people describe this task the same way. Safe to start.",
                "differences": []}

    return llm.structured(
        UnitTestVerdict,
        system="You compare how two people describe the same task before work starts, and flag mismatches in plain language.",
        user=(f"Task: {ticket_title}\n\nThe person who created it says: {creator_desc}\n\n"
              f"The person doing it says: {assignee_desc}\n\nDo these match?"),
        mock=mock,
    )


# ---------------------------------------------------------------------------
# LangGraph pipelines
# ---------------------------------------------------------------------------
class PlanState(TypedDict, total=False):
    """LangGraph state for the planning graph: chat -> brief -> tickets."""
    messages: list[dict]
    members: list[str]
    brief: dict
    brief_source: str
    tickets: list[dict]
    tickets_source: str


def _node_brief(state: PlanState) -> PlanState:
    """Graph node: run the PM agent to draft the brief."""
    brief, src = extract_brief(state["messages"])
    return {"brief": brief.model_dump(), "brief_source": src}


def _node_tickets(state: PlanState) -> PlanState:
    """Graph node: run the PM agent to propose tickets from the drafted brief."""
    draft = BriefDraft.model_validate(state["brief"])
    tickets, src = propose_tickets(draft.to_markdown(), state["messages"], state.get("members", []))
    return {"tickets": [t.model_dump() for t in tickets.tickets], "tickets_source": src}


_plan_graph = None
if HAS_LANGGRAPH:
    _g = StateGraph(PlanState)
    _g.add_node("pm_brief", _node_brief)
    _g.add_node("pm_tickets", _node_tickets)
    _g.set_entry_point("pm_brief")
    _g.add_edge("pm_brief", "pm_tickets")
    _g.add_edge("pm_tickets", END)
    _plan_graph = _g.compile()


def run_plan_pipeline(messages: list[dict], members: list[str]) -> PlanState:
    """PM agent: chat -> brief -> proposed tickets."""
    state: PlanState = {"messages": messages, "members": members}
    if _plan_graph is not None:
        return _plan_graph.invoke(state)
    state.update(_node_brief(state))
    state.update(_node_tickets(state))
    return state


class ReviewState(TypedDict, total=False):
    """LangGraph state for the review graph: new claim -> related claims -> verdict."""
    claim: str
    corpus: list[tuple[str, str]]
    matches: list[tuple[str, float]]
    verdict: dict
    verdict_source: str


def _node_retrieve(state: ReviewState) -> ReviewState:
    """Graph node: find past claims related to the new one."""
    return {"matches": find_related(state["claim"], state["corpus"])}


def _node_architect(state: ReviewState) -> ReviewState:
    """Graph node: ask the Architect about each related claim and keep the most serious issue."""
    corpus = dict(state["corpus"])
    best: dict[str, Any] | None = None
    for mid, score in state.get("matches", []):
        verdict, src = architect_check(state["claim"], corpus[mid])
        if verdict.kind == "none":
            continue
        rank = {"contradiction": 3, "assumption": 2, "duplicate": 1, "unclear": 0}[verdict.kind]
        if best is None or rank > best["rank"]:
            best = {"rank": rank, "verdict": verdict.model_dump(), "source": src,
                    "match_id": mid, "score": score}
    if best is None:
        return {"verdict": {}, "verdict_source": "none"}
    out = dict(best["verdict"])
    out["match_id"] = best["match_id"]
    out["score"] = best["score"]
    return {"verdict": out, "verdict_source": best["source"]}


_review_graph = None
if HAS_LANGGRAPH:
    _r = StateGraph(ReviewState)
    _r.add_node("retrieve", _node_retrieve)
    _r.add_node("architect", _node_architect)
    _r.set_entry_point("retrieve")
    _r.add_edge("retrieve", "architect")
    _r.add_edge("architect", END)
    _review_graph = _r.compile()


def run_review_pipeline(claim: str, corpus: list[tuple[str, str]]) -> ReviewState:
    """Retrieval + Architect: is this new claim a duplicate/conflict with past ones?"""
    state: ReviewState = {"claim": claim, "corpus": corpus}
    if _review_graph is not None:
        return _review_graph.invoke(state)
    state.update(_node_retrieve(state))
    state.update(_node_architect(state))
    return state
