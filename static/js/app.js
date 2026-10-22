// Shell: sign in, navigation, theme, settings, live wiring.

import { api, closeSocket, connectSocket, on, setToken, state } from './api.js';
import { $, avatar, clear, el, icon, modal, toast } from './ui.js';
import { createChat, renderChatList } from './chat.js';
import * as group from './group.js';
import * as workspace from './workspace.js';
import * as board from './board.js';

const VIEWS = [
  ['chat', 'Individual chat', 'chat'],
  ['group', 'Group chat', 'group'],
  ['work', 'My workspace', 'work'],
  ['board', 'Shared workspace', 'board'],
];
let view = 'chat';
let chatSearch = '';

// ---------------------------------------------------------------- theme
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('projecute_theme', theme);
  clear($('#btnTheme')).append(icon(theme === 'dark' ? 'sun' : 'moon', 16));
}
applyTheme(localStorage.getItem('projecute_theme') || 'dark');
$('#btnTheme').addEventListener('click', () =>
  applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));

// ---------------------------------------------------------------- chat surfaces
const mainChat = createChat({
  surface: 'chat',
  threadEl: $('#chatThread'), scrollEl: $('#chatScroll'),
  inputEl: $('#chatInput'), sendEl: $('#chatSend'), titleEl: $('#chatTitle'),
  placeholderTitle: 'Individual chat',
  onAfterReply: () => refreshChatList(),
});

const wsChat = createChat({
  surface: 'workspace',
  threadEl: $('#wsThread'), scrollEl: $('#wsScroll'),
  inputEl: $('#wsInput'), sendEl: $('#wsSend'), titleEl: $('#wsChatTitle'),
  placeholderTitle: 'Workspace chat',
  onAfterReply: (chat, answer) => {
    const bar = el('div', { class: 'row-between', style: 'margin:-10px 0 20px' });
    const make = el('button', { class: 'btn sm' }, icon('plus', 13), 'Save this as a named item');
    make.addEventListener('click', () => {
      workspace.newItemDialog({ prompt: lastWorkspacePrompt || answer.slice(0, 400) });
      bar.remove();
    });
    bar.append(make);
    $('#wsThread').append(bar);
  },
});
workspace.bindWorkspaceChat(wsChat);

let lastWorkspacePrompt = '';
$('#wsInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) lastWorkspacePrompt = $('#wsInput').value.trim();
});

// Reload the individual chat list in the sidebar.
async function refreshChatList() {
  const { chats } = await api('/chats?surface=chat');
  state.chats = chats;
  renderChatList({
    container: $('#chatList'), chats, activeId: mainChat.chat?.id, query: chatSearch,
    onOpen: async (c) => { await mainChat.open(c.id); refreshChatList(); },
    onRename: (c) => {
      const input = el('input', { class: 'field', value: c.title });
      modal({
        title: 'Rename chat',
        body: el('div', { class: 'row' }, el('label', {}, 'Chat name'), input),
        confirmLabel: 'Save name',
        onConfirm: async () => {
          await api(`/chats/${c.id}`, { method: 'PATCH', body: { title: input.value } });
          if (mainChat.chat?.id === c.id) $('#chatTitle').textContent = input.value;
          await refreshChatList();
          toast('Chat renamed');
        },
      });
    },
    onDelete: (c) => {
      modal({
        title: 'Delete this chat?',
        body: el('p', {}, `"${c.title}" and its messages will be removed. This cannot be undone.`),
        confirmLabel: 'Delete', danger: true,
        onConfirm: async () => {
          await api(`/chats/${c.id}`, { method: 'DELETE' });
          if (mainChat.chat?.id === c.id) mainChat.reset();
          await refreshChatList();
          toast('Chat deleted');
        },
      });
    },
  });
}

$('#newChat').addEventListener('click', async () => { await mainChat.newChat(); refreshChatList(); });
$('#chatSearch').addEventListener('input', (e) => { chatSearch = e.target.value; refreshChatList(); });
$('#wsNewChat').addEventListener('click', () => wsChat.newChat());

// ---------------------------------------------------------------- navigation
function renderRail() {
  const rail = clear($('#rail'));
  for (const [key, label, ic] of VIEWS) {
    const btn = el('button', { class: view === key ? 'active' : '', 'data-view': key, 'aria-label': label },
      icon(ic, 19), el('span', { class: 'tip' }, label));
    btn.addEventListener('click', () => show(key));
    rail.append(btn);
  }
}

// Switch to one of the four areas and load its data.
async function show(key) {
  view = key;
  renderRail();
  for (const [k] of VIEWS) $(`#view-${k}`).classList.toggle('active', k === key);
  $('#sidePanel').classList.remove('open');
  try {
    if (key === 'chat') {
      await refreshChatList();
      if (!mainChat.chat && state.chats.length) await mainChat.open(state.chats[0].id);
      else mainChat.render();
    } else if (key === 'group') {
      await group.loadGroups();
    } else if (key === 'work') {
      await workspace.loadWorkspace();
      if (!wsChat.chat) {
        const { chats } = await api('/chats?surface=workspace');
        if (chats.length) await wsChat.open(chats[0].id); else wsChat.render();
      }
    } else if (key === 'board') {
      if (!state.group) await group.loadGroups();
      await board.loadBoard();
    }
  } catch (err) { toast(err.message, 'err'); }
}

group.setAlertOpener(() => show('board'));
board.setMessageJumper(async (messageId) => {
  const msg = (state.messages || []).find((m) => m.id === messageId);
  await show('group');
  if (!msg) {
    // the message may live in another channel of the same group
    for (const ch of state.group.channels) {
      await group.openChannel(ch.id);
      if ((state.messages || []).some((m) => m.id === messageId)) break;
    }
  }
  setTimeout(() => group.flashMessage(messageId), 120);
  $('#sidePanel').classList.remove('open');
});

$('#btnMenu').replaceChildren(icon('board', 16));
$('#btnMenu').addEventListener('click', () => $(`#view-${view}`).classList.toggle('panel'));

// ---------------------------------------------------------------- settings
async function loadStatus() {
  try {
    state.status = await api('/status');
    const pill = $('#aiMode');
    const live = state.status.ai.mode === 'live';
    pill.className = `pill${live ? '' : ' demo'}`;
    clear(pill).append(el('span', { class: 'dot' }), el('span', {}, state.status.ai.label));
    pill.title = live ? 'Connected to the AI provider' : 'No AI provider key — answers come from the built-in demo responses';
  } catch { /* status is cosmetic */ }
}

$('#btnSettings').replaceChildren(icon('gear', 16));
$('#btnSettings').addEventListener('click', () => {
  const s = state.status || { ai: {}, retrieval: {}, agents: {} };
  const adv = el('details', { style: 'margin-top:10px' },
    el('summary', { style: 'cursor:pointer;color:var(--text-dim);font-size:13.5px' }, 'Advanced'),
    el('div', { class: 'meta', style: 'margin-top:10px;line-height:1.9' },
      el('div', {}, `AI provider: ${s.ai.mode === 'live' ? 'Groq' : 'none (demo responses)'}`),
      el('div', {}, `Model: ${s.ai.model || '—'}`),
      el('div', {}, `Related-claim search: ${s.retrieval.label || '—'}`),
      el('div', {}, `Agent orchestration: ${s.agents.orchestrator || '—'}`),
      s.ai.reason ? el('div', { style: 'color:var(--medium)' }, `Note: ${s.ai.reason}`) : null));

  const themeRow = el('div', { class: 'row-between' },
    el('span', {}, 'Theme'),
    el('span', { class: 'spacer', style: 'flex:1' }));
  const themeBtn = el('button', { class: 'btn sm' }, document.documentElement.dataset.theme === 'dark' ? 'Dark' : 'Light');
  themeBtn.addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    themeBtn.textContent = document.documentElement.dataset.theme === 'dark' ? 'Dark' : 'Light';
  });
  themeRow.append(themeBtn);

  const signOut = el('button', { class: 'btn sm danger' }, 'Sign out');
  signOut.addEventListener('click', () => { closeSocket(); setToken(''); location.reload(); });

  modal({
    title: 'Settings',
    body: el('div', {},
      el('p', { class: 'meta' }, `Signed in as ${state.me.display_name}.`),
      themeRow,
      el('div', { class: 'row-between', style: 'margin-top:12px' }, el('span', {}, 'Session'), el('span', { class: 'spacer', style: 'flex:1' }), signOut),
      adv),
    cancelLabel: 'Close',
  });
});

$('#userChip').addEventListener('click', () => $('#btnSettings').click());

// ---------------------------------------------------------------- demo
async function loadDemo(button) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Loading demo…';
  try {
    try {
      await api('/demo/load', { method: 'POST', body: {} });
    } catch (err) {
      // A public deployment protects the reset with a passcode.
      if (err.status !== 403) throw err;
      const passcode = window.prompt('This deployment needs the demo passcode to reset the data.');
      if (!passcode) return;
      await api('/demo/load', { method: 'POST', body: { passcode } });
    }
    // The reset removed every session, so sign this window out too.
    closeSocket();
    setToken('');
    toast('Demo loaded. Pick who you are.');
    await showGate();
  } catch (err) {
    toast(err.message || 'Could not load the demo.', 'err');
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}
$('#btnDemo').addEventListener('click', (e) => loadDemo(e.currentTarget));
$('#gateDemo').addEventListener('click', (e) => loadDemo(e.currentTarget));

// ---------------------------------------------------------------- sign in
async function showGate() {
  $('#app').classList.add('hidden');
  $('#gate').style.display = 'grid';
  const list = clear($('#gateList'));
  let users = [];
  try { ({ users } = await api('/users')); } catch { /* empty database */ }
  if (!users.length) {
    list.append(el('p', { class: 'meta' }, 'No users yet. Load the demo to create the sample team.'));
    return;
  }
  for (const u of users) {
    const row = el('button', { class: 'whochip' }, avatar(u.display_name, u.accent, 'lg'),
      el('span', {}, el('div', { class: 'nm' }, u.display_name),
        el('div', { class: 'rl' }, `@${u.username}`)));
    row.addEventListener('click', () => signIn(u.username));
    list.append(row);
  }
}

// Sign in as a user, store the token and open the app.
async function signIn(username) {
  try {
    const { token, user } = await api('/login', { method: 'POST', body: { username } });
    setToken(token);
    state.me = user;
    await start();
  } catch (err) { toast(err.message, 'err'); }
}

// App entry point: restore the session or show sign-in.
async function start() {
  $('#gate').style.display = 'none';
  $('#app').classList.remove('hidden');
  $('#meName').textContent = state.me.display_name;
  const av = $('#meAvatar');
  av.textContent = state.me.display_name.split(/\s+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase();
  av.style.background = state.me.accent;
  connectSocket();
  await loadStatus();
  try { const { groups } = await api('/groups'); state.groups = groups; } catch { /* ignore */ }
  await show('chat');
}

// ---------------------------------------------------------------- boot
$('#spClose').replaceChildren(icon('close', 16));
$('#spClose').addEventListener('click', () => $('#sidePanel').classList.remove('open'));
group.initGroupComposer();
group.initGroupLive();
board.initBoardLive();
workspace.initWorkspace();
renderRail();

on('signed-out', () => { closeSocket(); showGate(); });
on('ws:outputs', () => { if (view === 'work') workspace.loadWorkspace(); });

(async () => {
  if (state.token) {
    try {
      const { user } = await api('/me');
      state.me = user;
      await start();
      return;
    } catch { setToken(''); }
  }
  await showGate();
})();
