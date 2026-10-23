"""Cross-checking PRDs, bug tickets and meeting summaries (challenge brief), plus
task submissions, false-alert dismissal, decision impact and the event log.
"""
# Each test's name states the rule it checks. Run this file alone with:
#   python -m pytest -q tests/test_sources.py

from __future__ import annotations

from app import db
from tests.conftest import auth, login

# Sample documents (synthetic, written for these tests).
PRD = """# Checkout PRD
Goals:
- Every customer must create an account and log in before checkout.
- The checkout summary screen shows the cart total before payment."""

MEETING = """Sprint sync
- Payment step is blocked until the payment provider approves our sandbox account.
- Adrian will finish the address form this week."""

BUG = """Checkout summary screen shows the wrong cart total
The summary screen before payment shows the cart total without shipping, so the total is wrong."""

BUG_AGAIN = """Cart total on the checkout summary screen is wrong
The checkout summary screen shows a cart total that leaves out shipping before payment."""


def _add(client, token, group_id, kind, title, content):
    """Add a source document and return the response JSON."""
    res = client.post(f"/api/groups/{group_id}/documents", headers=auth(token),
                      json={"kind": kind, "title": title, "content": content})
    assert res.status_code == 200, res.text
    return res.json()


# A PRD line that contradicts the chat raises an alert quoting both, with dependent tasks.
def test_a_prd_that_contradicts_the_chat_is_flagged_with_both_sides(client, demo):
    adrian = login(client, "adrian")
    out = _add(client, adrian["token"], demo["group_id"], "prd", "Checkout PRD v2", PRD)
    conflicts = [a for a in out["alerts"] if a["kind"] == "contradiction"]
    assert conflicts, out["alerts"]
    kinds = {s["kind"] for s in conflicts[0]["sources"]}
    assert kinds == {"document", "message"}            # the PRD line and the chat it contradicts
    doc_quote = next(s for s in conflicts[0]["sources"] if s["kind"] == "document")
    assert "log in before checkout" in doc_quote["content"]
    assert conflicts[0]["tickets"]                       # dependent tasks are listed


# A 'blocked until ...' line in a meeting summary becomes one high-severity blocker alert.
def test_a_meeting_summary_blocker_is_flagged(client, demo):
    sritharan = login(client, "sritharan")
    out = _add(client, sritharan["token"], demo["group_id"], "meeting", "Sprint sync", MEETING)
    blockers = [a for a in out["alerts"] if a["kind"] == "blocker"]
    assert len(blockers) == 1
    assert "sandbox account" in blockers[0]["sources"][0]["content"]
    assert blockers[0]["severity"] == "high"


# A bug ticket becomes a proposed Fix task; a reworded repeat is flagged once as a
# duplicate and adds no second task.
def test_a_bug_is_triaged_into_a_task_and_a_repeat_report_is_a_duplicate(client, demo):
    adrian = login(client, "adrian")
    gid = demo["group_id"]
    first = _add(client, adrian["token"], gid, "bug", "Wrong total on summary", BUG)
    assert first["document"]["triage"]["category"] == "bug"
    tasks = client.get(f"/api/groups/{gid}/workspace", headers=auth(adrian["token"])).json()["tickets"]
    fix = [t for t in tasks if t["title"] == "Fix: Wrong total on summary"]
    assert fix and fix[0]["status"] == "proposed"        # the host still approves it

    again = _add(client, adrian["token"], gid, "bug", "Summary total missing shipping", BUG_AGAIN)
    dups = [a for a in again["alerts"] if a["kind"] == "duplicate"]
    assert len(dups) == 1                                # one flag per repeated report
    tasks = client.get(f"/api/groups/{gid}/workspace", headers=auth(adrian["token"])).json()["tickets"]
    assert not any(t["title"] == "Fix: Summary total missing shipping" for t in tasks)


# Bad document input is refused, and non-members can neither add nor list sources.
def test_sources_are_members_only_and_validated(client, demo):
    adrian = login(client, "adrian")
    gid = demo["group_id"]
    assert client.post(f"/api/groups/{gid}/documents", headers=auth(adrian["token"]),
                       json={"kind": "novel", "title": "x", "content": "y" * 30}).status_code == 400
    assert client.post("/api/groups/not-mine/documents", headers=auth(adrian["token"]),
                       json={"kind": "prd", "title": "x", "content": "y" * 30}).status_code == 403
    assert client.get("/api/groups/not-mine/documents", headers=auth(adrian["token"])).status_code == 403


# Any member can submit a task (it waits for the host); a near-copy is flagged as a duplicate.
def test_a_member_submits_a_task_and_a_duplicate_submission_is_flagged(client, demo):
    adrian = login(client, "adrian")
    gid = demo["group_id"]
    existing = client.get(f"/api/groups/{gid}/workspace", headers=auth(adrian["token"])).json()["tickets"][0]
    res = client.post(f"/api/groups/{gid}/tickets", headers=auth(adrian["token"]),
                      json={"title": existing["title"], "detail": existing["detail"], "priority": "High",
                            "estimated_hours": 3})
    assert res.status_code == 200
    assert res.json()["ticket"]["status"] == "proposed"
    alerts = client.get(f"/api/groups/{gid}/workspace", headers=auth(adrian["token"])).json()["alerts"]
    assert any(a["kind"] == "duplicate" and any(s["kind"] == "ticket" for s in a["sources"])
               for a in alerts)


# Only the host can dismiss a false alert; no decision is recorded and it stays closed.
def test_only_the_host_dismisses_a_false_alert_and_no_decision_is_recorded(client, demo):
    host, member = login(client, "kavin"), login(client, "adrian")
    gid = demo["group_id"]
    ws = client.get(f"/api/groups/{gid}/workspace", headers=auth(host["token"])).json()
    alert = next(a for a in ws["alerts"] if a["status"] == "open")
    decisions_before = len(ws["decisions"])
    assert client.post(f"/api/groups/{gid}/alerts/{alert['id']}/dismiss",
                       headers=auth(member["token"]), json={}).status_code == 403
    res = client.post(f"/api/groups/{gid}/alerts/{alert['id']}/dismiss", headers=auth(host["token"]),
                      json={"reason": "Same wording, no real conflict"})
    assert res.json()["alert"]["status"] == "dismissed"
    ws = client.get(f"/api/groups/{gid}/workspace", headers=auth(host["token"])).json()
    assert len(ws["decisions"]) == decisions_before
    assert client.post(f"/api/groups/{gid}/alerts/{alert['id']}/resolve", headers=auth(host["token"]),
                       json={"resolution": "x"}).status_code == 400   # closed alerts stay closed


# Decision impact: a resolved alert's decision lists exactly the alert's tasks.
def test_a_decision_lists_the_tasks_it_changes(client, demo):
    host = login(client, "kavin")
    gid = demo["group_id"]
    ws = client.get(f"/api/groups/{gid}/workspace", headers=auth(host["token"])).json()
    alert = next(a for a in ws["alerts"] if a["status"] == "open" and a["tickets"])
    client.post(f"/api/groups/{gid}/alerts/{alert['id']}/resolve", headers=auth(host["token"]),
                json={"resolution": "Accounts are required; guest checkout is dropped."})
    decision = client.get(f"/api/groups/{gid}/workspace", headers=auth(host["token"])).json()["decisions"][0]
    assert {t["id"] for t in decision["tickets"]} == {t["id"] for t in alert["tickets"]}


# The event log downloads as a JSON file with every agent action, for members only.
def test_the_event_log_downloads_for_members_only(client, demo):
    member = login(client, "sritharan")
    gid = demo["group_id"]
    res = client.get(f"/api/groups/{gid}/activity/export", headers=auth(member["token"]))
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    events = res.json()["events"]
    assert any(e["actor"] == "Architect agent" for e in events)
    assert any(e["actor"] == "PM agent" for e in events)
    assert client.get("/api/groups/not-mine/activity/export", headers=auth(member["token"])).status_code == 403
    assert db.q1("SELECT COUNT(*) AS n FROM activity WHERE group_id=?", (gid,))["n"] == len(events)
