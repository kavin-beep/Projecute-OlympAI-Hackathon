"""Seed the slide-10 demo.

Default: resets the database and stages the demo up to the point where the
brief is approved, tasks exist and estimates are confirmed — so the conflict,
the host's approval and the live dashboard update happen in front of the
judges, in two browser windows.

  python -m scripts.seed_demo            # stage the demo (what "Load demo" does)
  python -m scripts.seed_demo --full     # also run the conflict and resolution

All demo text is synthetic and written for this prototype.
"""
from __future__ import annotations

import os
import sys

# Make the project folder importable, so `from app import ...` works when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, pipeline  # noqa: E402

# ---------------------------------------------------------------- demo content
# The team: (username, display name, colour, role). Kavin is the host.
MEMBERS = [
    ("kavin", "Kavin K", "#6b8afd", "host"),
    ("adrian", "Adrian Rohith", "#4fcf9b", "member"),
    ("sritharan", "Sritharan N S", "#f0a84a", "member"),
]

# The chat the PM agent turns into the brief: (author, channel, message).
# The "no account / no login" agreement comes from Adrian and Kavin, so the conflicting
# update Sritharan posts in the demo is always quoted against a different person.
CONVERSATION = [
    ("adrian", "checkout",
     "Starting on the checkout flow. Shoppers should be able to buy without creating an account — "
     "guest checkout keeps cart conversion high."),
    ("kavin", "checkout",
     "Agreed, no login for checkout. We just collect an email address at checkout so we can send the receipt."),
    ("adrian", "checkout",
     "So the checkout page needs an address form and a payment step, nothing else."),
    ("sritharan", "checkout",
     "We also need to store each checkout order so support can look it up later."),
    ("adrian", "checkout",
     "I will add a checkout summary screen that shows the cart total before payment."),
    ("kavin", "checkout",
     "Good. Let's lock the brief before anyone writes code."),
]

# The message that contradicts 'no login for checkout' (sent live in the demo).
CONFLICT_MESSAGE = (
    "Update from the client: every customer must log in before they can pay, so checkout now "
    "requires an account."
)

# The host's decision when the demo is run with --full.
RESOLUTION = (
    "Checkout requires an account. Add a login step before payment and update the checkout tasks; "
    "guest checkout is dropped for this release."
)

# The Parallel Futures question waiting for the team's answers.
SCENARIO = (
    "A shopper with items in their cart opens checkout for the first time. "
    "Describe exactly what they see and what they have to do before they can pay."
)


def seed(full: bool = False) -> dict:
    """Reset the database and stage the demo team, chat, approved brief and confirmed tasks."""
    db.reset_db()
    ts = db.now()

    # 1. Users, the group, its members and its two channels.
    users: dict[str, str] = {}
    for i, (username, display, accent, _role) in enumerate(MEMBERS):
        uid = db.new_id()
        users[username] = uid
        db.ex("INSERT INTO users (id, username, display_name, accent, created_at) VALUES (?,?,?,?,?)",
              (uid, username, display, accent, ts + i))

    gid = db.new_id()
    db.ex("INSERT INTO groups (id, name, host_user_id, created_at) VALUES (?,?,?,?)",
          (gid, "Monarch Core", users["kavin"], ts))
    for username, _d, _a, role in MEMBERS:
        db.ex("INSERT INTO group_members (group_id, user_id, role) VALUES (?,?,?)",
              (gid, users[username], role))

    channels: dict[str, str] = {}
    for pos, name in enumerate(["general", "checkout"]):
        cid = db.new_id()
        channels[name] = cid
        db.ex("INSERT INTO channels (id, group_id, name, position) VALUES (?,?,?,?)", (cid, gid, name, pos))

    # 2. The chat history.
    db.ex("INSERT INTO group_messages (id, channel_id, group_id, user_id, kind, content, created_at)"
          " VALUES (?,?,?,?,?,?,?)",
          (db.new_id(), channels["general"], gid, users["kavin"], "user",
           "Welcome to Monarch Core. Project talk goes in #checkout.", ts))

    for i, (username, channel, text) in enumerate(CONVERSATION):
        db.ex("INSERT INTO group_messages (id, channel_id, group_id, user_id, kind, content, created_at)"
              " VALUES (?,?,?,?,?,?,?)",
              (db.new_id(), channels[channel], gid, users[username], "user", text, ts + 10 + i))

    # Personal project for each member (individual workspace is private).
    for uid in users.values():
        db.ex("INSERT INTO projects (id, user_id, name, created_at) VALUES (?,?,?,?)",
              (db.new_id(), uid, "Checkout work", db.now()))

    # PM agent: brief -> host approves -> tickets -> host approves -> estimates confirmed.
    pipeline.extract_brief(gid, users["kavin"])
    pipeline.approve_brief(gid, users["kavin"])
    pipeline.propose_tickets(gid)
    pipeline.approve_assignments(gid, users["kavin"])
    for t in db.q("SELECT id FROM tickets WHERE group_id=?", (gid,)):
        pipeline.confirm_hours(gid, t["id"], users["kavin"])

    # A Parallel Futures question is waiting for answers in the demo.
    fid = db.new_id()
    db.ex("INSERT INTO futures (id, group_id, scenario, created_at) VALUES (?,?,?,?)",
          (fid, gid, SCENARIO, db.now()))

    info = {
        "group_id": gid,
        "channel_id": channels["checkout"],
        "users": {u: users[u] for u in users},
        "tickets": len(db.q("SELECT id FROM tickets WHERE group_id=?", (gid,))),
        "alerts": 0,
    }

    # --full: also send the conflicting message and resolve the alert it raises.
    if full:
        mid = db.new_id()
        db.ex("INSERT INTO group_messages (id, channel_id, group_id, user_id, kind, content, created_at)"
              " VALUES (?,?,?,?,?,?,?)",
              (mid, channels["checkout"], gid, users["sritharan"], "user", CONFLICT_MESSAGE, db.now()))
        alert, _ = pipeline.scan_message(gid, mid)
        if alert:
            pipeline.resolve_alert(gid, alert["id"], users["kavin"], RESOLUTION)
            info["alerts"] = 1
            info["alert"] = {"headline": alert["headline"], "impact": alert["impact_label"]}
    return info


def main() -> None:
    """Command line entry: seed the demo (add --full to also run the conflict and resolution)."""
    full = "--full" in sys.argv
    info = seed(full=full)
    print("Demo seeded.")
    print(f"  Group:   Monarch Core ({info['group_id']})")
    print(f"  Users:   {', '.join(info['users'])}  (host: kavin)")
    print(f"  Tickets: {info['tickets']}")
    if info.get("alert"):
        print(f"  Alert:   {info['alert']['headline']} — {info['alert']['impact']}")
    print()
    print("Open http://127.0.0.1:8000 in two windows, sign in as kavin and as sritharan.")


if __name__ == "__main__":
    main()
