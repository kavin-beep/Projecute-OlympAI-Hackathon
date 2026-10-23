"""Agent orchestration (LangGraph).

Three agents from slide 5: PM (brief + tickets), Architect (meaning check over
retrieved claims) and QA (acceptance criteria), plus the two slide-8
innovations (Parallel Futures comparison, Human Unit Test comparison).

Each agent asks the LLM for JSON, validates it with Pydantic, and falls back to
a deterministic local heuristic when no provider key is present. The heuristics
are real rules over the text — nothing about a specific demo is hard-coded.
"""
# How to read this file
# ---------------------
# Sections, in order:
#   1. Local heuristics - text rules used when no AI key is set (and as a safety net).
#   2. PM agent        - chat -> project brief -> proposed tickets.
#   3. Architect agent - compares two statements: contradiction / assumption / duplicate.
#   4. QA agent        - acceptance criteria after a decision.
#   5. Parallel Futures and Human Unit Test comparisons (deck slide 8).
#   6. Source documents - splitting PRDs / bug tickets / meetings, blockers, triage.
#   7. LangGraph pipelines - the three graphs that chain the agents together.
# Every agent function has the same shape: llm.structured(Schema, system=..., user=...,
# mock=...) returns a validated Pydantic object and where it came from ('live' or 'mock').

from __future__ import annotations

import re
from typing import Any, TypedDict

from .llm import llm
from .retrieval import related, similarity
from .schemas import (
    AcceptanceCriteria,
    ArchitectBatch,
    ArchitectVerdict,
    BlockerList,
    BriefDraft,
    FuturesComparison,
    TicketSet,
    TriageResult,
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
# Words that say something is NOT needed (NEGATIVE) or IS needed (POSITIVE).
# Two related statements with opposite polarity are a likely contradiction.
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
    # Measure the pair: meaning similarity, shared words, polarity and numbers mentioned.
    sim = similarity(a, b)
    overlap = _subject_overlap(a, b)
    pa, pb = _polarity(a), _polarity(b)
    na, nb = _numbers(a), _numbers(b)
    topic = _shared_topic(a, b)

    opposed = pa != 0 and pb != 0 and pa != pb
    number_clash = bool(na and nb and na != nb and overlap >= 0.3)

    # Rule 1 - same subject, opposite polarity: a contradiction.
    if opposed and (sim >= 0.22 or overlap >= 0.3):
        earlier, later = (a, b) if pa == -1 else (b, a)
        return ArchitectVerdict(
            kind="contradiction",
            severity="high",
            headline=f"These statements disagree about {topic}",
            explanation=(
                f"One side says {topic} is not needed, the other says it is required. "
                "The team has to pick one before work continues."
            ),
            options=[
                f"Keep it as first agreed — {_short(earlier)}",
                f"Change it — {_short(later)}",
                "Support both and split the work in two",
            ],
        )
    # Rule 2 - same subject, different numbers: people assumed different values.
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
    # Rule 3 - almost the same words or meaning: the same task twice.
    if sim >= 0.50 or overlap >= 0.72:
        return ArchitectVerdict(
            kind="duplicate",
            severity="low",
            headline="Looks like the same task",
            explanation="These two describe the same piece of work in different words. Merge them so nobody builds it twice.",
            options=["Merge into one task", "Keep both — they are different after all"],
        )
    # Rule 4 - clearly related but undecidable by rules: ask a person.
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


# Messages about the meeting itself (not the product) are left out of the brief.
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
    # A sentence 'reads like work' if it contains an action verb and isn't a question.
    verbs = ("add", "build", "implement", "create", "set up", "support", "allow", "make",
             "handle", "store", "send", "validate", "design", "write", "update", "need", "require")
    picks: list[str] = []
    for s in sentences:
        low = s.lower()
        reads_like_work = any(v in low for v in verbs) and not low.startswith(
            ("what", "why", "how", "do we", "should we"))
        if reads_like_work and not any(similarity(s, p) > 0.75 for p in picks):
            picks.append(s)
    picks = picks[:6] or sentences[:3]
    tickets = []
    for s in picks:
        words = len(s.split())
        # Rough estimate from how long the description is; the team confirms hours later.
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


# Filler at the start of chat sentences ('So we should ...') removed to make task titles.
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
    "You are the Architect agent. You compare statements made by a project team and label each pair:\n"
    "- contradiction: opposite rules: one says something is required, allowed or needed, the other "
    "says it is not (e.g. 'login is required' vs 'no login').\n"
    "- assumption: both accept the same thing but assume different values or details: numbers, "
    "limits, durations, sizes, versions (e.g. 'keep orders 30 days' vs 'keep orders 90 days').\n"
    "- duplicate: the same piece of work or the same problem described in different words.\n"
    "- unclear: about the same thing, but you cannot tell whether they conflict; a person should read them.\n"
    "- none: unrelated, or consistent with each other.\n"
    "Rule: when both statements agree something exists but give different numbers or amounts for it "
    "(days, sizes, limits, counts, minutes, characters), the label is assumption, never contradiction.\n"
    "Severity: contradiction high, assumption medium, duplicate and unclear low. "
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


def architect_check_batch(pairs: list[tuple[str, str]]) -> list[tuple[ArchitectVerdict, str]]:
    """Architect agent on several pairs in one call (slide 11: batch to respect API limits).

    The model numbers its verdicts; if any pair is missing from the answer, that
    pair falls back to its own single call, so every pair always gets a verdict.
    """
    # One pair: a single call. Several pairs: one numbered request for all of them.
    if len(pairs) <= 1:
        return [architect_check(a, b) for a, b in pairs]
    listing = "\n\n".join(f"Pair {i}:\nStatement A: {a}\nStatement B: {b}" for i, (a, b) in enumerate(pairs, 1))

    def mock() -> dict:
        return {"verdicts": [{**heuristic_verdict(a, b).model_dump(), "pair": i}
                             for i, (a, b) in enumerate(pairs, 1)]}

    batch, src = llm.structured(
        ArchitectBatch,
        system=ARCHITECT_SYSTEM,
        user=(f"{listing}\n\nFor every pair, decide: duplicate, contradiction, assumption (people assumed "
              "different things), unclear, or none. Return one verdict per pair with its pair number, a short "
              "headline, a plain explanation, and 2-3 resolution options."),
        mock=mock,
    )
    # Match the answers back to the pairs by number; a missing one is asked again on its own.
    by_pair = {v.pair: v for v in batch.verdicts}
    out: list[tuple[ArchitectVerdict, str]] = []
    for i, (a, b) in enumerate(pairs, 1):
        v = by_pair.get(i)
        out.append((ArchitectVerdict(**v.model_dump(exclude={"pair"})), src) if v else architect_check(a, b))
    return out


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

    # Live mode: the model reads every answer side by side.
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
# Source documents: PRDs, bug tickets and meeting summaries
# ---------------------------------------------------------------------------
# Markdown headings / 'Section:' lines, and bullet or number markers at the start of a line.
_HEADING = re.compile(r"^\s*(?:#{1,6}\s|[A-Z][A-Za-z ]{0,40}:\s*$)")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def split_claims(text: str, limit: int = 25) -> list[str]:
    """Split a document into short statements the agents can compare one by one.

    Lines and bullets become statements; long lines are split into sentences.
    Headings, questions and fragments too short to mean anything are skipped.
    """
    claims: list[str] = []
    for line in text.splitlines():
        if not line.strip() or _HEADING.match(line):
            continue
        line = _BULLET.sub("", line).strip()
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            sentence = sentence.strip(" -•")
            if len(sentence) >= 20 and not sentence.endswith("?") and sentence not in claims:
                claims.append(sentence)
    return claims[:limit]


# Phrases that usually mean work is blocked ('waiting on', 'can't deploy', 'depends on').
_BLOCKER_CUE = re.compile(
    r"\b(?:block(?:ed|s|ing|er)?|waiting (?:on|for)|can(?:'|no)?t (?:start|continue|ship|merge|deploy)"
    r"|depends on|until .{3,40} (?:is|are) (?:done|ready|fixed|approved)|stuck|no access|not available"
    r"|on hold|delayed)\b", re.I)


def _mock_blockers(text: str) -> dict:
    """Demo-mode blocker finder: statements with blocking cue words."""
    found = []
    for claim in split_claims(text, limit=60):
        if _BLOCKER_CUE.search(claim):
            found.append({"statement": claim, "blocks": "",
                          "explanation": "This statement says work cannot go ahead until something else happens."})
    return {"blockers": found[:5]}


def detect_blockers(kind: str, title: str, text: str) -> tuple[BlockerList, str]:
    """PM agent: find blockers (things stopping or delaying planned work) in a source document."""
    return llm.structured(
        BlockerList,
        system=("You are the PM agent. You read a team's project document and list only real blockers: "
                "things that stop or delay planned work (missing access, waiting on another team or decision, "
                "a dependency that is not ready, an open bug that prevents release). Quote the blocking "
                "statement exactly as written. If there are none, return an empty list. Plain language."),
        user=f"Document type: {kind}\nTitle: {title}\n\n{text}\n\nList the blockers.",
        mock=lambda: _mock_blockers(text),
    )


# Keyword groups the demo-mode triage uses to pick a category and priority.
_BUG_WORDS = re.compile(r"\b(?:bug|error|crash|fail(?:s|ed|ing)?|broken|exception|wrong|cannot|can't|doesn'?t work|500|404)\b", re.I)
_FEATURE_WORDS = re.compile(r"\b(?:feature|add|support|allow|request|would like|should be able|enhance|improve)\b", re.I)
_QUESTION_WORDS = re.compile(r"\b(?:how (?:do|can|to)|is it possible|question|help|why does)\b", re.I)
_DOCS_WORDS = re.compile(r"\b(?:docs?|documentation|readme|typo|examples?|tutorial|godoc|clarify|wording)\b", re.I)
_URGENT_WORDS = re.compile(r"\b(?:crash|data loss|security|urgent|critical|production|all users|blocker|cannot (?:log ?in|pay|checkout))\b", re.I)


def _mock_triage(title: str, body: str) -> dict:
    """Demo-mode triage: keyword rules for category and priority.

    The title is the strongest signal, so it is read before the body.
    """
    text = f"{title}\n{body}"
    title_bug = _BUG_WORDS.search(title)
    title_feature = _FEATURE_WORDS.search(title) or re.match(r"\s*(?:\S+:\s*)?proposal\b", title, re.I)
    if _DOCS_WORDS.search(title):
        category = "docs"
    elif _QUESTION_WORDS.search(title) or title.strip().endswith("?"):
        category = "question"
    elif title_feature and not title_bug:
        category = "feature"
    elif title_bug or _BUG_WORDS.search(body):
        category = "bug"
    elif _FEATURE_WORDS.search(body):
        category = "feature"
    else:
        category = "bug"
    priority = "High" if _URGENT_WORDS.search(text) else ("Low" if category in ("docs", "question") else "Medium")
    hours = {"High": 6.0, "Medium": 4.0, "Low": 2.0}[priority]
    return {"category": category, "priority": priority, "estimated_hours": hours,
            "summary": _short(title or body, 120)}


def triage_issue(title: str, body: str) -> tuple[TriageResult, str]:
    """PM agent: triage a bug ticket or issue into category, priority and an hour estimate."""
    return llm.structured(
        TriageResult,
        system=("You are the PM agent triaging an incoming issue for a software team. Choose the category "
                "(bug, feature, question or docs), a priority (Low, Medium or High: High only for crashes, "
                "data loss, security or anything that stops users), an estimate in hours, and a one-line summary."),
        user=f"Title: {title}\n\n{body[:3000]}",
        mock=lambda: _mock_triage(title, body),
    )


# ---------------------------------------------------------------------------
# LangGraph pipelines
# ---------------------------------------------------------------------------
# Each graph has a State (the data passed between steps), node functions (one step
# each, returning the keys they add), and a compiled StateGraph wiring the steps in order.
# If LangGraph isn't installed, the run_* functions call the same nodes in the same order.

# Graph 1 - planning: pm_brief -> pm_tickets
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


# Build the planning graph once, when the module is imported.
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


# Graph 2 - review of a new chat message or task: retrieve -> architect
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
    matches = state.get("matches", [])
    verdicts = architect_check_batch([(state["claim"], corpus[mid]) for mid, _ in matches])
    for (mid, score), (verdict, src) in zip(matches, verdicts, strict=True):
        if verdict.kind == "none":
            continue
        # Keep only the most serious finding: contradiction > assumption > duplicate > unclear.
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


# Build the review graph once, when the module is imported.
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


# ---- Source review: PRDs, bug tickets and meeting summaries -------------------
MAX_SOURCE_CHECKS = 8     # Architect calls per document, to stay inside free-tier rate limits


# Graph 3 - source review (a PRD, bug ticket or meeting summary):
# split -> retrieve -> architect -> pm_blockers -> pm_triage
class SourceState(TypedDict, total=False):
    kind: str                         # prd | bug | meeting
    title: str
    text: str
    corpus: list[tuple[str, str]]     # (prefixed id, text): chat, other documents, tasks
    duplicate_targets: list[str]      # corpus ids a bug ticket may duplicate
    claims: list[str]
    pairs: list[tuple[str, str, float]]
    findings: list[dict]
    blockers: list[dict]
    triage: dict


def _source_min_score() -> float:
    """Embeddings and TF-IDF score on different scales, so the retrieval cut-off depends on the backend."""
    from .retrieval import backend
    return 0.45 if backend() == "embeddings" else 0.2


def _node_split(state: SourceState) -> SourceState:
    """Graph node: split the document into statements."""
    return {"claims": split_claims(state["text"])}


def _node_source_retrieve(state: SourceState) -> SourceState:
    """Graph node: pair each statement with its closest earlier statements, strongest pairs first."""
    pairs: list[tuple[str, str, float]] = []
    for claim in state.get("claims", []):
        for match_id, score in find_related(claim, state["corpus"], k=2, min_score=_source_min_score()):
            pairs.append((claim, match_id, score))
    pairs.sort(key=lambda p: -p[2])
    return {"pairs": pairs[:MAX_SOURCE_CHECKS]}


def _node_source_architect(state: SourceState) -> SourceState:
    """Graph node: the Architect checks each pair and keeps one finding per statement.

    Conflicts are always kept. Duplicates count only for bug tickets, and only
    against ids listed in `duplicate_targets` (other bug reports and fix tasks),
    because a bug in a feature is not a duplicate of the feature.
    """
    corpus = dict(state["corpus"])
    targets = set(state.get("duplicate_targets", []))
    by_claim: dict[str, dict] = {}
    pairs = state.get("pairs", [])
    verdicts = architect_check_batch([(claim, corpus[match_id]) for claim, match_id, _ in pairs])
    for (claim, match_id, score), (verdict, src) in zip(pairs, verdicts, strict=True):
        if verdict.kind == "duplicate" and not (state["kind"] == "bug" and match_id in targets):
            continue
        if verdict.kind not in ("contradiction", "assumption", "duplicate"):
            continue
        if claim in by_claim:                    # same statement, more evidence
            by_claim[claim]["match_ids"].append(match_id)
        else:
            by_claim[claim] = {**verdict.model_dump(), "claim": claim, "match_ids": [match_id],
                               "score": score, "source": src}
    return {"findings": list(by_claim.values())}


def _node_blockers(state: SourceState) -> SourceState:
    """Graph node: the PM agent lists blockers in the document."""
    found, _ = detect_blockers(state["kind"], state["title"], state["text"])
    return {"blockers": [b.model_dump() for b in found.blockers]}


def _node_triage(state: SourceState) -> SourceState:
    """Graph node: the PM agent triages a bug ticket (category, priority, hours)."""
    if state["kind"] != "bug":
        return {"triage": {}}
    result, _ = triage_issue(state["title"], state["text"])
    return {"triage": result.model_dump()}


# Build the source-review graph once, when the module is imported.
_source_graph = None
if HAS_LANGGRAPH:
    _s = StateGraph(SourceState)
    _s.add_node("split", _node_split)
    _s.add_node("retrieve", _node_source_retrieve)
    _s.add_node("architect", _node_source_architect)
    _s.add_node("pm_blockers", _node_blockers)
    _s.add_node("pm_triage", _node_triage)
    _s.set_entry_point("split")
    _s.add_edge("split", "retrieve")
    _s.add_edge("retrieve", "architect")
    _s.add_edge("architect", "pm_blockers")
    _s.add_edge("pm_blockers", "pm_triage")
    _s.add_edge("pm_triage", END)
    _source_graph = _s.compile()


def run_source_review(kind: str, title: str, text: str, corpus: list[tuple[str, str]],
                      duplicate_targets: list[str] | None = None) -> SourceState:
    """Cross-check a PRD, bug ticket or meeting summary against the chat, other sources and tasks."""
    state: SourceState = {"kind": kind, "title": title, "text": text, "corpus": corpus,
                          "duplicate_targets": duplicate_targets or []}
    if _source_graph is not None:
        return _source_graph.invoke(state)
    for node in (_node_split, _node_source_retrieve, _node_source_architect, _node_blockers, _node_triage):
        state.update(node(state))
    return state
