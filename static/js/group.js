// Group chat: channels, grouped messages, replies, reactions, typing, AI modes.

import { api, on, state } from './api.js';
import { $, autoGrow, avatar, clear, el, emptyState, icon, markdown, relative, sidePanel, skeleton, timeOf, toast } from './ui.js';

const EMOJI = ['👍', '🎯', '🔥', '🙌', '👀'];
// This module's state: the composer's AI mode ('none', 'public' or 'private'),
// the message being replied to, and the typing-indicator timers.
let aiMode = 'none';
let replyTo = null;
let typingTimer = null;
let lastTypedAt = 0;
let openAlert = null;   // callback supplied by app.js

// Let app.js provide a function that opens an alert.
export function setAlertOpener(fn) { openAlert = fn; }

// Load the user's groups and open the current one.
export async function loadGroups() {
  const { groups } = await api('/groups');
  state.groups = groups;
  renderRail();
  if (groups.length) await openGroup(state.group?.group?.id && groups.some((g) => g.id === state.group.group.id)
    ? state.group.group.id : groups[0].id);
  else {
    clear($('#groupMsgs')).append(emptyState({
      art: 'group', title: 'No groups yet',
      text: 'Load the demo to join Monarch Core and see the shared workspace fill up.',
      actionLabel: 'Load demo', onAction: () => document.querySelector('#btnDemo').click(),
    }));
  }
}

// Draw the list of groups.
function renderRail() {
  const rail = clear($('#serverRail'));
  for (const g of state.groups) {
    const orb = el('button', {
      class: `orb${state.group?.group?.id === g.id ? ' active' : ''}`,
      title: g.name, 'aria-label': g.name,
    }, g.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join(''));
    orb.addEventListener('click', () => openGroup(g.id));
    rail.append(orb);
  }
}

// Open a group: channels, members, host controls and messages.
export async function openGroup(groupId) {
  const data = await api(`/groups/${groupId}`);
  state.group = data;
  state.channelId = data.default_channel_id || data.channels[0]?.id || null;
  $('#groupName').textContent = data.group.name;
  $('#boardGroupName').textContent = data.group.name;
  $('#groupRole').textContent = data.is_host ? 'You are the host' : 'Member';
  renderRail();
  renderChannels();
  renderMembers();
  renderHostControls();
  updateAiSeg();
  await openChannel(state.channelId);
  refreshPrivateHistoryIfOpen();
}

// Draw the channel list.
function renderChannels() {
  const list = clear($('#channelList'));
  list.append(el('div', { class: 'sectionlabel' }, 'Channels'));
  for (const ch of state.group.channels) {
    const row = el('button', { class: `listitem${ch.id === state.channelId ? ' active' : ''}` },
      el('span', { class: 'label' }, `# ${ch.name}`));
    row.addEventListener('click', () => openChannel(ch.id));
    list.append(row);
  }
}

// Draw the member list with host role and online state.
function renderMembers() {
  const list = clear($('#memberList'));
  for (const m of state.group.members) {
    list.append(el('div', { class: 'member' },
      avatar(m.display_name, m.accent),
      el('span', { style: 'flex:1' }, m.display_name),
      m.role === 'host' ? el('span', { class: 'role' }, 'host') : null,
      el('span', { class: `status${m.online ? ' on' : ''}`, title: m.online ? 'Online' : 'Offline' })));
  }
}

// Host-only switches for public AI and private help.
function renderHostControls() {
  const box = clear($('#hostControls'));
  const g = state.group.group;
  if (!state.group.is_host) {
    box.append(el('div', { class: 'meta' },
      `AI in this group: ${g.allow_public_ai ? 'group answers on' : 'group answers off'}, ${g.allow_private_ai ? 'private help on' : 'private help off'}.`));
    return;
  }
  box.append(el('div', { class: 'sectionlabel', style: 'padding-top:0' }, 'Host controls'));
  for (const [key, label] of [['allow_public_ai', "Ask the group's AI"], ['allow_private_ai', 'Private help']]) {
    const btn = el('button', { class: 'listitem' },
      el('span', { class: 'label' }, label),
      el('span', { class: 'count' }, g[key] ? 'on' : 'off'));
    btn.addEventListener('click', async () => {
      try {
        const { group } = await api(`/groups/${g.id}/settings`, { method: 'PATCH', body: { [key]: !g[key] } });
        state.group.group = group;
        renderHostControls();
        updateAiSeg();
        toast(`${label} is now ${group[key] ? 'on' : 'off'} for everyone`);
      } catch (err) { toast(err.message, 'err'); }
    });
    box.append(btn);
  }
}

// Enable or disable the composer's AI modes to match the host's settings.
function updateAiSeg() {
  const g = state.group.group;
  for (const btn of $('#aiSeg').children) {
    const mode = btn.dataset.mode;
    btn.disabled = (mode === 'public' && !g.allow_public_ai) || (mode === 'private' && !g.allow_private_ai);
    if (btn.disabled && aiMode === mode) aiMode = 'none';
    btn.classList.toggle('on', aiMode === mode);
  }
  $('#aiHint').textContent = {
    none: '',
    public: 'The answer is posted to the group.',
    private: 'Only you see the answer. The group sees that you used AI.',
  }[aiMode];
}

// Load and show one channel's messages.
export async function openChannel(channelId) {
  state.channelId = channelId;
  const ch = state.group.channels.find((c) => c.id === channelId);
  $('#channelName').textContent = `# ${ch?.name || ''}`;
  $('#groupInput').placeholder = `Message # ${ch?.name || ''}`;
  renderChannels();
  const box = clear($('#groupMsgs'));
  box.append(skeleton(5));
  const { messages } = await api(`/groups/${state.group.group.id}/channels/${channelId}/messages`);
  state.messages = messages;
  renderMessages();
  await loadPrivateHelp();
}

// Draw the messages, grouping consecutive ones by the same author.
function renderMessages() {
  const box = clear($('#groupMsgs'));
  if (!state.messages.length) {
    box.append(emptyState({
      art: 'group', title: 'Nothing here yet',
      text: 'Say what you are building. The PM agent reads this channel when someone asks for a brief.',
    }));
    return;
  }
  let prev = null;
  for (const m of state.messages) {
    box.append(messageNode(m, prev));
    prev = m;
  }
  box.scrollTop = box.scrollHeight;
}

// One message: text, replies, reactions, or an AI-usage notice.
function messageNode(m, prev) {
  if (m.kind === 'notice') {
    return el('div', { class: 'notice', 'data-id': m.id },
      el('span', { class: 'lock' }, icon('lock', 13)), m.content,
      el('span', { class: 'meta', style: 'margin-left:auto' }, timeOf(m.created_at)));
  }
  const isAi = m.kind === 'ai_public';
  // Messages from the same person within 5 minutes are grouped under one name.
  const cont = prev && prev.kind === m.kind && prev.user_id === m.user_id && !m.reply_to_id &&
    (m.created_at - prev.created_at) < 300 && prev.kind !== 'notice';
  const node = el('div', { class: `msg${cont ? ' cont' : ''}${isAi ? ' ai' : ''}`, 'data-id': m.id });
  node.append(isAi ? avatarForAi() : avatar(m.author || '?', m.accent));

  const col = el('div', { style: 'min-width:0' });
  if (m.reply_to_id) {
    const target = (state.messages || []).find((x) => x.id === m.reply_to_id);
    if (target) {
      const ref = el('div', { class: 'replyref' }, icon('reply', 12),
        el('span', { class: 'truncate' }, `${target.author || 'Projecute'}: ${target.content.slice(0, 70)}`));
      ref.addEventListener('click', () => flash(target.id));
      col.append(ref);
    }
  }
  if (!cont) {
    col.append(el('div', { class: 'head' },
      el('span', { class: 'name' }, isAi ? 'Projecute AI' : m.author),
      isAi ? el('span', { class: 'aitag' }, icon('sparkle', 11), 'answered the group') : null,
      el('span', { class: 'time' }, timeOf(m.created_at))));
  }
  col.append(el('div', { class: 'text' }, markdown(m.content)));

  if (m.reactions?.length) {
    const row = el('div', { class: 'reactions' });
    for (const r of m.reactions) {
      const mine = r.users.includes(state.me.id);
      const chip = el('button', { class: `reaction${mine ? ' mine' : ''}` }, r.emoji, String(r.count));
      chip.addEventListener('click', () => react(m.id, r.emoji));
      row.append(chip);
    }
    col.append(row);
  }
  node.append(col);

  // Hover tools: quick reactions and reply.
  const tools = el('div', { class: 'tools' });
  for (const e of EMOJI) {
    const b = el('button', { class: 'iconbtn', title: `React ${e}`, style: 'font-size:14px' }, e);
    b.addEventListener('click', () => react(m.id, e));
    tools.append(b);
  }
  const rep = el('button', { class: 'iconbtn', title: 'Reply' }, icon('reply', 14));
  rep.addEventListener('click', () => setReply(m));
  tools.append(rep);
  node.append(tools);
  return node;
}

// Avatar used for public AI answers.
function avatarForAi() {
  const node = el('span', { class: 'avatar' }, '');
  node.style.background = 'var(--accent-soft)';
  node.style.color = 'var(--accent)';
  node.append(icon('sparkle', 13));
  return node;
}

// Scroll to a message and highlight it briefly.
function flash(id) {
  const node = $(`#groupMsgs .msg[data-id="${id}"]`) || $(`#groupMsgs .notice[data-id="${id}"]`);
  if (!node) return;
  node.scrollIntoView({ block: 'center', behavior: 'smooth' });
  node.classList.remove('flash');
  void node.offsetWidth;
  node.classList.add('flash');
}
export { flash as flashMessage };

// Toggle a reaction on a message.
async function react(messageId, emoji) {
  try { await api(`/groups/${state.group.group.id}/messages/${messageId}/reactions`, { method: 'POST', body: { emoji } }); }
  catch (err) { toast(err.message, 'err'); }
}

// Start replying to a message.
function setReply(m) {
  replyTo = m;
  const bar = clear($('#replyBar'));
  const chip = el('div', { class: 'row-between', style: 'padding:7px 12px;margin-bottom:8px;border:1px solid var(--line);border-radius:9px;font-size:13px' },
    icon('reply', 13),
    el('span', { class: 'truncate', style: 'flex:1' }, `Replying to ${m.author}: ${m.content.slice(0, 60)}`));
  const x = el('button', { class: 'iconbtn' }, icon('close', 13));
  x.addEventListener('click', () => { replyTo = null; clear($('#replyBar')); });
  chip.append(x);
  bar.append(chip);
  $('#groupInput').focus();
}

// ---------------------------------------------------------------- private help
async function loadPrivateHelp() {
  const { help } = await api(`/groups/${state.group.group.id}/private-help`);
  renderPrivate(help[0] || null);
}

// Draw the private help panel.
function renderPrivate(item) {
  const area = clear($('#privateArea'));
  if (!item) return;
  const panel = el('div', { class: 'privatepanel' });
  const head = el('div', { class: 'ph' }, icon('lock', 13), 'Private help — only you can see this',
    el('span', { class: 'spacer' }), el('span', { class: 'meta' }, relative(item.created_at)));
  // Closing only hides the panel; the question and answer stay saved in My private AI.
  const close = el('button', { class: 'iconbtn', title: 'Close (kept in My private AI)', 'aria-label': 'Close private help' },
    icon('close', 13));
  close.addEventListener('click', () => {
    clear($('#privateArea'));
    toast('Kept in My private AI');
  });
  head.append(close);
  panel.append(head, el('div', { class: 'meta', style: 'margin-bottom:6px' }, `You asked: ${item.prompt}`), markdown(item.answer));
  area.append(panel);
}

// ---------------------------------------------------------------- my private AI
// Your private AI questions and answers in this group, newest first, with the time
// and channel of each. The server returns only the signed-in user's own (the last
// 20), so nobody else can open them.
async function showPrivateHistory() {
  if (!state.group) return;
  // Open the side panel at once with a loading placeholder, then fill it in.
  const body = el('div', {}, skeleton(3));
  sidePanel('My private AI', body);
  try {
    const { help } = await api(`/groups/${state.group.group.id}/private-help`);
    clear(body).append(el('p', { class: 'meta' }, 'Only you can see these. The group only saw that you used AI.'));
    if (!help.length) {
      body.append(emptyState({
        art: 'lock', title: 'No private questions yet',
        text: 'Choose Private help above the message box and ask anything. Your question and the answer are kept here.',
      }));
      return;
    }
    // One card per answer: when and in which channel, your question, then the AI's answer.
    for (const h of help) {
      const channel = state.group.channels.find((c) => c.id === h.channel_id);
      body.append(el('div', { class: 'card' },
        el('div', { class: 'meta' }, `${relative(h.created_at)} · ${timeOf(h.created_at)}${channel ? ` · #${channel.name}` : ''}`),
        el('p', { style: 'margin:6px 0 8px' }, el('strong', {}, 'You asked: '), h.prompt),
        markdown(h.answer)));
    }
  } catch (err) {
    clear(body);
    toast(err.message, 'err');
  }
}

// Keep the list current when it is already open (a new answer, or another group).
function refreshPrivateHistoryIfOpen() {
  if ($('#sidePanel').classList.contains('open') && $('#spTitle').textContent === 'My private AI') showPrivateHistory();
}

// ---------------------------------------------------------------- sending
export function initGroupComposer() {
  const input = $('#groupInput');
  autoGrow(input);
  $('#groupSend').replaceChildren(icon('send', 16));

  for (const btn of $('#aiSeg').children) {
    btn.addEventListener('click', () => { aiMode = btn.dataset.mode; updateAiSeg(); input.focus(); });
  }
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendGroupMessage(); }
    // Tell the others 'X is typing' at most every 2.5 seconds.
    else if (Date.now() - lastTypedAt > 2500) {
      lastTypedAt = Date.now();
      api(`/groups/${state.group.group.id}/typing`, { method: 'POST' }).catch(() => {});
    }
  });
  $('#groupSend').addEventListener('click', sendGroupMessage);
  // The 'My private AI' button in the channel header opens your saved private answers.
  $('#privateHistory').prepend(icon('lock', 13));
  $('#privateHistory').addEventListener('click', showPrivateHistory);
}

// Send a message (plain, public AI or private help).
async function sendGroupMessage() {
  const input = $('#groupInput');
  const content = input.value.trim();
  if (!content || !state.group) return;
  const btn = $('#groupSend');
  btn.disabled = true;
  input.value = '';
  input.style.height = 'auto';
  const body = { content, ai_mode: aiMode, reply_to_id: replyTo?.id || null };
  replyTo = null;
  clear($('#replyBar'));
  try {
    const res = await api(`/groups/${state.group.group.id}/channels/${state.channelId}/messages`, { method: 'POST', body });
    // Private help comes back only in this response, never over the group's live feed.
    if (res.private_help) {
      renderPrivate(res.private_help);
      refreshPrivateHistoryIfOpen();
    }
    if (res.alert && openAlert) {
      toast('The Architect agent flagged something in the shared workspace', 'err');
    }
  } catch (err) {
    input.value = content;
    toast(err.message, 'err');
  } finally {
    btn.disabled = false;
    input.focus();
  }
}

// ---------------------------------------------------------------- live
export function initGroupLive() {
  // A new or updated message (e.g. a reaction) in the open channel: redraw the list.
  on('ws:group_message', ({ group_id, data }) => {
    if (!state.group || group_id !== state.group.group.id) return;
    if (data.channel_id !== state.channelId) return;
    state.messages = state.messages || [];
    const idx = state.messages.findIndex((m) => m.id === data.id);
    if (idx >= 0) state.messages[idx] = data;
    else state.messages.push(data);
    renderMessages();
  });
  // Someone is typing: show it for 2.6 seconds.
  on('ws:typing', ({ group_id, data }) => {
    if (!state.group || group_id !== state.group.group.id) return;
    const bar = $('#typing');
    clear(bar).append(el('span', { class: 'dots' }, el('i'), el('i'), el('i')), `${data.user} is typing`);
    clearTimeout(typingTimer);
    typingTimer = setTimeout(() => clear(bar), 2600);
  });
  // The host changed the AI settings: update the switches and the composer.
  on('ws:group', ({ group_id, data }) => {
    if (state.group && group_id === state.group.group.id) {
      state.group.group = data;
      renderHostControls();
      updateAiSeg();
    }
  });
}
