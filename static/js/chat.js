// Private AI chat. Used by Individual Chat and by the Individual Workspace.

import { api, stream, state } from './api.js';
import { $, autoGrow, clear, el, emptyState, icon, markdown, skeleton, toast } from './ui.js';

// Start a new individual chat.
export function createChat({ surface, threadEl, scrollEl, inputEl, sendEl, titleEl, onAfterReply, placeholderTitle }) {
  let chat = null;
  let messages = [];
  let busy = false;

  autoGrow(inputEl);

  function scrollDown() { scrollEl.scrollTop = scrollEl.scrollHeight; }

  function renderTurn(msg) {
    const turn = el('div', { class: `turn ${msg.role}` });
    if (msg.role === 'user') {
      turn.append(el('div', { class: 'who' }, 'You'), el('div', { class: 'bubble' }, markdown(msg.content)));
    } else {
      const who = el('div', { class: 'who' }, icon('sparkle', 14), 'Projecute');
      const body = el('div', { class: 'md-host' }, markdown(msg.content));
      turn.append(who, body);
      turn.dataset.assistant = '1';
    }
    return turn;
  }

  function render() {
    clear(threadEl);
    if (!chat) {
      threadEl.append(emptyState({
        title: 'Start a chat',
        text: surface === 'workspace'
          ? 'Work something out here, then turn the result into a named item in the work panel.'
          : 'Ask a question, think something through, or learn something new. Only you can see this.',
        actionLabel: 'New chat',
        onAction: () => newChat(),
      }));
      titleEl.textContent = placeholderTitle;
      return;
    }
    titleEl.textContent = chat.title;
    if (!messages.length) {
      threadEl.append(emptyState({
        title: chat.title === 'New chat' ? 'What are you working on?' : chat.title,
        text: 'Type below to begin. Replies stream in as they are written.',
      }));
      return;
    }
    messages.forEach((m) => threadEl.append(renderTurn(m)));
    scrollDown();
  }

  async function open(chatId) {
    threadEl.replaceChildren(skeleton(4));
    const data = await api(`/chats/${chatId}`);
    chat = data.chat;
    messages = data.messages;
    render();
  }

  async function newChat(title) {
    const data = await api('/chats', { method: 'POST', body: { surface, title } });
    chat = data.chat;
    messages = [];
    render();
    inputEl.focus();
    return chat;
  }

  async function send() {
    const text = inputEl.value.trim();
    if (!text || busy) return;
    if (!chat) await newChat();
    busy = true;
    sendEl.disabled = true;
    inputEl.value = '';
    inputEl.style.height = 'auto';

    if (threadEl.querySelector('.empty')) clear(threadEl);
    threadEl.append(renderTurn({ role: 'user', content: text }));
    const pending = el('div', { class: 'turn assistant' },
      el('div', { class: 'who' }, icon('sparkle', 14), 'Projecute'), skeleton(2));
    threadEl.append(pending);
    scrollDown();

    let answer = '';
    let host = null;
    try {
      await stream(`/chats/${chat.id}/messages`, { content: text }, (ev) => {
        if (ev.type === 'delta') {
          answer += ev.text;
          if (!host) { clear(pending).append(el('div', { class: 'who' }, icon('sparkle', 14), 'Projecute')); host = el('div'); pending.append(host); }
          clear(host).append(markdown(answer));
          scrollDown();
        } else if (ev.type === 'done') {
          messages.push({ role: 'user', content: text });
          messages.push({ role: 'assistant', content: ev.content, id: ev.id });
          clear(pending).append(el('div', { class: 'who' }, icon('sparkle', 14), 'Projecute'), markdown(ev.content));
          if (chat.title === 'New chat') { chat.title = text.slice(0, 48); titleEl.textContent = chat.title; }
        }
      });
      if (onAfterReply) onAfterReply(chat, answer);
    } catch (err) {
      pending.remove();
      toast(err.message, 'err');
    } finally {
      busy = false;
      sendEl.disabled = false;
      scrollDown();
    }
  }

  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  sendEl.addEventListener('click', send);
  sendEl.replaceChildren(icon('send', 16));

  return {
    render,
    open,
    newChat,
    send,
    get chat() { return chat; },
    get lastAnswer() { return messages.length ? messages[messages.length - 1].content : ''; },
    reset() { chat = null; messages = []; render(); },
  };
}

// --------------------------------------------------------- chat history list
export function renderChatList({ container, chats, activeId, onOpen, onRename, onDelete, query }) {
  clear(container);
  const q = (query || '').trim().toLowerCase();
  const visible = chats.filter((c) => !q || c.title.toLowerCase().includes(q) || (c.preview || '').toLowerCase().includes(q));
  if (!visible.length) {
    container.append(emptyState({
      art: 'chat',
      title: q ? 'No chats match' : 'No chats yet',
      text: q ? 'Try a different word from the chat you are looking for.' : 'Your conversations will be listed here by date.',
    }));
    return;
  }
  const buckets = new Map();
  for (const c of visible) {
    const key = bucketOf(c.updated_at);
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(c);
  }
  for (const [label, items] of buckets) {
    container.append(el('div', { class: 'sectionlabel' }, label));
    for (const c of items) {
      const row = el('button', { class: `listitem${c.id === activeId ? ' active' : ''}` },
        el('span', { class: 'label' }, c.title));
      row.addEventListener('click', () => onOpen(c));
      const actions = el('span', { class: 'rowactions' });
      const rename = el('button', { class: 'iconbtn', title: 'Rename', 'aria-label': `Rename ${c.title}` }, icon('pencil', 13));
      rename.addEventListener('click', (e) => { e.stopPropagation(); onRename(c); });
      const del = el('button', { class: 'iconbtn', title: 'Delete', 'aria-label': `Delete ${c.title}` }, icon('trash', 13));
      del.addEventListener('click', (e) => { e.stopPropagation(); onDelete(c); });
      actions.append(rename, del);
      row.append(actions);
      container.append(row);
    }
  }
}

// Date group label for the chat list (Today, Yesterday, ...).
function bucketOf(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const days = Math.floor((new Date(now.getFullYear(), now.getMonth(), now.getDate()) -
    new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return 'Previous 7 days';
  if (days < 30) return 'Previous 30 days';
  return 'Older';
}
