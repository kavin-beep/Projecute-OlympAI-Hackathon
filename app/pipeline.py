"""Group pipeline: brief -> tickets -> conflict review -> decision -> QA.

Pure(ish) functions over the database. They return the events the caller should
broadcast over WebSockets, so the HTTP layer stays thin.
"""
from __future__ import annotations

import json
from typing import Any

from . import agents, db
from .schemas import BriefDraft

Event = tuple[str, Any]


# ---------------------------------------------------------------- lookups
def members_of(group_id: str) -> list[str]:
    """User ids of everyone in the group."""
    return [r["user_id"] for r in db.q("SELECT user_id FROM group_members WHERE group_id=?", (group_id,))]


def user_name(user_id: str | None) -> str:
    """Display name for a user id ('' if unknown)."""
    if not user_id:
        return ""
    row = db.q1("SELECT display_name FROM users WHERE id=?", (user_id,))
    return row["display_name"] if row else ""


def chat_corpus(group_id: str, exclude_id: str | None = None) -> list[tuple[str, str]]:
    """(id, text) of every user message in the group, for related-claim search."""
    rows = db.q(
        "SELECT id, content FROM group_messages WHERE group_id=? AND kind='user' ORDER BY created_at",
        (group_id,),
    )
    return [(r["id"], r["content"]) for r in rows if r["id"] != exclude_id]


_QUESTION_START = ("what", "why", "how", "who", "when", "where", "which", "do we", "should we",
                   "can we", "is it", "are we", "did we", "does it", "any chance", "anyone")


def _is_question(text: str) -> bool:
    """Questions are not claims about the plan, so they are not reviewed."""
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    return stripped.lower().startswith(_QUESTION_START)


def busiest_channel(group_id: str) -> str | None:
    """The channel with the most messages; the PM agent reads this one."""
    row = db.q1(
        "SELECT channel_id, COUNT(*) AS n FROM group_messages WHERE group_id=? AND kind='user'"
        " GROUP BY channel_id ORDER BY n DESC LIMIT 1", (group_id,))
    return row["channel_id"] if row else None


def group_messages(group_id: str, channel_id: str | None = None) -> list[dict]:
    """User messages of a group (optionally one channel), oldest first."""
    sql = ("SELECT m.id, m.content, m.created_at, u.display_name AS author"
           " FROM group_messages m LEFT JOIN users u ON u.id=m.user_id"
           " WHERE m.group_id=? AND m.kind='user'")
    params: list[object] = [group_id]
    if channel_id:
        sql += " AND m.channel_id=?"
        params.append(channel_id)
    rows = db.q(sql + " ORDER BY m.created_at", params)
    return [{"id": r["id"], "content": r["content"], "author": r["author"] or "Someone",
             "created_at": r["created_at"], "kind": "user"} for r in rows]


# ---------------------------------------------------------------- serialise
def serialize_ticket(row) -> dict:
    """A ticket row plus owner name and parsed acceptance criteria."""
    t = dict(row)
    t["owner_name"] = user_name(t.get("owner_user_id"))
    t["acceptance_criteria"] = json.loads(t["acceptance_criteria"]) if t.get("acceptance_criteria") else []
    return t


def serialize_alert(alert_row, *, full: bool = False) -> dict:
    """An alert with its source messages, each affected task once, and the hours impact."""
    a = dict(alert_row)
    a["options"] = json.loads(a["options"]) if a.get("options") else []
    a["resolved_by_name"] = user_name(a.get("resolved_by"))
    sources = db.q(
        "SELECT m.id, m.content, m.created_at, u.display_name AS author"
        " FROM alert_sources s JOIN group_messages m ON m.id=s.message_id"
        " LEFT JOIN users u ON u.id=m.user_id WHERE s.alert_id=? ORDER BY m.created_at",
        (a["id"],),
    )
    a["sources"] = [dict(r) for r in sources]
    tickets = db.q(
        "SELECT t.* FROM alert_tickets at JOIN tickets t ON t.id=at.ticket_id"
        " WHERE at.alert_id=? ORDER BY t.key",
        (a["id"],),
    )
    seen: set[str] = set()
    unique: list[dict] = []
    for row in tickets:                       # each affected ticket listed once
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        unique.append(serialize_ticket(row))
    a["tickets"] = unique
    a["confirmed_hours"] = round(sum(t["estimated_hours"] for t in unique if t["hours_confirmed"]), 1)
    a["unconfirmed_count"] = sum(1 for t in unique if not t["hours_confirmed"])
    a["impact_label"] = _impact_label(unique, a["confirmed_hours"], a["unconfirmed_count"])
    return a


def _impact_label(tickets: list[dict], hours: float, unconfirmed: int) -> str:
    """Plain-language impact line, e.g. 'Impact: 4 tasks, about 20 hours'."""
    if not tickets:
        return "Impact: no tasks affected yet"
    n = len(tickets)
    task_word = "task" if n == 1 else "tasks"
    if hours <= 0:
        return f"Impact: {n} {task_word}, hours not confirmed yet"
    tail = f", {unconfirmed} estimate{'s' if unconfirmed != 1 else ''} not confirmed" if unconfirmed else ""
    return f"Impact: {n} {task_word}, about {hours:g} hours{tail}"


def workspace_state(group_id: str) -> dict:
    """Everything the group workspace shows, in one dict."""
    brief = db.q1("SELECT * FROM briefs WHERE group_id=? ORDER BY created_at DESC LIMIT 1", (group_id,))
    tickets = [serialize_ticket(r) for r in db.q("SELECT * FROM tickets WHERE group_id=? ORDER BY key", (group_id,))]
    alerts = [serialize_alert(r) for r in db.q(
        "SELECT * FROM alerts WHERE group_id=? ORDER BY (status='open') DESC, created_at DESC", (group_id,))]
    decisions = db.rows_to_dicts(db.q("SELECT * FROM decisions WHERE group_id=? ORDER BY created_at DESC", (group_id,)))
    for d in decisions:
        d["decided_by_name"] = user_name(d.get("decided_by"))
    activity = db.rows_to_dicts(db.q(
        "SELECT * FROM activity WHERE group_id=? ORDER BY created_at DESC LIMIT 80", (group_id,)))
    outputs = db.rows_to_dicts(db.q(
        "SELECT i.id, i.name, i.kind, i.body, i.language, i.data_url, i.generator, i.created_at,"
        " u.display_name AS owner_name FROM items i JOIN users u ON u.id=i.owner_user_id"
        " WHERE i.shared_group_id=? ORDER BY i.created_at DESC", (group_id,)))
    futures = db.rows_to_dicts(db.q("SELECT * FROM futures WHERE group_id=? ORDER BY created_at DESC", (group_id,)))
    for f in futures:
        f["answers"] = db.rows_to_dicts(db.q(
            "SELECT fa.*, u.display_name AS author FROM future_answers fa JOIN users u ON u.id=fa.user_id"
            " WHERE fa.future_id=? ORDER BY fa.created_at", (f["id"],)))
        f["comparison"] = json.loads(f["comparison"]) if f.get("comparison") else None
    unit_tests = db.rows_to_dicts(db.q(
        "SELECT * FROM unit_tests WHERE group_id=? ORDER BY created_at DESC", (group_id,)))
    for u in unit_tests:
        u["comparison"] = json.loads(u["comparison"]) if u.get("comparison") else None
        u["creator_name"] = user_name(u["creator_user_id"])
        u["assignee_name"] = user_name(u.get("assignee_user_id"))
    return {
        "brief": dict(brief) if brief else None,
        "tickets": tickets,
        "alerts": alerts,
        "decisions": decisions,
        "activity": activity,
        "outputs": outputs,
        "futures": futures,
        "unit_tests": unit_tests,
        "counts": {
            "brief": 1 if brief else 0,
            "tickets": len(tickets),
            "decisions": len(decisions),
            "alerts": sum(1 for a in alerts if a["status"] == "open"),
            "activity": len(activity),
            "outputs": len(outputs),
        },
    }


# ---------------------------------------------------------------- PM agent
def extract_brief(group_id: str, actor_user_id: str, channel_id: str | None = None) -> tuple[dict, list[Event]]:
    """PM agent: draft (or redraft) the brief from the busiest channel."""
    msgs = group_messages(group_id, channel_id or busiest_channel(group_id))
    if not msgs:
        raise ValueError("There are no group messages to read yet.")
    state = agents.run_plan_pipeline(msgs, [user_name(u) for u in members_of(group_id)])
    draft = BriefDraft.model_validate(state["brief"])
    content = draft.to_markdown()
    existing = db.q1("SELECT * FROM briefs WHERE group_id=? ORDER BY created_at DESC LIMIT 1", (group_id,))
    ts = db.now()
    if existing and existing["status"] != "approved":
        db.ex("UPDATE briefs SET content=?, updated_at=? WHERE id=?", (content, ts, existing["id"]))
        bid = existing["id"]
    else:
        bid = db.new_id()
        db.ex("INSERT INTO briefs (id, group_id, content, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
              (bid, group_id, content, "draft", ts, ts))
    act = db.log_activity(group_id, "PM agent", "Drafted the project brief",
                          f"Read {len(msgs)} messages from the group chat", ref_kind="brief", ref_id=bid)
    # Stash the proposed tickets so the host can approve them after the brief.
    _stash_proposals(group_id, state.get("tickets", []))
    brief = dict(db.q1("SELECT * FROM briefs WHERE id=?", (bid,)))
    return brief, [("brief", brief), ("activity", act)]


_proposal_cache: dict[str, list[dict]] = {}


def _stash_proposals(group_id: str, tickets: list[dict]) -> None:
    """Keep the tickets drafted with the brief until the host approves it."""
    if tickets:
        _proposal_cache[group_id] = tickets


def approve_brief(group_id: str, host_user_id: str) -> tuple[dict, list[Event]]:
    """Mark the latest brief approved by the host."""
    brief = db.q1("SELECT * FROM briefs WHERE group_id=? ORDER BY created_at DESC LIMIT 1", (group_id,))
    if not brief:
        raise ValueError("There is no brief to approve yet.")
    db.ex("UPDATE briefs SET status='approved', approved_by=?, updated_at=? WHERE id=?",
          (host_user_id, db.now(), brief["id"]))
    act = db.log_activity(group_id, user_name(host_user_id), "Approved the project brief",
                          actor_kind="user", ref_kind="brief", ref_id=brief["id"])
    out = dict(db.q1("SELECT * FROM briefs WHERE id=?", (brief["id"],)))
    return out, [("brief", out), ("activity", act)]


def update_brief(group_id: str, content: str, actor_user_id: str) -> tuple[dict, list[Event]]:
    """Save an edited brief; it returns to draft until the host approves again."""
    brief = db.q1("SELECT * FROM briefs WHERE group_id=? ORDER BY created_at DESC LIMIT 1", (group_id,))
    ts = db.now()
    if not brief:
        bid = db.new_id()
        db.ex("INSERT INTO briefs (id, group_id, content, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
              (bid, group_id, content, "draft", ts, ts))
    else:
        bid = brief["id"]
        db.ex("UPDATE briefs SET content=?, status='draft', approved_by=NULL, updated_at=? WHERE id=?",
              (content, ts, bid))
    act = db.log_activity(group_id, user_name(actor_user_id), "Edited the project brief",
                          actor_kind="user", ref_kind="brief", ref_id=bid)
    out = dict(db.q1("SELECT * FROM briefs WHERE id=?", (bid,)))
    return out, [("brief", out), ("activity", act)]


def propose_tickets(group_id: str) -> tuple[list[dict], list[Event]]:
    """Create proposed tickets (skipping near-duplicates) and suggest owners."""
    brief = db.q1("SELECT * FROM briefs WHERE group_id=? ORDER BY created_at DESC LIMIT 1", (group_id,))
    if not brief or brief["status"] != "approved":
        raise ValueError("The host needs to approve the brief first.")
    msgs = group_messages(group_id, busiest_channel(group_id))
    member_ids = members_of(group_id)
    names = {user_name(u): u for u in member_ids}
    proposals = _proposal_cache.pop(group_id, None)
    if proposals is None:
        ts_set, _ = agents.propose_tickets(brief["content"], msgs, list(names))
        proposals = [t.model_dump() for t in ts_set.tickets]

    existing = db.q("SELECT key, title FROM tickets WHERE group_id=?", (group_id,))
    start = len(existing) + 1
    created: list[dict] = []
    ts = db.now()
    for i, p in enumerate(proposals):
        if any(agents.similarity(p["title"], e["title"]) > 0.8 for e in existing):
            continue
        tid = db.new_id()
        owner = names.get(p.get("owner_hint", ""), None)
        if owner is None and member_ids:
            owner = member_ids[(start + i - 1) % len(member_ids)]
        db.ex(
            "INSERT INTO tickets (id, group_id, key, title, detail, priority, estimated_hours,"
            " owner_user_id, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (tid, group_id, f"T-{start + i}", p["title"][:140], p.get("detail", ""),
             p.get("priority", "Medium"), float(p.get("estimated_hours", 4)), owner, "proposed", ts, ts),
        )
        created.append(serialize_ticket(db.q1("SELECT * FROM tickets WHERE id=?", (tid,))))
    act = db.log_activity(group_id, "PM agent", f"Proposed {len(created)} tasks",
                          "Each has a priority, an estimate and a suggested owner", ref_kind="tickets", ref_id=None)
    return created, [("tickets", workspace_state(group_id)["tickets"]), ("activity", act)]


def approve_assignments(group_id: str, host_user_id: str) -> tuple[list[dict], list[Event]]:
    """Host approves every proposed ticket and its owner."""
    rows = db.q("SELECT id FROM tickets WHERE group_id=? AND status='proposed'", (group_id,))
    ts = db.now()
    for r in rows:
        db.ex("UPDATE tickets SET status='approved', updated_at=? WHERE id=?", (ts, r["id"]))
    act = db.log_activity(group_id, user_name(host_user_id), f"Approved {len(rows)} task assignments",
                          actor_kind="user", ref_kind="tickets")
    tickets = workspace_state(group_id)["tickets"]
    return tickets, [("tickets", tickets), ("activity", act)]


# ------------------------------------------------- Architect agent / alerts
def scan_message(group_id: str, message_id: str) -> tuple[dict | None, list[Event]]:
    """Run retrieval + Architect over one new message. Returns a new alert, if any."""
    msg = db.q1("SELECT * FROM group_messages WHERE id=? AND kind='user'", (message_id,))
    if not msg:
        return None, []
    if db.q1("SELECT 1 FROM alert_sources WHERE message_id=?", (message_id,)):
        return None, []
    if _is_question(msg["content"]):
        return None, []        # a question is not a claim about the plan
    corpus = chat_corpus(group_id, exclude_id=message_id)
    if not corpus:
        return None, []
    state = agents.run_review_pipeline(msg["content"], corpus)
    verdict = state.get("verdict") or {}
    if not verdict or verdict.get("kind") in (None, "none"):
        return None, []

    aid = db.new_id()
    ts = db.now()
    db.ex(
        "INSERT INTO alerts (id, group_id, kind, severity, headline, explanation, status, options, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, group_id, verdict["kind"], verdict.get("severity", "medium"), verdict["headline"],
         verdict.get("explanation", ""), "open", json.dumps(verdict.get("options", [])), ts),
    )
    db.exmany("INSERT OR IGNORE INTO alert_sources (alert_id, message_id) VALUES (?,?)",
              [(aid, message_id), (aid, verdict["match_id"])])

    # Dependent tickets: retrieved against both source messages, each listed once.
    tickets = db.q("SELECT id, title, detail FROM tickets WHERE group_id=?", (group_id,))
    corpus_t = [(t["id"], f"{t['title']} {t['detail']}") for t in tickets]
    hits: dict[str, float] = {}
    other = db.q1("SELECT content FROM group_messages WHERE id=?", (verdict["match_id"],))
    for claim in (msg["content"], other["content"] if other else ""):
        for tid, score in agents.find_related(claim, corpus_t, k=5, min_score=0.12):
            hits[tid] = max(hits.get(tid, 0.0), score)
    db.exmany("INSERT OR IGNORE INTO alert_tickets (alert_id, ticket_id) VALUES (?,?)",
              [(aid, tid) for tid in hits])

    alert = serialize_alert(db.q1("SELECT * FROM alerts WHERE id=?", (aid,)))
    act = db.log_activity(group_id, "Architect agent", alert["headline"],
                          alert["impact_label"], ref_kind="alert", ref_id=aid)
    return alert, [("alert", alert), ("activity", act)]


def resolve_alert(group_id: str, alert_id: str, host_user_id: str, resolution: str) -> tuple[dict, list[Event]]:
    """Record the host's resolution as a decision, then have QA write acceptance criteria."""
    row = db.q1("SELECT * FROM alerts WHERE id=? AND group_id=?", (alert_id, group_id))
    if not row:
        raise ValueError("That alert no longer exists.")
    if row["status"] == "resolved":
        raise ValueError("That alert is already resolved.")
    ts = db.now()
    db.ex("UPDATE alerts SET status='resolved', resolution=?, resolved_by=?, resolved_at=? WHERE id=?",
          (resolution, host_user_id, ts, alert_id))

    alert = serialize_alert(db.q1("SELECT * FROM alerts WHERE id=?", (alert_id,)))
    did = db.new_id()
    db.ex("INSERT INTO decisions (id, group_id, title, content, alert_id, decided_by, created_at)"
          " VALUES (?,?,?,?,?,?,?)",
          (did, group_id, alert["headline"], resolution, alert_id, host_user_id, ts))
    events: list[Event] = [("alert", alert)]
    acts = [db.log_activity(group_id, user_name(host_user_id), "Approved a resolution",
                            resolution, actor_kind="user", ref_kind="decision", ref_id=did)]

    # QA agent drafts acceptance criteria for every affected ticket.
    for t in alert["tickets"]:
        criteria, _ = agents.acceptance_criteria(t["title"], t["detail"], resolution)
        db.ex("UPDATE tickets SET acceptance_criteria=?, status=CASE WHEN status='proposed' THEN 'proposed'"
              " ELSE 'approved' END, updated_at=? WHERE id=?",
              (json.dumps(criteria.criteria), db.now(), t["id"]))
    if alert["tickets"]:
        acts.append(db.log_activity(
            group_id, "QA agent", f"Wrote acceptance criteria for {len(alert['tickets'])} task(s)",
            "Based on the approved decision", ref_kind="tickets"))

    state = workspace_state(group_id)
    events.append(("tickets", state["tickets"]))
    events.append(("decisions", state["decisions"]))
    for a in acts:
        events.append(("activity", a))
    return alert, events


def confirm_hours(group_id: str, ticket_id: str, user_id: str) -> tuple[dict, list[Event]]:
    """Mark a ticket's estimate as team-confirmed."""
    row = db.q1("SELECT * FROM tickets WHERE id=? AND group_id=?", (ticket_id, group_id))
    if not row:
        raise ValueError("That task no longer exists.")
    db.ex("UPDATE tickets SET hours_confirmed=1, updated_at=? WHERE id=?", (db.now(), ticket_id))
    ticket = serialize_ticket(db.q1("SELECT * FROM tickets WHERE id=?", (ticket_id,)))
    act = db.log_activity(group_id, user_name(user_id), f"Confirmed the estimate for {ticket['key']}",
                          f"{ticket['estimated_hours']:g} hours", actor_kind="user",
                          ref_kind="ticket", ref_id=ticket_id)
    state = workspace_state(group_id)
    return ticket, [("tickets", state["tickets"]), ("alerts", state["alerts"]), ("activity", act)]


def update_ticket(group_id: str, ticket_id: str, patch: dict, user_id: str) -> tuple[dict, list[Event]]:
    """Apply the host's edits to a ticket; changing hours clears the confirmation."""
    row = db.q1("SELECT * FROM tickets WHERE id=? AND group_id=?", (ticket_id, group_id))
    if not row:
        raise ValueError("That task no longer exists.")
    fields, values = [], []
    for col in ("title", "detail", "priority", "status", "owner_user_id"):
        if col in patch and patch[col] is not None:
            fields.append(f"{col}=?")
            values.append(patch[col])
    if "estimated_hours" in patch and patch["estimated_hours"] is not None:
        fields += ["estimated_hours=?", "hours_confirmed=0"]
        values.append(float(patch["estimated_hours"]))
    if not fields:
        return serialize_ticket(row), []
    values += [db.now(), ticket_id]
    db.ex(f"UPDATE tickets SET {', '.join(fields)}, updated_at=? WHERE id=?", values)
    ticket = serialize_ticket(db.q1("SELECT * FROM tickets WHERE id=?", (ticket_id,)))
    act = db.log_activity(group_id, user_name(user_id), f"Updated {ticket['key']}",
                          ticket["title"], actor_kind="user", ref_kind="ticket", ref_id=ticket_id)
    state = workspace_state(group_id)
    return ticket, [("tickets", state["tickets"]), ("alerts", state["alerts"]), ("activity", act)]
