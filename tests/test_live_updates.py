"""Live updates: both members' dashboards change over WebSockets."""
# Each test's name states the rule it checks. Run this file alone with:
#   python -m pytest -q tests/test_live_updates.py

from __future__ import annotations

import json

from tests.conftest import auth, login


def drain(ws, event_name, limit=25):
    """Read up to `limit` frames, returning the first matching event."""
    for _ in range(limit):
        try:
            frame = ws.receive_json()
        except Exception:
            return None
        if frame.get("event") == event_name:
            return frame["payload"]
    return None


# A message one member sends appears live in the other member's open window.
def test_a_group_message_reaches_the_other_member(client, demo):
    a = login(client, "adrian")
    b = login(client, "sritharan")
    group_id, channel_id = demo["group_id"], demo["channel_id"]

    with client.websocket_connect(f"/ws?token={b['token']}") as ws:
        assert ws.receive_json()["event"] == "ready"
        client.post(f"/api/groups/{group_id}/channels/{channel_id}/messages",
                    json={"content": "Pushing the address form today.", "ai_mode": "none"},
                    headers=auth(a["token"]))
        payload = drain(ws, "group_message")
        assert payload and payload["data"]["content"] == "Pushing the address form today."


# Over the live feed, others receive only the 'used AI' notice, never the content.
def test_private_help_sends_only_a_usage_notice_to_others(client, demo):
    a = login(client, "adrian")
    b = login(client, "sritharan")
    group_id, channel_id = demo["group_id"], demo["channel_id"]

    with client.websocket_connect(f"/ws?token={b['token']}") as ws:
        ws.receive_json()
        client.post(f"/api/groups/{group_id}/channels/{channel_id}/messages",
                    json={"content": "What is a webhook signature?", "ai_mode": "private"},
                    headers=auth(a["token"]))
        payload = drain(ws, "group_message")
        assert payload, "the group should be told that AI was used"
        data = payload["data"]
        assert data["kind"] == "notice"
        assert data["content"] == "Adrian Rohith used AI"
        assert "webhook" not in json.dumps(payload).lower()


# When the host resolves an alert, the member's dashboard updates without reloading.
def test_host_approval_updates_the_other_dashboard(client, demo):
    host = login(client, "kavin")
    member = login(client, "sritharan")
    group_id, channel_id = demo["group_id"], demo["channel_id"]

    # Plant a conflicting requirement so there is something to approve.
    client.post(f"/api/groups/{group_id}/channels/{channel_id}/messages", headers=auth(member["token"]), json={
        "content": "The client now says shoppers must create an account before checkout, no guest orders.",
        "ai_mode": "none",
    })
    alerts = client.get(f"/api/groups/{group_id}/workspace", headers=auth(host["token"])).json()["alerts"]
    open_alerts = [a for a in alerts if a["status"] == "open"]
    assert open_alerts, "a conflicting requirement should raise an alert"
    alert = open_alerts[0]

    with client.websocket_connect(f"/ws?token={member['token']}") as ws:
        ws.receive_json()
        client.post(f"/api/groups/{group_id}/alerts/{alert['id']}/resolve",
                    json={"resolution": "Accounts are required. Update the checkout tasks."},
                    headers=auth(host["token"]))
        payload = drain(ws, "alert")
        assert payload and payload["data"]["status"] == "resolved"

    ws_state = client.get(f"/api/groups/{group_id}/workspace", headers=auth(member["token"])).json()
    assert any(d["content"].startswith("Accounts are required") for d in ws_state["decisions"])


# Activity shows the PM, Architect and QA agents' actions.
def test_activity_timeline_records_each_agent(client, demo):
    host = login(client, "kavin")
    activity = client.get(f"/api/groups/{demo['group_id']}/workspace", headers=auth(host["token"])).json()["activity"]
    actors = {a["actor"] for a in activity}
    assert "PM agent" in actors
    assert "Architect agent" in actors
    assert "QA agent" in actors


# A WebSocket with an invalid session token is refused.
def test_a_bad_token_cannot_open_a_socket(client, demo):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws?token=nope") as ws:
        ws.receive_json()
