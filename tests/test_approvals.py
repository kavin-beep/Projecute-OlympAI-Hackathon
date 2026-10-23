"""Host approvals: brief, task assignments, AI accessibility and resolutions."""
# Each test's name states the rule it checks. Run this file alone with:
#   python -m pytest -q tests/test_approvals.py

from __future__ import annotations

from app import db
from tests.conftest import auth, login


# A member's edit turns the brief back into a draft; only the host can approve it.
def test_only_the_host_approves_the_brief(client, demo):
    member = login(client, "adrian")
    host = login(client, "kavin")
    group_id = demo["group_id"]

    client.patch(f"/api/groups/{group_id}/brief", json={"content": "# Brief\n\nDraft for the checkout work."},
                 headers=auth(member["token"]))
    assert client.get(f"/api/groups/{group_id}/workspace", headers=auth(member["token"])).json()["brief"]["status"] == "draft"

    assert client.post(f"/api/groups/{group_id}/brief/approve", headers=auth(member["token"])).status_code == 403
    assert client.post(f"/api/groups/{group_id}/brief/approve", headers=auth(host["token"])).status_code == 200

    brief = client.get(f"/api/groups/{group_id}/workspace", headers=auth(host["token"])).json()["brief"]
    assert brief["status"] == "approved"


# The PM agent proposes tasks with a valid priority and hours; only the host approves them.
def test_tasks_need_an_approved_brief_then_host_approval(client, demo):
    member = login(client, "adrian")
    host = login(client, "kavin")
    group_id = demo["group_id"]

    res = client.post(f"/api/groups/{group_id}/tickets/propose", headers=auth(member["token"]))
    assert res.status_code == 200

    tickets = client.get(f"/api/groups/{group_id}/workspace", headers=auth(member["token"])).json()["tickets"]
    assert tickets, "the PM agent should have proposed tasks"
    for t in tickets:
        assert t["priority"] in ("Low", "Medium", "High")
        assert t["estimated_hours"] > 0

    db.ex("UPDATE tickets SET status='proposed' WHERE group_id=?", (group_id,))
    assert client.post(f"/api/groups/{group_id}/tickets/approve", headers=auth(member["token"])).status_code == 403
    assert client.post(f"/api/groups/{group_id}/tickets/approve", headers=auth(host["token"])).status_code == 200

    tickets = client.get(f"/api/groups/{group_id}/workspace", headers=auth(host["token"])).json()["tickets"]
    assert all(t["status"] == "approved" for t in tickets)


# A member cannot change who owns a task; the host can.
def test_only_the_host_reassigns_a_task(client, demo):
    member = login(client, "adrian")
    host = login(client, "kavin")
    group_id = demo["group_id"]
    ticket = client.get(f"/api/groups/{group_id}/workspace", headers=auth(host["token"])).json()["tickets"][0]

    other = db.q1("SELECT id FROM users WHERE username='sritharan'")["id"]
    assert client.patch(f"/api/groups/{group_id}/tickets/{ticket['id']}",
                        json={"owner_user_id": other}, headers=auth(member["token"])).status_code == 403
    res = client.patch(f"/api/groups/{group_id}/tickets/{ticket['id']}",
                       json={"owner_user_id": other}, headers=auth(host["token"]))
    assert res.status_code == 200
    assert res.json()["ticket"]["owner_user_id"] == other


# A member's edits to title, hours or priority are refused and nothing changes.
def test_only_the_host_edits_a_task(client, demo):
    member = login(client, "adrian")
    host = login(client, "kavin")
    group_id = demo["group_id"]
    ticket = client.get(f"/api/groups/{group_id}/workspace", headers=auth(host["token"])).json()["tickets"][0]

    for patch in ({"title": "Changed by a member"}, {"estimated_hours": 99}, {"priority": "Low"}):
        assert client.patch(f"/api/groups/{group_id}/tickets/{ticket['id']}",
                            json=patch, headers=auth(member["token"])).status_code == 403
    after = client.get(f"/api/groups/{group_id}/workspace", headers=auth(host["token"])).json()["tickets"][0]
    assert (after["title"], after["estimated_hours"]) == (ticket["title"], ticket["estimated_hours"])

    res = client.patch(f"/api/groups/{group_id}/tickets/{ticket['id']}",
                       json={"priority": "High"}, headers=auth(host["token"]))
    assert res.status_code == 200


def test_demo_reset_needs_the_passcode_when_one_is_set(client, demo, monkeypatch):
    """On a public deployment a visitor cannot wipe the data without the passcode."""
    monkeypatch.setattr("scripts.seed_demo.seed", lambda full=False: {"ok": True})
    monkeypatch.setenv("DEMO_PASSCODE", "olympai")
    assert client.post("/api/demo/load", json={}).status_code == 403
    assert client.post("/api/demo/load", json={"passcode": "wrong"}).status_code == 403
    assert client.post("/api/demo/load", json={"passcode": "olympai"}).status_code == 200


# Only the host can switch AI off, and once off, members cannot use that AI mode.
def test_only_the_host_changes_ai_accessibility(client, demo):
    member = login(client, "adrian")
    host = login(client, "kavin")
    group_id, channel_id = demo["group_id"], demo["channel_id"]

    assert client.patch(f"/api/groups/{group_id}/settings", json={"allow_private_ai": False},
                        headers=auth(member["token"])).status_code == 403

    assert client.patch(f"/api/groups/{group_id}/settings", json={"allow_private_ai": False},
                        headers=auth(host["token"])).status_code == 200
    blocked = client.post(f"/api/groups/{group_id}/channels/{channel_id}/messages",
                          json={"content": "help me", "ai_mode": "private"}, headers=auth(member["token"]))
    assert blocked.status_code == 403

    client.patch(f"/api/groups/{group_id}/settings", json={"allow_public_ai": False}, headers=auth(host["token"]))
    blocked = client.post(f"/api/groups/{group_id}/channels/{channel_id}/messages",
                          json={"content": "what did we agree?", "ai_mode": "public"}, headers=auth(member["token"]))
    assert blocked.status_code == 403

    client.patch(f"/api/groups/{group_id}/settings",
                 json={"allow_public_ai": True, "allow_private_ai": True}, headers=auth(host["token"]))


# The full slide-7 flow: a conflicting message raises an alert with sources, tasks
# (each once) and impact; only the host resolves it; the decision is recorded and the
# QA agent writes acceptance criteria for the affected tasks.
def test_only_the_host_resolves_an_alert_and_qa_writes_criteria(client, demo):
    member = login(client, "adrian")
    host = login(client, "kavin")
    group_id, channel_id = demo["group_id"], demo["channel_id"]

    client.post(f"/api/groups/{group_id}/channels/{channel_id}/messages", headers=auth(member["token"]), json={
        "content": "Update from the client: every customer must log in before they can pay, "
                   "so checkout now requires an account.",
        "ai_mode": "none",
    })
    alerts = client.get(f"/api/groups/{group_id}/workspace", headers=auth(host["token"])).json()["alerts"]
    assert alerts, "the Architect agent should have flagged the new requirement"
    alert = alerts[0]
    assert alert["sources"], "every flag shows the exact source messages"
    assert alert["tickets"], "every flag lists the dependent tickets"
    assert len({t["id"] for t in alert["tickets"]}) == len(alert["tickets"]), "each ticket listed once"
    assert "Impact:" in alert["impact_label"]

    resolution = "Checkout requires an account. Add a login step before payment."
    assert client.post(f"/api/groups/{group_id}/alerts/{alert['id']}/resolve",
                       json={"resolution": resolution}, headers=auth(member["token"])).status_code == 403

    res = client.post(f"/api/groups/{group_id}/alerts/{alert['id']}/resolve",
                      json={"resolution": resolution}, headers=auth(host["token"]))
    assert res.status_code == 200
    assert res.json()["alert"]["status"] == "resolved"

    ws = client.get(f"/api/groups/{group_id}/workspace", headers=auth(member["token"])).json()
    assert any(d["content"] == resolution for d in ws["decisions"]), "the resolution is recorded as a decision"
    affected = {t["id"] for t in alert["tickets"]}
    criteria = [t for t in ws["tickets"] if t["id"] in affected and t["acceptance_criteria"]]
    assert criteria, "the QA agent drafts acceptance criteria for affected tasks"


# The impact total counts only hours the team has confirmed.
def test_confirmed_hours_drive_the_impact_sum(client, demo):
    host = login(client, "kavin")
    group_id = demo["group_id"]
    ws = client.get(f"/api/groups/{group_id}/workspace", headers=auth(host["token"])).json()
    alert = ws["alerts"][0]
    expected = sum(t["estimated_hours"] for t in alert["tickets"] if t["hours_confirmed"])
    assert abs(alert["confirmed_hours"] - round(expected, 1)) < 0.05


def test_task_edits_and_long_inputs_are_validated(client, demo):
    """Bad task edits and oversized text get a clear 400, never a crash or bad data."""
    host = login(client, "kavin")
    gid = demo["group_id"]
    ticket = client.get(f"/api/groups/{gid}/workspace", headers=auth(host["token"])).json()["tickets"][0]
    outsider = db.new_id()
    db.ex("INSERT INTO users (id, username, display_name, created_at) VALUES (?,?,?,?)",
          (outsider, f"outsider-{outsider}", "Outsider", db.now()))
    for bad in ({"estimated_hours": "abc"}, {"estimated_hours": -5}, {"estimated_hours": 1e9},
                {"priority": "Whenever"}, {"status": "exploded"}, {"owner_user_id": outsider}, {"title": "   "}):
        res = client.patch(f"/api/groups/{gid}/tickets/{ticket['id']}", json=bad, headers=auth(host["token"]))
        assert res.status_code == 400, (bad, res.text)
    after = client.get(f"/api/groups/{gid}/workspace", headers=auth(host["token"])).json()["tickets"][0]
    assert (after["title"], after["estimated_hours"], after["priority"]) == \
        (ticket["title"], ticket["estimated_hours"], ticket["priority"])

    chat = client.post("/api/chats", json={}, headers=auth(host["token"])).json()["chat"]["id"]
    res = client.post(f"/api/chats/{chat}/messages", json={"content": "x" * 5000}, headers=auth(host["token"]))
    assert res.status_code == 400 and "at most" in res.json()["detail"]
