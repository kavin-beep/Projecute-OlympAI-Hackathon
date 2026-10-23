// API client, session state and the WebSocket connection.

// How the frontend fits together: app.js (shell) loads one module per area - chat.js,
// group.js, workspace.js, board.js - and they all share this file (server calls,
// shared state, live events) and ui.js (building blocks such as el(), modal(), toast()).

// Shared app state: who is signed in, and what is open in each area.
export const state = {
  token: sessionStorage.getItem('projecute_token') || '',
  me: null,
  groups: [],
  group: null,          // {group, channels, members, is_host}
  channelId: null,
  workspace: null,
  chats: [],
  chatId: null,
  wsChatId: null,
  projects: [],
  projectId: null,
  items: [],
  status: null,
};

// A tiny event bus: WebSocket events arrive as 'ws:<name>' and any module can listen.
const listeners = new Map();
// Subscribe to a live event (from the WebSocket or the app itself).
export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
}
// Notify every subscriber of an event.
export function emit(event, payload) {
  (listeners.get(event) || []).forEach((fn) => fn(payload));
}

// An error carrying the server's message and HTTP status, shown to the user in a toast.
export class ApiError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}

// Call the backend JSON API with the session token; throws ApiError with the server's message.
export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(state.token ? { 'X-Token': state.token } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  // The session ended (e.g. the demo was reset): sign out and show the sign-in screen.
  if (res.status === 401) {
    setToken('');
    emit('signed-out');
    throw new ApiError('Your session ended. Sign in again.');
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new ApiError(data.detail || 'Something went wrong.', res.status);
  return data;
}

// Remember (or forget) the session token for this browser tab.
export function setToken(token) {
  state.token = token;
  if (token) sessionStorage.setItem('projecute_token', token);
  else sessionStorage.removeItem('projecute_token');
}

/** POST that streams server-sent events; calls onEvent for each parsed object. */
export async function stream(path, body, onEvent) {
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Token': state.token },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = 'Something went wrong.';
    try { detail = JSON.parse(text).detail || detail; } catch { /* keep default */ }
    throw new ApiError(detail);
  }
  // Read the answer as it arrives; each 'data: {...}' block is one event (delta or done).
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      onEvent(JSON.parse(line.slice(5).trim()));
    }
  }
}

// ---------------------------------------------------------------- websocket
let socket = null;
let retry = 0;

// Open the live-update WebSocket and reconnect if it drops.
export function connectSocket() {
  if (!state.token) return;
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(state.token)}`);
  socket.addEventListener('open', () => { retry = 0; });
  socket.addEventListener('message', (ev) => {
    const { event, payload } = JSON.parse(ev.data);
    emit(`ws:${event}`, payload);
  });
  // Reconnect after a drop, waiting a little longer each time (up to 2.4 s).
  socket.addEventListener('close', () => {
    socket = null;
    if (!state.token) return;
    retry = Math.min(retry + 1, 6);
    setTimeout(connectSocket, 400 * retry);
  });
}

// Close the live-update WebSocket (on sign-out).
export function closeSocket() {
  if (socket) { const s = socket; socket = null; s.close(); }
}
