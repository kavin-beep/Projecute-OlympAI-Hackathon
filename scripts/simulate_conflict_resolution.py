"""Simulated conflict-resolution tests, end to end through the real pipeline.

    python -m scripts.simulate_conflict_resolution [--verbose]

For every planted scenario in `evaluate_conflicts.py`, a fresh team is set up in
a temporary database: an approved brief, a task that depends on the planted
claim, an unrelated task, and the planted claim among distractor messages. Then
the new message arrives and the same steps the app runs are checked:

  1. detect      the Architect flags the expected kind (or stays quiet)
  2. evidence    the alert quotes the planted and the new message, no distractor
  3. impact      the dependent task is listed once and its confirmed hours counted
  4. resolve     the host approves a resolution: the alert closes and a decision
                 is recorded that links to the affected tasks
  5. QA          the QA agent writes acceptance criteria on every affected task
  6. closed      a resolved alert cannot be resolved again

"Unclear" flags take the false-alert path instead: the host dismisses them and no
decision is recorded. Uses a temporary database; the demo data is not touched.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

# Use a throw-away database (set before app.db is imported), so the demo data is untouched.
os.environ["PROJECUTE_DB"] = os.path.join(tempfile.mkdtemp(prefix="projecute-sim-"), "sim.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, pipeline, retrieval  # noqa: E402
from app.llm import llm  # noqa: E402
from scripts.evaluate_conflicts import DISTRACTORS, SCENARIOS  # noqa: E402

STEPS = ["detect", "evidence", "impact", "resolve", "qa", "closed"]


def _team(name: str) -> tuple[str, str, str, str]:
    """A fresh group with a host and a member. Returns (group, channel, host, member)."""
    ts = db.now()
    host, member, gid, cid = db.new_id(), db.new_id(), db.new_id(), db.new_id()
    db.exmany("INSERT INTO users (id, username, display_name, created_at) VALUES (?,?,?,?)",
              [(host, f"host-{host}", "Host", ts), (member, f"member-{member}", "Member", ts)])
    db.ex("INSERT INTO groups (id, name, host_user_id, created_at) VALUES (?,?,?,?)", (gid, name, host, ts))
    db.exmany("INSERT INTO group_members (group_id, user_id, role) VALUES (?,?,?)",
              [(gid, host, "host"), (gid, member, "member")])
    db.ex("INSERT INTO channels (id, group_id, name) VALUES (?,?,?)", (cid, gid, "project"))
    db.ex("INSERT INTO briefs (id, group_id, content, status, approved_by, created_at, updated_at)"
          " VALUES (?,?,?,?,?,?,?)", (db.new_id(), gid, "# Brief", "approved", host, ts, ts))
    return gid, cid, host, member


def _say(gid: str, cid: str, uid: str, text: str) -> str:
    """Post a chat message and return its id."""
    mid = db.new_id()
    db.ex("INSERT INTO group_messages (id, channel_id, group_id, user_id, kind, content, created_at)"
          " VALUES (?,?,?,?,?,?,?)", (mid, cid, gid, uid, "user", text, db.now()))
    return mid


def _task(gid: str, key: str, title: str, hours: float) -> str:
    """An approved task with team-confirmed hours."""
    tid = db.new_id()
    ts = db.now()
    db.ex("INSERT INTO tickets (id, group_id, key, title, detail, priority, estimated_hours, hours_confirmed,"
          " status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
          (tid, gid, key, title, "", "Medium", hours, 1, "approved", ts, ts))
    return tid


def simulate(sid: str, planted: str, new: str, expected: str) -> dict:
    """Run one scenario end to end. Returns which steps passed (None = not applicable)."""
    # Set up: the planted claim among distractors, a task that depends on it, an unrelated
    # task, and then the new message.
    gid, cid, host, member = _team(sid)
    for d in DISTRACTORS[:3]:
        _say(gid, cid, host, d)
    planted_id = _say(gid, cid, member, planted)
    for d in DISTRACTORS[3:]:
        _say(gid, cid, member, d)
    dependent = _task(gid, "T-1", planted, 6)
    _task(gid, "T-2", "Refresh the marketing site screenshots", 2)
    new_id = _say(gid, cid, host, new)

    # 1. detect
    alert, _ = pipeline.scan_message(gid, new_id)
    got = alert["kind"] if alert else "none"
    res: dict = {"id": sid, "expected": expected, "got": got, **dict.fromkeys(STEPS)}
    res["detect"] = got == expected
    if not alert:
        return res

    # 2. evidence and 3. impact
    sources = {s["id"] for s in alert["sources"]}
    res["evidence"] = sources == {planted_id, new_id}
    keys = [t["key"] for t in alert["tickets"]]
    res["impact"] = keys.count("T-1") == 1 and len(keys) == len(set(keys)) and alert["confirmed_hours"] >= 6

    # 4. resolve and 5. QA
    if alert["kind"] == "unclear":       # false-alert path: dismissed, no decision
        before = len(pipeline.workspace_state(gid)["decisions"])
        closed, _ = pipeline.dismiss_alert(gid, alert["id"], host, "They agree")
        res["resolve"] = closed["status"] == "dismissed" and len(pipeline.workspace_state(gid)["decisions"]) == before
        res["qa"] = None
    else:
        resolution = alert["options"][0] if alert["options"] else "Keep the original agreement."
        closed, _ = pipeline.resolve_alert(gid, alert["id"], host, resolution)
        state = pipeline.workspace_state(gid)
        decision = next((d for d in state["decisions"] if d["alert_id"] == alert["id"]), None)
        res["resolve"] = (closed["status"] == "resolved" and decision is not None
                          and dependent in {t["id"] for t in decision["tickets"]})
        affected = {t["id"] for t in alert["tickets"]}
        res["qa"] = all(t["acceptance_criteria"] for t in state["tickets"] if t["id"] in affected)
    # 6. closed: resolving the same alert twice must fail.
    try:
        pipeline.resolve_alert(gid, alert["id"], host, "again")
        res["closed"] = False
    except ValueError:
        res["closed"] = True
    return res


def main() -> int:
    """Run every scenario and print a step-by-step report."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    db.init_db()
    results = [simulate(*s) for s in SCENARIOS]

    print("Simulated conflict-resolution tests (full pipeline, temporary database)")
    print(f"  Scenarios:    {len(results)}")
    print(f"  Judged by:    {'live AI: ' + llm.model if llm.mode == 'live' else 'built-in rules (no AI provider key)'}")
    print(f"  Claim search: {retrieval.backend_label()}\n")
    for step in STEPS:
        applicable = [r for r in results if r[step] is not None]
        passed = sum(1 for r in applicable if r[step])
        print(f"  {step:<10} {passed}/{len(applicable)}")
    full = [r for r in results if r["got"] != "none"]
    ok = sum(1 for r in full if all(r[s] is not False for s in STEPS))
    print(f"\n  Flagged scenarios that completed every step: {ok}/{len(full)}")
    for r in results:
        failed = [s for s in STEPS if r[s] is False]
        if failed or args.verbose:
            print(f"  {'FAIL' if failed else 'ok  '} {r['id']}: expected {r['expected']}, got {r['got']}"
                  + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
