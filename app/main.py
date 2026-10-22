"""Projecute — FastAPI app: HTTP API, WebSockets and the static frontend."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import (
    Body,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import agents, db, media, pipeline, retrieval
from .llm import llm
from .ws import hub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create the database tables when the server starts, and stage the demo on a fresh database."""
    db.init_db()
    if not db.q1("SELECT 1 FROM users LIMIT 1"):
        from scripts.seed_demo import seed

        await asyncio.to_thread(seed)
    yield


app = FastAPI(title="Projecute", docs_url=None, redoc_url=None, lifespan=lifespan)


# ---------------------------------------------------------------- auth
def current_user(authorization: str | None = Header(default=None),
                 x_token: str | None = Header(default=None, alias="X-Token")) -> dict:
    """Resolve the signed-in user from the X-Token / Bearer header, or reject with 401."""
    token = x_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(401, "Sign in to continue.")
    row = db.q1("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,))
    if not row:
        raise HTTPException(401, "Your session expired. Sign in again.")
    return dict(row)


User = Depends(current_user)


def _public_user(row: dict) -> dict:
    """The fields of a user that are safe to send to the browser."""
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"],
            "accent": row["accent"]}


@app.post("/api/login")
def login(payload: dict = Body(...)) -> dict:
    """Sign in by username (demo prototype, no passwords) and return a session token."""
    username = (payload.get("username") or "").strip().lower()
    if not username:
        raise HTTPException(400, "Pick a username.")
    row = db.q1("SELECT * FROM users WHERE username=?", (username,))
    if not row:
        raise HTTPException(404, "No such user in this demo. Use the Load demo button first.")
    token = secrets.token_urlsafe(24)
    db.ex("INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)", (token, row["id"], db.now()))
    return {"token": token, "user": _public_user(dict(row))}


@app.get("/api/users")
def list_users() -> dict:
    """Users shown on the sign-in screen."""
    return {"users": [_public_user(dict(r)) for r in db.q("SELECT * FROM users ORDER BY created_at")]}


@app.get("/api/me")
def me(user: dict = User) -> dict:
    """The signed-in user."""
    return {"user": _public_user(user)}


@app.get("/api/status")
def status() -> dict:
    """AI mode, retrieval backend and orchestrator, for the header and Settings."""
    return {
        "ai": llm.status(),
        "retrieval": {"backend": retrieval.backend(), "label": retrieval.backend_label()},
        "agents": {"orchestrator": "LangGraph" if agents.HAS_LANGGRAPH else "sequential fallback"},
    }


# ---------------------------------------------------------------- helpers
async def broadcast(group_id: str, events: list[tuple[str, Any]]) -> None:
    """Push pipeline events to every member of a group over WebSockets."""
    if not events:
        return
    members = pipeline.members_of(group_id)
    for event, payload in events:
        await hub.send_users(members, event, {"group_id": group_id, "data": payload})


def require_member(group_id: str, user: dict) -> None:
    """Reject with 403 unless the user is in the group."""
    if not db.is_member(group_id, user["id"]):
        raise HTTPException(403, "You are not a member of this group.")


def require_host(group_id: str, user: dict) -> None:
    """Reject with 403 unless the user is the group's host."""
    require_member(group_id, user)
    if not db.is_host(group_id, user["id"]):
        raise HTTPException(403, "Only the host can approve this.")


def require_channel(group_id: str, channel_id: str) -> None:
    """Reject with 404 unless the channel belongs to this group."""
    if not db.q1("SELECT 1 FROM channels WHERE id=? AND group_id=?", (channel_id, group_id)):
        raise HTTPException(404, "Channel not found.")


def require_group_message(group_id: str, message_id: str) -> None:
    """Reject with 404 unless the message belongs to this group."""
    if not db.q1("SELECT 1 FROM group_messages WHERE id=? AND group_id=?", (message_id, group_id)):
        raise HTTPException(404, "Message not found.")


# ================================================================ 1. Individual chat
@app.get("/api/chats")
def list_chats(surface: str = Query("chat"), user: dict = User) -> dict:
    """The user's own individual chats, newest first."""
    rows = db.q(
        "SELECT c.*, (SELECT content FROM chat_messages m WHERE m.chat_id=c.id ORDER BY m.created_at LIMIT 1)"
        " AS preview FROM chats c WHERE c.user_id=? AND c.surface=? ORDER BY c.updated_at DESC",
        (user["id"], surface),
    )
    return {"chats": db.rows_to_dicts(rows)}


@app.post("/api/chats")
def create_chat(payload: dict = Body(default={}), user: dict = User) -> dict:
    """Start a new individual chat."""
    cid = db.new_id()
    ts = db.now()
    db.ex("INSERT INTO chats (id, user_id, title, created_at, updated_at, surface) VALUES (?,?,?,?,?,?)",
          (cid, user["id"], payload.get("title") or "New chat", ts, ts, payload.get("surface") or "chat"))
    return {"chat": dict(db.q1("SELECT * FROM chats WHERE id=?", (cid,)))}


def _own_chat(chat_id: str, user: dict) -> dict:
    """Load a chat only if it belongs to the user (404 otherwise, so ids leak nothing)."""
    row = db.q1("SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"]))
    if not row:
        raise HTTPException(404, "Chat not found.")
    return dict(row)


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str, user: dict = User) -> dict:
    """One of the user's chats with its messages."""
    chat = _own_chat(chat_id, user)
    msgs = db.rows_to_dicts(db.q("SELECT * FROM chat_messages WHERE chat_id=? ORDER BY created_at", (chat_id,)))
    return {"chat": chat, "messages": msgs}


@app.patch("/api/chats/{chat_id}")
def rename_chat(chat_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Rename one of the user's chats."""
    _own_chat(chat_id, user)
    title = (payload.get("title") or "").strip()[:80]
    if not title:
        raise HTTPException(400, "Give the chat a name.")
    db.ex("UPDATE chats SET title=?, updated_at=? WHERE id=?", (title, db.now(), chat_id))
    return {"chat": dict(db.q1("SELECT * FROM chats WHERE id=?", (chat_id,)))}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str, user: dict = User) -> dict:
    """Delete one of the user's chats and unlink items created from it."""
    _own_chat(chat_id, user)
    db.ex("DELETE FROM chat_messages WHERE chat_id=?", (chat_id,))
    db.ex("UPDATE items SET source_chat_id=NULL WHERE source_chat_id=?", (chat_id,))
    db.ex("DELETE FROM chats WHERE id=?", (chat_id,))
    return {"ok": True}


# Who the assistant says it is. Without this, the underlying model introduces
# itself by its own product name. It stays honest about the model if asked.
IDENTITY = (
    "Your name is Projecute AI: the AI assistant built into Projecute, a team project tool made by team "
    "Monarch Core for the OlympAI Hackathon. When asked who or what you are, say you are Projecute AI. "
    "Do not call yourself ChatGPT or any other assistant. If someone asks which model powers you, say "
    f"Projecute AI runs on an open-source language model ({llm.model}) served through Groq. "
)

# What the assistant knows about Projecute itself, so questions about the app,
# and about what will be improved next, are answered the same way the README does.
ABOUT_PROJECUTE = (
    "About Projecute: a multiplayer AI sprint and architecture manager. It has four areas: individual "
    "chat (private AI help), group chat (public AI answers, or private help that only shows a 'used AI' "
    "notice), an individual workspace (named content, emails, code, images and audio) and a group "
    "workspace (Brief, Sources, Tasks, Decisions, Alerts, Activity, Team outputs). A PM agent turns the "
    "team chat into a brief and tasks with priority, estimated hours and owner, finds blockers and "
    "triages bug tickets; an Architect agent flags duplicates and contradictions across chat, PRDs, bug "
    "tickets, meeting summaries and tasks, quoting the exact evidence; a QA agent writes acceptance "
    "criteria after the host approves a resolution. The host approves every change to the shared plan.\n"
    "If asked what will be improved or added next (future scope, roadmap, enhancements), answer with "
    "this list: 1) connect GitHub issues, document tools and meeting-summary sources automatically (in "
    "the prototype, sources are pasted in by hand); 2) support larger teams and more detailed permission "
    "policies; 3) add multilingual evaluation and improved dependency visualisation; 4) expand beyond the "
    "prototype after measured user feedback; 5) real image and audio generation (the prototype makes "
    "placeholder images and reads scripts aloud with the browser's voice). If asked what is missing or "
    "not done yet, or for more detail, also mention: creating groups and inviting members from the app "
    "(only the demo team exists); proper accounts with passwords; uploading PDF or Word files as sources; "
    "a task board with in progress / done, due dates and reminders; email or phone notifications; a "
    "dependency graph; and for the AI: agents that discuss and act on their own (today the host approves "
    "each step), longer chat memory (today the last 20 messages), web browsing and reading uploaded "
    "files, catching more real duplicates and better grouping of similar issues, and languages other "
    "than English. Keep it honest: these are not in the prototype yet.\n"
    "If asked to generate or create an image, picture, logo, drawing, audio, voice-over, song or other "
    "sound, start your answer with exactly this sentence: 'Real image and audio generation will be "
    "enhanced and added in future development of Projecute.' Then add one short sentence: for now, My "
    "workspace can make a labelled placeholder (New item, type Image or Audio). Keep the whole answer "
    "under 60 words and do not describe or fake the image or audio.\n"
    "My workspace's New item offers exactly these types: Content, Email draft, Code, Image, Audio. Never "
    "mention other types. "
)

CHAT_SYSTEM = IDENTITY + ABOUT_PROJECUTE + (
    "You are the assistant inside Projecute's private individual chat. Answer everyday questions, explain "
    "ideas, help the person brainstorm and learn. Use Markdown. Keep answers tight and useful.\n"
    "This chat is for exploring and learning, not for producing finished work. If the person asks you to "
    "generate or write a finished piece (an article, report, essay, document, email draft, letter, code "
    "file or program), do not write it here. Instead, tell them to open My workspace (the folder icon in "
    "the left rail) and press New item, choose the type, name it and describe what they want: it is "
    "generated there and saved as a named item they can edit, find later and share with their group. "
    "You can still explain how to approach it, suggest an outline or ideas, and show a short example "
    "snippet when it helps them learn."
)


@app.post("/api/chats/{chat_id}/messages")
async def send_chat_message(chat_id: str, payload: dict = Body(...), user: dict = User):
    """Save the user's message and stream the AI reply back as server-sent events."""
    chat = _own_chat(chat_id, user)
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "Write a message first.")
    ts = db.now()
    umid = db.new_id()
    db.ex("INSERT INTO chat_messages (id, chat_id, role, content, created_at) VALUES (?,?,?,?,?)",
          (umid, chat_id, "user", content, ts))
    if chat["title"] == "New chat":
        db.ex("UPDATE chats SET title=? WHERE id=?", (content[:48], chat_id))
    db.ex("UPDATE chats SET updated_at=? WHERE id=?", (ts, chat_id))

    history = db.q("SELECT role, content FROM chat_messages WHERE chat_id=? ORDER BY created_at", (chat_id,))
    messages = [{"role": "system", "content": CHAT_SYSTEM}] + [
        {"role": r["role"], "content": r["content"]} for r in history
    ][-20:]

    async def gen():
        """Server-sent event stream: the user message id, text deltas, then the saved reply."""
        yield _sse({"type": "user_message", "id": umid, "created_at": ts})
        chunks: list[str] = []
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def produce() -> None:
            """Run the blocking LLM stream in a worker thread and hand chunks to the event loop."""
            try:
                for piece in llm.stream(messages):
                    loop.call_soon_threadsafe(queue.put_nowait, piece)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, produce)
        while True:
            piece = await queue.get()
            if piece is None:
                break
            chunks.append(piece)
            yield _sse({"type": "delta", "text": piece})
        answer = "".join(chunks)
        amid = db.new_id()
        db.ex("INSERT INTO chat_messages (id, chat_id, role, content, created_at) VALUES (?,?,?,?,?)",
              (amid, chat_id, "assistant", answer, db.now()))
        db.ex("UPDATE chats SET updated_at=? WHERE id=?", (db.now(), chat_id))
        yield _sse({"type": "done", "id": amid, "content": answer})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(obj: dict) -> str:
    """Format one server-sent event."""
    return "data: " + json.dumps(obj) + "\n\n"


# ================================================================ 3. Individual workspace
@app.get("/api/projects")
def list_projects(user: dict = User) -> dict:
    """The user's personal projects (folders for workspace items)."""
    rows = db.q("SELECT * FROM projects WHERE user_id=? ORDER BY created_at", (user["id"],))
    return {"projects": db.rows_to_dicts(rows)}


@app.post("/api/projects")
def create_project(payload: dict = Body(...), user: dict = User) -> dict:
    """Create a personal project."""
    name = (payload.get("name") or "").strip()[:60]
    if not name:
        raise HTTPException(400, "Give the project a name.")
    pid = db.new_id()
    db.ex("INSERT INTO projects (id, user_id, name, created_at) VALUES (?,?,?,?)", (pid, user["id"], name, db.now()))
    return {"project": dict(db.q1("SELECT * FROM projects WHERE id=?", (pid,)))}


@app.get("/api/items")
def list_items(project_id: str | None = None, q: str | None = None, user: dict = User) -> dict:
    """The user's workspace items, filtered by project and name search."""
    sql = "SELECT * FROM items WHERE owner_user_id=?"
    params: list[Any] = [user["id"]]
    if project_id:
        sql += " AND project_id=?"
        params.append(project_id)
    if q:
        sql += " AND lower(name) LIKE ?"
        params.append(f"%{q.lower()}%")
    sql += " ORDER BY updated_at DESC"
    return {"items": db.rows_to_dicts(db.q(sql, params))}


@app.get("/api/items/{item_id}")
def get_item(item_id: str, user: dict = User) -> dict:
    """One item: the owner can always read it; group members only once it is shared."""
    row = db.q1("SELECT * FROM items WHERE id=?", (item_id,))
    if not row:
        raise HTTPException(404, "Item not found.")
    item = dict(row)
    if item["owner_user_id"] != user["id"]:
        shared = item["shared_group_id"]
        if not (shared and db.is_member(shared, user["id"])):
            raise HTTPException(404, "Item not found.")
    return {"item": item}


ITEM_PROMPTS = {
    "content": "You write clear, useful content. Return Markdown only, no preamble.",
    "email": "You write short professional emails. Return a Subject line then the body.",
    "code": "You write small, correct, self-contained code. Return code only, no explanation, no fences.",
}


@app.post("/api/items/generate")
async def generate_item(payload: dict = Body(...), user: dict = User) -> dict:
    """Generate a named workspace item (content, email, code, image or audio)."""
    name = (payload.get("name") or "").strip()[:80]
    kind = payload.get("kind") or "content"
    prompt = (payload.get("prompt") or "").strip()
    project_id = payload.get("project_id")
    chat_id = payload.get("chat_id")
    if not name:
        raise HTTPException(400, "Name the item so you can find it later.")
    if kind not in ("content", "email", "code", "image", "audio"):
        raise HTTPException(400, "Unknown item type.")
    if not prompt:
        raise HTTPException(400, "Say what you want generated.")
    if project_id and not db.q1("SELECT 1 FROM projects WHERE id=? AND user_id=?", (project_id, user["id"])):
        raise HTTPException(403, "That project is not yours.")
    if chat_id and not db.q1("SELECT 1 FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"])):
        chat_id = None

    body, language, data_url, generator = "", None, None, "live"
    if kind in ("content", "email", "code"):
        body = await asyncio.to_thread(
            llm.complete,
            [{"role": "system", "content": ITEM_PROMPTS[kind]}, {"role": "user", "content": prompt}],
        )
        generator = llm.mode
        if kind == "code":
            language = payload.get("language") or "python"
    elif kind == "image":
        data_url, generator = media.generate_image(prompt, name)
        body = prompt
    else:
        script = await asyncio.to_thread(
            llm.complete,
            [{"role": "system", "content": "Write a short spoken script, 60 words max, plain text only."},
             {"role": "user", "content": prompt}],
        )
        body, generator = media.generate_audio(script)

    iid = db.new_id()
    ts = db.now()
    db.ex(
        "INSERT INTO items (id, owner_user_id, project_id, name, kind, body, language, data_url,"
        " source_chat_id, generator, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (iid, user["id"], project_id, name, kind, body, language, data_url, chat_id, generator, ts, ts),
    )
    return {"item": dict(db.q1("SELECT * FROM items WHERE id=?", (iid,)))}


@app.patch("/api/items/{item_id}")
def update_item(item_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Edit an item the user owns."""
    row = db.q1("SELECT * FROM items WHERE id=? AND owner_user_id=?", (item_id, user["id"]))
    if not row:
        raise HTTPException(404, "Item not found.")
    fields, values = [], []
    for col in ("name", "body", "language"):
        if col in payload and payload[col] is not None:
            fields.append(f"{col}=?")
            values.append(payload[col])
    if not fields:
        return {"item": dict(row)}
    values += [db.now(), item_id]
    db.ex(f"UPDATE items SET {', '.join(fields)}, updated_at=? WHERE id=?", values)
    return {"item": dict(db.q1("SELECT * FROM items WHERE id=?", (item_id,)))}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str, user: dict = User) -> dict:
    """Delete an item the user owns."""
    row = db.q1("SELECT * FROM items WHERE id=? AND owner_user_id=?", (item_id, user["id"]))
    if not row:
        raise HTTPException(404, "Item not found.")
    db.ex("DELETE FROM items WHERE id=?", (item_id,))
    return {"ok": True}


@app.post("/api/items/{item_id}/share")
async def share_item(item_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Share an item into a group the user is in (explicit sharing, slide 14)."""
    row = db.q1("SELECT * FROM items WHERE id=? AND owner_user_id=?", (item_id, user["id"]))
    if not row:
        raise HTTPException(404, "Item not found.")
    group_id = payload.get("group_id")
    if not group_id or not db.is_member(group_id, user["id"]):
        raise HTTPException(403, "You can only share into a group you are in.")
    db.ex("UPDATE items SET shared_group_id=?, updated_at=? WHERE id=?", (group_id, db.now(), item_id))
    act = db.log_activity(group_id, user["display_name"], "Shared a workspace item",
                          row["name"], actor_kind="user", ref_kind="item", ref_id=item_id)
    state = pipeline.workspace_state(group_id)
    await broadcast(group_id, [("outputs", state["outputs"]), ("activity", act)])
    return {"item": dict(db.q1("SELECT * FROM items WHERE id=?", (item_id,)))}


@app.post("/api/items/{item_id}/unshare")
async def unshare_item(item_id: str, user: dict = User) -> dict:
    """Make a shared item private again."""
    row = db.q1("SELECT * FROM items WHERE id=? AND owner_user_id=?", (item_id, user["id"]))
    if not row:
        raise HTTPException(404, "Item not found.")
    group_id = row["shared_group_id"]
    db.ex("UPDATE items SET shared_group_id=NULL, updated_at=? WHERE id=?", (db.now(), item_id))
    if group_id:
        state = pipeline.workspace_state(group_id)
        await broadcast(group_id, [("outputs", state["outputs"])])
    return {"item": dict(db.q1("SELECT * FROM items WHERE id=?", (item_id,)))}


# ================================================================ 2. Group chat
@app.get("/api/groups")
def my_groups(user: dict = User) -> dict:
    """Groups the user belongs to."""
    rows = db.q(
        "SELECT g.* FROM groups g JOIN group_members m ON m.group_id=g.id WHERE m.user_id=? ORDER BY g.created_at",
        (user["id"],),
    )
    return {"groups": db.rows_to_dicts(rows)}


@app.get("/api/groups/{group_id}")
def group_detail(group_id: str, user: dict = User) -> dict:
    """Group info, channels, members (with online state) and whether the user is host."""
    require_member(group_id, user)
    group = dict(db.q1("SELECT * FROM groups WHERE id=?", (group_id,)))
    channels = db.rows_to_dicts(db.q("SELECT * FROM channels WHERE group_id=? ORDER BY position", (group_id,)))
    members = db.rows_to_dicts(db.q(
        "SELECT u.id, u.username, u.display_name, u.accent, m.role FROM group_members m"
        " JOIN users u ON u.id=m.user_id WHERE m.group_id=? ORDER BY m.role, u.display_name", (group_id,)))
    online = hub.online()
    for m in members:
        m["online"] = m["id"] in online
    return {"group": group, "channels": channels, "members": members,
            "is_host": group["host_user_id"] == user["id"],
            "default_channel_id": pipeline.busiest_channel(group_id) or (channels[0]["id"] if channels else None)}


@app.patch("/api/groups/{group_id}/settings")
async def group_settings(group_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Host only: switch public AI answers and private AI help on or off."""
    require_host(group_id, user)
    fields, values, notes = [], [], []
    for col, label in (("allow_public_ai", "Public AI answers"), ("allow_private_ai", "Private AI help")):
        if col in payload:
            fields.append(f"{col}=?")
            values.append(1 if payload[col] else 0)
            notes.append(f"{label}: {'on' if payload[col] else 'off'}")
    if not fields:
        raise HTTPException(400, "Nothing to change.")
    db.ex(f"UPDATE groups SET {', '.join(fields)} WHERE id=?", values + [group_id])
    group = dict(db.q1("SELECT * FROM groups WHERE id=?", (group_id,)))
    act = db.log_activity(group_id, user["display_name"], "Changed who can use AI here",
                          "; ".join(notes), actor_kind="user")
    await broadcast(group_id, [("group", group), ("activity", act)])
    return {"group": group}


@app.get("/api/groups/{group_id}/channels/{channel_id}/messages")
def channel_messages(group_id: str, channel_id: str, user: dict = User) -> dict:
    """Messages in one channel of a group the user is in."""
    require_member(group_id, user)
    require_channel(group_id, channel_id)
    rows = db.q(
        "SELECT m.*, u.display_name AS author, u.accent FROM group_messages m"
        " LEFT JOIN users u ON u.id=m.user_id WHERE m.channel_id=? ORDER BY m.created_at",
        (channel_id,),
    )
    msgs = db.rows_to_dicts(rows)
    for m in msgs:
        m["reactions"] = _reactions(m["id"])
    return {"messages": msgs}


def _reactions(message_id: str) -> list[dict]:
    """Emoji reaction counts for a message."""
    rows = db.q("SELECT emoji, COUNT(*) AS n, GROUP_CONCAT(user_id) AS users FROM reactions"
                " WHERE message_id=? GROUP BY emoji", (message_id,))
    return [{"emoji": r["emoji"], "count": r["n"], "users": (r["users"] or "").split(",")} for r in rows]


GROUP_AI_SYSTEM = IDENTITY + ABOUT_PROJECUTE + (
    "You are the group assistant in a team chat. You can only see this group's messages. "
    "Answer the question using that context. Be brief and concrete."
)


@app.post("/api/groups/{group_id}/channels/{channel_id}/messages")
async def post_group_message(group_id: str, channel_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Post to a channel; optional public AI answer or private help; then run conflict review."""
    require_member(group_id, user)
    require_channel(group_id, channel_id)
    content = (payload.get("content") or "").strip()
    ai_mode = payload.get("ai_mode") or "none"
    if not content:
        raise HTTPException(400, "Write a message first.")
    if payload.get("reply_to_id"):
        require_group_message(group_id, payload["reply_to_id"])
    group = dict(db.q1("SELECT * FROM groups WHERE id=?", (group_id,)))
    if ai_mode == "public" and not group["allow_public_ai"]:
        raise HTTPException(403, "The host turned off public AI answers in this group.")
    if ai_mode == "private" and not group["allow_private_ai"]:
        raise HTTPException(403, "The host turned off private AI help in this group.")

    members = pipeline.members_of(group_id)
    result: dict[str, Any] = {}

    if ai_mode == "private":
        # Nothing about the prompt, the answer or the topic reaches the group.
        context = _group_context(group_id)
        answer = await asyncio.to_thread(
            llm.complete,
            [{"role": "system", "content": GROUP_AI_SYSTEM},
             {"role": "user", "content": f"Group messages so far:\n{context}\n\nQuestion: {content}"}],
        )
        hid = db.new_id()
        ts = db.now()
        db.ex("INSERT INTO private_help (id, group_id, channel_id, user_id, prompt, answer, created_at)"
              " VALUES (?,?,?,?,?,?,?)", (hid, group_id, channel_id, user["id"], content, answer, ts))
        notice_id = db.new_id()
        notice = f"{user['display_name']} used AI"
        db.ex("INSERT INTO group_messages (id, channel_id, group_id, user_id, kind, content, created_at)"
              " VALUES (?,?,?,?,?,?,?)", (notice_id, channel_id, group_id, user["id"], "notice", notice, ts))
        notice_row = _message_payload(notice_id)
        await hub.send_users(members, "group_message", {"group_id": group_id, "data": notice_row})
        return {"private_help": {"id": hid, "prompt": content, "answer": answer, "created_at": ts},
                "notice": notice_row}

    ts = db.now()
    mid = db.new_id()
    db.ex("INSERT INTO group_messages (id, channel_id, group_id, user_id, kind, content, reply_to_id, created_at)"
          " VALUES (?,?,?,?,?,?,?,?)",
          (mid, channel_id, group_id, user["id"], "user", content, payload.get("reply_to_id"), ts))
    msg = _message_payload(mid)
    await hub.send_users(members, "group_message", {"group_id": group_id, "data": msg})
    result["message"] = msg

    if ai_mode == "public":
        context = _group_context(group_id)
        answer = await asyncio.to_thread(
            llm.complete,
            [{"role": "system", "content": GROUP_AI_SYSTEM},
             {"role": "user", "content": f"Group messages so far:\n{context}\n\nQuestion: {content}"}],
        )
        aid = db.new_id()
        db.ex("INSERT INTO group_messages (id, channel_id, group_id, user_id, kind, content, reply_to_id, created_at)"
              " VALUES (?,?,?,?,?,?,?,?)", (aid, channel_id, group_id, None, "ai_public", answer, mid, db.now()))
        ai_msg = _message_payload(aid)
        await hub.send_users(members, "group_message", {"group_id": group_id, "data": ai_msg})
        result["ai_message"] = ai_msg

    # Architect agent reviews new claims once the team has an approved brief.
    brief = db.q1("SELECT status FROM briefs WHERE group_id=? ORDER BY created_at DESC LIMIT 1", (group_id,))
    if brief and brief["status"] == "approved":
        alert, events = await asyncio.to_thread(pipeline.scan_message, group_id, mid)
        await broadcast(group_id, events)
        if alert:
            result["alert"] = alert
    return result


def _group_context(group_id: str) -> str:
    """The last 40 messages of this group only, given to the group assistant."""
    rows = db.q(
        "SELECT m.content, u.display_name AS author FROM group_messages m LEFT JOIN users u ON u.id=m.user_id"
        " WHERE m.group_id=? AND m.kind IN ('user','ai_public') ORDER BY m.created_at DESC LIMIT 40",
        (group_id,),
    )
    return "\n".join(f"{r['author'] or 'Assistant'}: {r['content']}" for r in reversed(rows))


def _message_payload(message_id: str) -> dict:
    """A message row plus author and reactions, as sent to the browser."""
    row = db.q1(
        "SELECT m.*, u.display_name AS author, u.accent FROM group_messages m"
        " LEFT JOIN users u ON u.id=m.user_id WHERE m.id=?", (message_id,))
    msg = dict(row)
    msg["reactions"] = _reactions(message_id)
    return msg


@app.post("/api/groups/{group_id}/messages/{message_id}/reactions")
async def react(group_id: str, message_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Toggle the user's emoji reaction on a message in this group."""
    require_member(group_id, user)
    require_group_message(group_id, message_id)
    emoji = (payload.get("emoji") or "").strip()[:8]
    if not emoji:
        raise HTTPException(400, "Pick a reaction.")
    existing = db.q1("SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?",
                     (message_id, user["id"], emoji))
    if existing:
        db.ex("DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?", (message_id, user["id"], emoji))
    else:
        db.ex("INSERT INTO reactions (message_id, user_id, emoji) VALUES (?,?,?)", (message_id, user["id"], emoji))
    msg = _message_payload(message_id)
    await hub.send_users(pipeline.members_of(group_id), "group_message", {"group_id": group_id, "data": msg})
    return {"message": msg}


@app.post("/api/groups/{group_id}/typing")
async def typing(group_id: str, user: dict = User) -> dict:
    """Tell the other members this user is typing."""
    require_member(group_id, user)
    others = [u for u in pipeline.members_of(group_id) if u != user["id"]]
    await hub.send_users(others, "typing", {"group_id": group_id, "data": {"user": user["display_name"]}})
    return {"ok": True}


@app.get("/api/groups/{group_id}/private-help")
def my_private_help(group_id: str, user: dict = User) -> dict:
    """The user's own private AI help in this group (nobody else can read it)."""
    require_member(group_id, user)
    rows = db.q("SELECT * FROM private_help WHERE group_id=? AND user_id=? ORDER BY created_at DESC LIMIT 20",
                (group_id, user["id"]))
    return {"help": db.rows_to_dicts(rows)}


# ================================================================ 4. Group workspace
@app.get("/api/groups/{group_id}/workspace")
def get_workspace(group_id: str, user: dict = User) -> dict:
    """Everything in the group workspace: brief, tasks, alerts, decisions, activity, outputs."""
    require_member(group_id, user)
    return pipeline.workspace_state(group_id)


@app.post("/api/groups/{group_id}/brief/extract")
async def brief_extract(group_id: str, user: dict = User) -> dict:
    """Run the PM agent over the group chat to draft the brief."""
    require_member(group_id, user)
    try:
        brief, events = await asyncio.to_thread(pipeline.extract_brief, group_id, user["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast(group_id, events)
    return {"brief": brief}


@app.patch("/api/groups/{group_id}/brief")
async def brief_update(group_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Edit the brief; any edit sends it back to draft for the host to approve."""
    require_member(group_id, user)
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "The brief cannot be empty.")
    brief, events = pipeline.update_brief(group_id, content, user["id"])
    await broadcast(group_id, events)
    return {"brief": brief}


@app.post("/api/groups/{group_id}/brief/approve")
async def brief_approve(group_id: str, user: dict = User) -> dict:
    """Host only: approve the project brief."""
    require_host(group_id, user)
    try:
        brief, events = pipeline.approve_brief(group_id, user["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast(group_id, events)
    return {"brief": brief}


@app.post("/api/groups/{group_id}/tickets/propose")
async def tickets_propose(group_id: str, user: dict = User) -> dict:
    """Run the PM agent to propose tickets from the approved brief."""
    require_member(group_id, user)
    try:
        created, events = await asyncio.to_thread(pipeline.propose_tickets, group_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast(group_id, events)
    return {"tickets": created}


@app.post("/api/groups/{group_id}/tickets/approve")
async def tickets_approve(group_id: str, user: dict = User) -> dict:
    """Host only: approve the proposed task assignments."""
    require_host(group_id, user)
    tickets, events = pipeline.approve_assignments(group_id, user["id"])
    await broadcast(group_id, events)
    return {"tickets": tickets}


@app.post("/api/groups/{group_id}/tickets")
async def ticket_create(group_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Any member submits a task; it waits for the host's approval and is checked for duplicates."""
    require_member(group_id, user)
    title = (payload.get("title") or "").strip()[:140]
    if not title:
        raise HTTPException(400, "Give the task a title.")
    priority = payload.get("priority") or "Medium"
    if priority not in ("Low", "Medium", "High"):
        raise HTTPException(400, "Priority must be Low, Medium or High.")
    try:
        hours = float(payload.get("estimated_hours") or 4)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Estimated hours must be a number.") from exc
    if not 0.5 <= hours <= 200:
        raise HTTPException(400, "Estimated hours must be between 0.5 and 200.")
    owner = payload.get("owner_user_id") or None
    if owner and not db.is_member(group_id, owner):
        raise HTTPException(400, "The owner must be a member of this group.")
    ticket, events = await asyncio.to_thread(
        pipeline.create_ticket, group_id, user["id"], title, (payload.get("detail") or "").strip(),
        priority, hours, owner)
    await broadcast(group_id, events)
    return {"ticket": ticket}


@app.patch("/api/groups/{group_id}/tickets/{ticket_id}")
async def ticket_update(group_id: str, ticket_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Host only: edit a task (title, detail, priority, hours, owner, status)."""
    require_host(group_id, user)       # tasks are part of the shared plan
    try:
        ticket, events = pipeline.update_ticket(group_id, ticket_id, payload, user["id"])
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await broadcast(group_id, events)
    return {"ticket": ticket}


@app.post("/api/groups/{group_id}/tickets/{ticket_id}/confirm-hours")
async def ticket_confirm(group_id: str, ticket_id: str, user: dict = User) -> dict:
    """A member confirms a task's estimated hours (team-confirmed hours)."""
    require_member(group_id, user)
    try:
        ticket, events = pipeline.confirm_hours(group_id, ticket_id, user["id"])
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await broadcast(group_id, events)
    return {"ticket": ticket}


@app.get("/api/groups/{group_id}/alerts/{alert_id}")
def alert_detail(group_id: str, alert_id: str, user: dict = User) -> dict:
    """One alert with its source messages and affected tasks."""
    require_member(group_id, user)
    row = db.q1("SELECT * FROM alerts WHERE id=? AND group_id=?", (alert_id, group_id))
    if not row:
        raise HTTPException(404, "Alert not found.")
    return {"alert": pipeline.serialize_alert(row)}


@app.post("/api/groups/{group_id}/alerts/{alert_id}/resolve")
async def alert_resolve(group_id: str, alert_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Host only: approve a resolution; records a decision and runs the QA agent."""
    require_host(group_id, user)
    resolution = (payload.get("resolution") or "").strip()
    if not resolution:
        raise HTTPException(400, "Say what the team decided.")
    try:
        alert, events = await asyncio.to_thread(
            pipeline.resolve_alert, group_id, alert_id, user["id"], resolution)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast(group_id, events)
    return {"alert": alert}


@app.post("/api/groups/{group_id}/alerts/{alert_id}/dismiss")
async def alert_dismiss(group_id: str, alert_id: str, payload: dict = Body(default={}), user: dict = User) -> dict:
    """Host only: close a false alert without recording a decision."""
    require_host(group_id, user)
    reason = (payload.get("reason") or "").strip() or "Not a real conflict"
    try:
        alert, events = pipeline.dismiss_alert(group_id, alert_id, user["id"], reason[:300])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast(group_id, events)
    return {"alert": alert}


# -------------------------------------------- sources: PRDs, bug tickets, meetings
@app.get("/api/groups/{group_id}/documents")
def list_documents(group_id: str, user: dict = User) -> dict:
    """The group's source documents with how many flags each raised."""
    require_member(group_id, user)
    return {"documents": pipeline.workspace_state(group_id)["documents"]}


@app.post("/api/groups/{group_id}/documents")
async def add_document(group_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Add a PRD, bug ticket or meeting summary; the agents cross-check it straight away."""
    require_member(group_id, user)
    kind = payload.get("kind") or ""
    if kind not in pipeline.KIND_LABEL:
        raise HTTPException(400, "Choose PRD, bug ticket or meeting summary.")
    title = (payload.get("title") or "").strip()[:120]
    content = (payload.get("content") or "").strip()
    if not title:
        raise HTTPException(400, "Give the source a title.")
    if len(content) < 20:
        raise HTTPException(400, "Paste the text of the document (at least a sentence).")
    if len(content) > 20000:
        raise HTTPException(400, "That document is too long for the prototype (20,000 characters max).")
    doc, alerts, events = await asyncio.to_thread(
        pipeline.add_document, group_id, user["id"], kind, title, content)
    await broadcast(group_id, events)
    return {"document": doc, "alerts": alerts}


@app.get("/api/groups/{group_id}/documents/{document_id}")
def document_detail(group_id: str, document_id: str, user: dict = User) -> dict:
    """One source document with its statements and the flags it raised."""
    require_member(group_id, user)
    doc = pipeline.get_document(group_id, document_id)
    if not doc:
        raise HTTPException(404, "Document not found.")
    return {"document": doc}


@app.get("/api/groups/{group_id}/activity/export")
def activity_export(group_id: str, user: dict = User) -> JSONResponse:
    """Download the full multi-agent event stream as JSON."""
    require_member(group_id, user)
    events = pipeline.activity_log(group_id)
    return JSONResponse({"group_id": group_id, "events": events},
                        headers={"Content-Disposition": 'attachment; filename="projecute-event-log.json"'})


@app.post("/api/groups/{group_id}/alerts/scan")
async def alerts_scan(group_id: str, user: dict = User) -> dict:
    """Re-run conflict review over every message in the group."""
    require_member(group_id, user)
    rows = db.q("SELECT id FROM group_messages WHERE group_id=? AND kind='user' ORDER BY created_at", (group_id,))
    found = []
    for r in rows:
        alert, events = await asyncio.to_thread(pipeline.scan_message, group_id, r["id"])
        if alert:
            found.append(alert)
            await broadcast(group_id, events)
    return {"alerts": found}


# -------------------------------------------- Parallel Futures / Human Unit Test
@app.post("/api/groups/{group_id}/futures")
async def create_future(group_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Start a Parallel Futures scenario for members to answer independently."""
    require_member(group_id, user)
    scenario = (payload.get("scenario") or "").strip()
    if not scenario:
        raise HTTPException(400, "Describe the scenario everyone should answer.")
    fid = db.new_id()
    db.ex("INSERT INTO futures (id, group_id, scenario, created_at) VALUES (?,?,?,?)",
          (fid, group_id, scenario, db.now()))
    act = db.log_activity(group_id, user["display_name"], "Started a Parallel Futures question",
                          scenario[:120], actor_kind="user", ref_kind="future", ref_id=fid)
    state = pipeline.workspace_state(group_id)
    await broadcast(group_id, [("futures", state["futures"]), ("activity", act)])
    return {"future": state["futures"][0]}


@app.post("/api/groups/{group_id}/futures/{future_id}/answer")
async def answer_future(group_id: str, future_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Submit this member's single answer to a Parallel Futures scenario."""
    require_member(group_id, user)
    if not db.q1("SELECT 1 FROM futures WHERE id=? AND group_id=?", (future_id, group_id)):
        raise HTTPException(404, "Not found.")
    answer = (payload.get("answer") or "").strip()
    if not answer:
        raise HTTPException(400, "Write your answer first.")
    if db.q1("SELECT 1 FROM future_answers WHERE future_id=? AND user_id=?", (future_id, user["id"])):
        raise HTTPException(400, "You already answered this one.")
    db.ex("INSERT INTO future_answers (id, future_id, user_id, answer, created_at) VALUES (?,?,?,?,?)",
          (db.new_id(), future_id, user["id"], answer, db.now()))
    state = pipeline.workspace_state(group_id)
    await broadcast(group_id, [("futures", state["futures"])])
    return {"ok": True}


@app.post("/api/groups/{group_id}/futures/{future_id}/compare")
async def compare_future(group_id: str, future_id: str, user: dict = User) -> dict:
    """Compare the answers to surface hidden assumptions."""
    require_member(group_id, user)
    row = db.q1("SELECT * FROM futures WHERE id=? AND group_id=?", (future_id, group_id))
    if not row:
        raise HTTPException(404, "Not found.")
    answers = db.rows_to_dicts(db.q(
        "SELECT fa.answer, u.display_name AS author FROM future_answers fa JOIN users u ON u.id=fa.user_id"
        " WHERE fa.future_id=? ORDER BY fa.created_at", (future_id,)))
    if len(answers) < 2:
        raise HTTPException(400, "At least two people need to answer before comparing.")
    comparison, _ = await asyncio.to_thread(agents.compare_futures, row["scenario"], answers)
    db.ex("UPDATE futures SET status='compared', comparison=? WHERE id=?",
          (json.dumps(comparison.model_dump()), future_id))
    act = db.log_activity(group_id, "Architect agent", "Compared Parallel Futures answers",
                          comparison.summary, ref_kind="future", ref_id=future_id)
    state = pipeline.workspace_state(group_id)
    await broadcast(group_id, [("futures", state["futures"]), ("activity", act)])
    return {"comparison": comparison.model_dump()}


@app.post("/api/groups/{group_id}/tickets/{ticket_id}/unit-test")
async def unit_test(group_id: str, ticket_id: str, payload: dict = Body(...), user: dict = User) -> dict:
    """Human Unit Test: record a description of a task and compare once both sides exist."""
    require_member(group_id, user)
    ticket = db.q1("SELECT * FROM tickets WHERE id=? AND group_id=?", (ticket_id, group_id))
    if not ticket:
        raise HTTPException(404, "Task not found.")
    description = (payload.get("description") or "").strip()
    if not description:
        raise HTTPException(400, "Describe the task in your own words.")
    row = db.q1("SELECT * FROM unit_tests WHERE ticket_id=?", (ticket_id,))
    is_assignee = ticket["owner_user_id"] == user["id"]
    if not row:
        uid = db.new_id()
        db.ex("INSERT INTO unit_tests (id, group_id, ticket_id, creator_user_id, assignee_user_id,"
              " creator_desc, assignee_desc, created_at) VALUES (?,?,?,?,?,?,?,?)",
              (uid, group_id, ticket_id, user["id"], ticket["owner_user_id"],
               None if is_assignee else description, description if is_assignee else None, db.now()))
    else:
        uid = row["id"]
        if is_assignee:
            db.ex("UPDATE unit_tests SET assignee_desc=?, assignee_user_id=? WHERE id=?",
                  (description, user["id"], uid))
        else:
            if row["creator_desc"] and row["creator_user_id"] != user["id"]:
                raise HTTPException(400, f"{pipeline.user_name(row['creator_user_id'])} already described this "
                                         "task. The person doing it writes the other description.")
            db.ex("UPDATE unit_tests SET creator_desc=?, creator_user_id=? WHERE id=?",
                  (description, user["id"], uid))

    row = db.q1("SELECT * FROM unit_tests WHERE id=?", (uid,))
    if row["creator_desc"] and row["assignee_desc"]:
        verdict, _ = await asyncio.to_thread(
            agents.compare_interpretations, ticket["title"], row["creator_desc"], row["assignee_desc"])
        db.ex("UPDATE unit_tests SET verdict=?, comparison=? WHERE id=?",
              (verdict.verdict, json.dumps(verdict.model_dump()), uid))
        db.log_activity(group_id, "Architect agent",
                        f"Human Unit Test on {ticket['key']}: {verdict.verdict}",
                        verdict.summary, ref_kind="ticket", ref_id=ticket_id)
    state = pipeline.workspace_state(group_id)
    await broadcast(group_id, [("unit_tests", state["unit_tests"]), ("activity", state["activity"][0])])
    return {"unit_test": next((u for u in state["unit_tests"] if u["id"] == uid), None)}


# ================================================================ demo + ws
@app.post("/api/demo/load")
async def load_demo(payload: dict = Body(default={})) -> dict:
    """Reset the database to the staged demo (needs the demo passcode when one is set)."""
    from scripts.seed_demo import seed

    # On a public deployment DEMO_PASSCODE is set, so a visitor cannot wipe the data.
    expected = os.environ.get("DEMO_PASSCODE", "")
    given = str(payload.get("passcode") or "")
    if expected and not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(403, "Enter the demo passcode to reset the data.")

    info = await asyncio.to_thread(seed)
    return info


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(default="")):
    """Live updates: one socket per signed-in browser window."""
    row = db.q1("SELECT user_id FROM sessions WHERE token=?", (token,))
    if not row:
        await ws.close(code=4401)
        return
    user_id = row["user_id"]
    await hub.connect(ws, user_id)
    try:
        await ws.send_json({"event": "ready", "payload": {"user_id": user_id}})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await hub.disconnect(ws, user_id)


# ---------------------------------------------------------------- static
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    """Serve the single-page frontend."""
    return FileResponse(os.path.join(STATIC, "index.html"))
