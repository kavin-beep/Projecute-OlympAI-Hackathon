"""Privacy rules from slide 12, enforced in the backend.

User A can never read B's individual chats, workspace items or private AI help,
and individual content only enters a group through explicit sharing.
"""
# Each test's name states the rule it checks. Run this file alone with:
#   python -m pytest -q tests/test_privacy.py

from __future__ import annotations

from tests.conftest import auth, login


def test_individual_chat_is_private(client, demo):
    a = login(client, "adrian")
    b = login(client, "sritharan")

    chat = client.post("/api/chats", json={"title": "Adrian's notes"}, headers=auth(a["token"])).json()["chat"]
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "a private thought"}, headers=auth(a["token"]))

    assert client.get(f"/api/chats/{chat['id']}", headers=auth(a["token"])).status_code == 200
    assert client.get(f"/api/chats/{chat['id']}", headers=auth(b["token"])).status_code == 404

    listed = client.get("/api/chats", headers=auth(b["token"])).json()["chats"]
    assert all(c["id"] != chat["id"] for c in listed)


def test_other_user_cannot_rename_or_delete_a_chat(client, demo):
    a = login(client, "adrian")
    b = login(client, "sritharan")
    chat = client.post("/api/chats", json={"title": "mine"}, headers=auth(a["token"])).json()["chat"]

    assert client.patch(f"/api/chats/{chat['id']}", json={"title": "hijacked"}, headers=auth(b["token"])).status_code == 404
    assert client.delete(f"/api/chats/{chat['id']}", headers=auth(b["token"])).status_code == 404
    assert client.get(f"/api/chats/{chat['id']}", headers=auth(a["token"])).json()["chat"]["title"] == "mine"


def test_workspace_item_is_private_until_shared(client, demo):
    a = login(client, "adrian")
    b = login(client, "sritharan")
    group_id = demo["group_id"]

    item = client.post("/api/items/generate", headers=auth(a["token"]), json={
        "name": "Checkout copy", "kind": "content", "prompt": "Write two lines about guest checkout.",
    }).json()["item"]

    assert client.get(f"/api/items/{item['id']}", headers=auth(b["token"])).status_code == 404
    assert all(i["id"] != item["id"] for i in client.get("/api/items", headers=auth(b["token"])).json()["items"])

    workspace = client.get(f"/api/groups/{group_id}/workspace", headers=auth(b["token"])).json()
    assert all(o["id"] != item["id"] for o in workspace["outputs"])

    client.post(f"/api/items/{item['id']}/share", json={"group_id": group_id}, headers=auth(a["token"]))

    assert client.get(f"/api/items/{item['id']}", headers=auth(b["token"])).status_code == 200
    workspace = client.get(f"/api/groups/{group_id}/workspace", headers=auth(b["token"])).json()
    assert any(o["id"] == item["id"] for o in workspace["outputs"])

    # ...and it can be made private again.
    client.post(f"/api/items/{item['id']}/unshare", headers=auth(a["token"]))
    assert client.get(f"/api/items/{item['id']}", headers=auth(b["token"])).status_code == 404


def test_item_cannot_be_shared_into_a_group_you_are_not_in(client, demo):
    a = login(client, "adrian")
    item = client.post("/api/items/generate", headers=auth(a["token"]), json={
        "name": "Private note", "kind": "content", "prompt": "One line.",
    }).json()["item"]
    res = client.post(f"/api/items/{item['id']}/share", json={"group_id": "not-a-real-group"}, headers=auth(a["token"]))
    assert res.status_code == 403


def test_private_ai_help_stays_with_the_asker(client, demo):
    a = login(client, "adrian")
    b = login(client, "sritharan")
    group_id, channel_id = demo["group_id"], demo["channel_id"]

    secret = "Explain idempotency keys to me, I do not want to ask the others."
    res = client.post(f"/api/groups/{group_id}/channels/{channel_id}/messages", headers=auth(a["token"]),
                      json={"content": secret, "ai_mode": "private"}).json()
    assert res["private_help"]["answer"]
    assert res["notice"]["kind"] == "notice"
    assert res["notice"]["content"] == "Adrian Rohith used AI"

    # The group only sees the usage notice: no prompt, no answer, no topic.
    messages = client.get(f"/api/groups/{group_id}/channels/{channel_id}/messages",
                          headers=auth(b["token"])).json()["messages"]
    blob = " ".join(m["content"] for m in messages)
    assert "idempotency" not in blob.lower()
    assert secret not in blob
    assert res["private_help"]["answer"] not in blob
    assert "Adrian Rohith used AI" in blob

    # And the help itself is only readable by the asker.
    assert any(h["id"] == res["private_help"]["id"]
               for h in client.get(f"/api/groups/{group_id}/private-help", headers=auth(a["token"])).json()["help"])
    assert all(h["id"] != res["private_help"]["id"]
               for h in client.get(f"/api/groups/{group_id}/private-help", headers=auth(b["token"])).json()["help"])


def test_non_members_cannot_read_a_group(client, demo):
    a = login(client, "adrian")
    headers = auth(a["token"])
    # Adrian is a member of the demo group, so use an id that belongs to nobody.
    assert client.get("/api/groups/unknown-group", headers=headers).status_code == 403
    assert client.get("/api/groups/unknown-group/workspace", headers=headers).status_code == 403


def _other_group_with_a_message() -> tuple[str, str, str]:
    """A second group the demo members are not in, with one message in it."""
    from app import db

    host = db.q1("SELECT id FROM users WHERE username='kavin'")["id"]
    gid, cid, mid, ts = db.new_id(), db.new_id(), db.new_id(), db.now()
    db.ex("INSERT INTO groups (id, name, host_user_id, created_at) VALUES (?,?,?,?)", (gid, "Other team", host, ts))
    db.ex("INSERT INTO group_members (group_id, user_id, role) VALUES (?,?,?)", (gid, host, "host"))
    db.ex("INSERT INTO channels (id, group_id, name) VALUES (?,?,?)", (cid, gid, "plans"))
    db.ex("INSERT INTO group_messages (id, channel_id, group_id, user_id, kind, content, created_at)"
          " VALUES (?,?,?,?,?,?,?)", (mid, cid, gid, host, "user", "other team's private plan", ts))
    return gid, cid, mid


def test_other_groups_messages_stay_out_of_reach(client, demo):
    """Being in one group must not open another group's channels or messages."""
    a = login(client, "adrian")
    headers = auth(a["token"])
    group_id, channel_id = demo["group_id"], demo["channel_id"]
    _, other_channel, other_message = _other_group_with_a_message()

    res = client.get(f"/api/groups/{group_id}/channels/{other_channel}/messages", headers=headers)
    assert res.status_code == 404
    assert "other team" not in res.text

    res = client.post(f"/api/groups/{group_id}/messages/{other_message}/reactions",
                      json={"emoji": "👍"}, headers=headers)
    assert res.status_code == 404
    assert "other team" not in res.text

    res = client.post(f"/api/groups/{group_id}/channels/{channel_id}/messages", headers=headers,
                      json={"content": "replying across groups", "reply_to_id": other_message})
    assert res.status_code == 404


def test_reacting_to_a_missing_message_is_a_404(client, demo):
    a = login(client, "adrian")
    res = client.post(f"/api/groups/{demo['group_id']}/messages/not-a-message/reactions",
                      json={"emoji": "👍"}, headers=auth(a["token"]))
    assert res.status_code == 404


def test_requests_without_a_session_are_rejected(client, demo):
    assert client.get("/api/chats").status_code == 401
    assert client.get("/api/items").status_code == 401
    assert client.get(f"/api/groups/{demo['group_id']}/workspace").status_code == 401
    assert client.get("/api/chats", headers=auth("made-up-token")).status_code == 401


def test_group_ai_only_reads_this_group(client, demo):
    """The group assistant is given this group's messages and nothing else."""
    from app import main

    a = login(client, "adrian")
    group_id = demo["group_id"]
    context = main._group_context(group_id)

    private_chat = client.post("/api/chats", json={"title": "solo"}, headers=auth(a["token"])).json()["chat"]
    client.post(f"/api/chats/{private_chat['id']}/messages", headers=auth(a["token"]),
                json={"content": "zebra-coloured unicorn protocol"})

    assert "zebra-coloured unicorn protocol" not in main._group_context(group_id)
    assert "guest checkout" in context.lower()
