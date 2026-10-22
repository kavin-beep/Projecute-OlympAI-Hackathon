// Individual workspace: private named items, organised by project.

import { api, state } from './api.js';
import { $, clear, codeBlock, el, emptyState, icon, markdown, modal, relative, skeleton, toast } from './ui.js';

const KIND_ICON = { content: 'doc', email: 'mail', code: 'code', image: 'image', audio: 'audio' };
const KIND_LABEL = { content: 'Content', email: 'Email draft', code: 'Code', image: 'Image', audio: 'Audio' };

let searchQuery = '';
let openItemId = null;
let chatRef = null;      // the workspace chat, for "from this chat" links

// Link the workspace to the chat an item was created from.
export function bindWorkspaceChat(chat) { chatRef = chat; }

// Load the user's projects and items.
export async function loadWorkspace() {
  const [{ projects }, { items }] = await Promise.all([api('/projects'), api('/items')]);
  state.projects = projects;
  state.items = items;
  if (!state.projectId || !projects.some((p) => p.id === state.projectId)) state.projectId = projects[0]?.id || null;
  renderProjects();
  renderItems();
}

// Draw the project list.
function renderProjects() {
  const list = clear($('#projectList'));
  list.append(el('div', { class: 'sectionlabel' }, 'Projects'));
  if (!state.projects.length) {
    list.append(el('div', { class: 'meta', style: 'padding:8px' }, 'Make a project to group your items.'));
  }
  const all = el('button', { class: `listitem${state.projectId === null ? ' active' : ''}` },
    el('span', { class: 'label' }, 'All items'),
    el('span', { class: 'count' }, String(state.items.length)));
  all.addEventListener('click', () => { state.projectId = null; renderProjects(); renderItems(); });
  list.append(all);
  for (const p of state.projects) {
    const n = state.items.filter((i) => i.project_id === p.id).length;
    const row = el('button', { class: `listitem${p.id === state.projectId ? ' active' : ''}` },
      el('span', { class: 'label' }, p.name), el('span', { class: 'count' }, String(n)));
    row.addEventListener('click', () => { state.projectId = p.id; renderProjects(); renderItems(); });
    list.append(row);
  }
}

// Items in the selected project that match the search.
function visibleItems() {
  const q = searchQuery.trim().toLowerCase();
  return state.items.filter((i) =>
    (state.projectId === null || i.project_id === state.projectId) &&
    (!q || i.name.toLowerCase().includes(q)));
}

// Draw the item grid.
export function renderItems() {
  const area = clear($('#itemArea'));
  $('#wsPanelTitle').textContent = 'Work panel';
  openItemId = null;
  $('#wsBackToChat').style.display = 'none';
  const items = visibleItems();
  if (!items.length) {
    area.append(emptyState({
      art: 'work',
      title: searchQuery ? 'No items match that name' : 'No items yet',
      text: searchQuery
        ? 'Items are searched by name. Clear the search to see everything.'
        : 'Generate content, an email draft, code, an image or audio — each one is saved as a named item you can find later.',
      actionLabel: searchQuery ? null : 'New item',
      onAction: () => newItemDialog(),
    }));
    return;
  }
  for (const item of items) area.append(itemCard(item));
}

// One item card: name, type, and whether it is shared.
function itemCard(item) {
  const card = el('div', { class: 'card itemcard' });
  const head = el('div', { class: 'cardhead' },
    el('span', { class: 'kindtag' }, icon(KIND_ICON[item.kind], 12), KIND_LABEL[item.kind]),
    el('h4', { style: 'flex:1' }, item.name));
  card.append(head);
  card.append(el('div', { class: 'meta truncate' }, item.kind === 'image' ? item.body : item.body.slice(0, 120)));
  const foot = el('div', { class: 'row-between', style: 'margin-top:10px' },
    item.shared_group_id
      ? el('span', { class: 'lockbadge sharedbadge' }, icon('share', 11), 'Shared to group')
      : el('span', { class: 'lockbadge' }, icon('lock', 11), 'Private'),
    el('span', { class: 'spacer' }),
    el('span', { class: 'meta' }, relative(item.updated_at)));
  card.append(foot);
  card.addEventListener('click', () => openItem(item.id));
  return card;
}

// Open an item to view, edit, share or delete it.
export async function openItem(itemId) {
  const area = clear($('#itemArea'));
  area.append(skeleton(4));
  const { item } = await api(`/items/${itemId}`);
  openItemId = itemId;
  clear(area);
  $('#wsPanelTitle').textContent = item.name;

  const back = el('button', { class: 'btn sm ghost' }, icon('back', 13), 'All items');
  back.addEventListener('click', renderItems);
  area.append(el('div', { class: 'row-between', style: 'margin-bottom:12px' }, back,
    el('span', { class: 'spacer' }),
    item.shared_group_id
      ? el('span', { class: 'lockbadge sharedbadge' }, icon('share', 11), 'Shared')
      : el('span', { class: 'lockbadge' }, icon('lock', 11), 'Private')));

  const card = el('div', { class: 'card' });
  card.append(el('div', { class: 'cardhead' },
    el('span', { class: 'kindtag' }, icon(KIND_ICON[item.kind], 12), KIND_LABEL[item.kind]),
    el('h4', {}, item.name)));

  if (item.generator === 'mock' && (item.kind === 'image' || item.kind === 'audio')) {
    card.append(el('div', { class: 'meta', style: 'margin-bottom:10px;color:var(--medium)' },
      item.kind === 'image'
        ? 'Placeholder image. Real image generation will be enhanced and added in future development.'
        : 'Your browser reads the script aloud. Real audio generation will be enhanced and added in future development.'));
  }

  if (item.kind === 'image') {
    card.append(el('img', { class: 'gen', src: item.data_url, alt: item.name }));
    card.append(el('div', { class: 'meta', style: 'margin-top:8px' }, item.body));
  } else if (item.kind === 'audio') {
    const play = el('button', { class: 'btn' }, icon('audio', 14), 'Play');
    let speaking = false;
    play.addEventListener('click', () => {
      if (!('speechSynthesis' in window)) return toast('This browser cannot read text aloud.', 'err');
      if (speaking) { speechSynthesis.cancel(); speaking = false; clear(play).append(icon('audio', 14), 'Play'); return; }
      const utter = new SpeechSynthesisUtterance(item.body);
      utter.onend = () => { speaking = false; clear(play).append(icon('audio', 14), 'Play'); };
      speechSynthesis.speak(utter);
      speaking = true;
      clear(play).append(icon('close', 14), 'Stop');
    });
    card.append(play, el('div', { class: 'meta', style: 'margin-top:10px' }, item.body));
  } else if (item.kind === 'code') {
    const editor = el('textarea', { class: 'field mono', style: 'min-height:240px' });
    editor.value = item.body;
    card.append(editor);
    card.append(el('div', { class: 'meta', style: 'margin-top:8px' }, 'Editable here. Projecute never runs code.'));
    const save = el('button', { class: 'btn sm primary', style: 'margin-top:10px' }, 'Save changes');
    save.addEventListener('click', async () => {
      await api(`/items/${item.id}`, { method: 'PATCH', body: { body: editor.value } });
      await loadWorkspace();
      toast('Saved');
    });
    card.append(save);
  } else {
    card.append(markdown(item.body));
    const edit = el('button', { class: 'btn sm', style: 'margin-top:10px' }, icon('pencil', 13), 'Edit text');
    edit.addEventListener('click', () => {
      const area2 = el('textarea', { class: 'field', style: 'min-height:220px' });
      area2.value = item.body;
      const save = el('button', { class: 'btn sm primary', style: 'margin-top:10px' }, 'Save changes');
      save.addEventListener('click', async () => {
        await api(`/items/${item.id}`, { method: 'PATCH', body: { body: area2.value } });
        await loadWorkspace();
        openItem(item.id);
        toast('Saved');
      });
      edit.replaceWith(area2, save);
    });
    card.append(edit);
  }
  area.append(card);

  // actions
  const actions = el('div', { class: 'stack' });
  if (item.source_chat_id) {
    const link = el('button', { class: 'btn wide' }, icon('chat', 14), 'Open the chat this came from');
    link.addEventListener('click', async () => {
      if (!chatRef) return;
      await chatRef.open(item.source_chat_id);
      document.querySelector('#view-work').classList.remove('panel');
      toast('Opened the source chat');
    });
    actions.append(link);
  }
  if (!item.shared_group_id) {
    const share = el('button', { class: 'btn wide' }, icon('share', 14), 'Share to a group workspace');
    share.addEventListener('click', () => shareDialog(item));
    actions.append(share);
  } else {
    const unshare = el('button', { class: 'btn wide' }, icon('lock', 14), 'Make private again');
    unshare.addEventListener('click', async () => {
      await api(`/items/${item.id}/unshare`, { method: 'POST' });
      await loadWorkspace();
      openItem(item.id);
      toast('This item is private again');
    });
    actions.append(unshare);
  }
  const del = el('button', { class: 'btn wide danger' }, icon('trash', 14), 'Delete item');
  del.addEventListener('click', () => {
    modal({
      title: 'Delete this item?',
      body: el('p', {}, `"${item.name}" will be removed. This cannot be undone.`),
      confirmLabel: 'Delete', danger: true,
      onConfirm: async () => {
        await api(`/items/${item.id}`, { method: 'DELETE' });
        await loadWorkspace();
        toast('Item deleted');
      },
    });
  });
  actions.append(del);
  area.append(actions);
}

// Dialog to share an item into a group.
function shareDialog(item) {
  if (!state.groups.length) return toast('You are not in a group yet.', 'err');
  const select = el('select', { class: 'field' });
  for (const g of state.groups) select.append(el('option', { value: g.id }, g.name));
  modal({
    title: 'Share to a group workspace',
    body: el('div', {},
      el('p', { class: 'meta' }, 'Everyone in the group will be able to open this item. Nothing else from your workspace is shared.'),
      el('div', { class: 'row' }, el('label', {}, 'Group'), select)),
    confirmLabel: 'Share item',
    onConfirm: async () => {
      await api(`/items/${item.id}/share`, { method: 'POST', body: { group_id: select.value } });
      await loadWorkspace();
      openItem(item.id);
      toast('Shared to the group workspace');
    },
  });
}

// Dialog to generate a new named item.
export function newItemDialog(prefill = {}) {
  const name = el('input', { class: 'field', placeholder: 'Checkout email to the client' });
  const kind = el('select', { class: 'field' });
  for (const [value, label] of Object.entries(KIND_LABEL)) kind.append(el('option', { value }, label));
  const project = el('select', { class: 'field' });
  project.append(el('option', { value: '' }, 'No project'));
  for (const p of state.projects) project.append(el('option', { value: p.id }, p.name));
  if (state.projectId) project.value = state.projectId;
  const prompt = el('textarea', { class: 'field', style: 'min-height:110px', placeholder: 'Say what you want generated.' });
  if (prefill.prompt) prompt.value = prefill.prompt;
  if (prefill.kind) kind.value = prefill.kind;

  const fromChat = chatRef?.chat
    ? el('div', { class: 'meta' }, `This item will link back to "${chatRef.chat.title}".`)
    : null;

  modal({
    title: 'New item',
    body: el('div', {},
      el('div', { class: 'row' }, el('label', {}, 'Name — this is how you will find it later'), name),
      el('div', { class: 'row' }, el('label', {}, 'Type'), kind),
      el('div', { class: 'row' }, el('label', {}, 'Project'), project),
      el('div', { class: 'row' }, el('label', {}, 'What should it say?'), prompt),
      fromChat),
    confirmLabel: 'Generate item',
    onConfirm: async () => {
      if (!name.value.trim()) { toast('Name the item so you can find it later.', 'err'); return false; }
      if (!prompt.value.trim()) { toast('Say what you want generated.', 'err'); return false; }
      try {
        const { item } = await api('/items/generate', {
          method: 'POST',
          body: {
            name: name.value.trim(), kind: kind.value, prompt: prompt.value.trim(),
            project_id: project.value || null, chat_id: chatRef?.chat?.id || null,
          },
        });
        await loadWorkspace();
        openItem(item.id);
        toast('Item created');
      } catch (err) { toast(err.message, 'err'); return false; }
    },
  });
}

// Dialog to create a project.
export function newProjectDialog() {
  const name = el('input', { class: 'field', placeholder: 'Checkout work' });
  modal({
    title: 'New project',
    body: el('div', { class: 'row' }, el('label', {}, 'Project name'), name),
    confirmLabel: 'Create project',
    onConfirm: async () => {
      if (!name.value.trim()) { toast('Give the project a name.', 'err'); return false; }
      const { project } = await api('/projects', { method: 'POST', body: { name: name.value.trim() } });
      state.projectId = project.id;
      await loadWorkspace();
      toast('Project created');
    },
  });
}

// Wire up the workspace toolbar and search.
export function initWorkspace() {
  $('#newItem').addEventListener('click', () => newItemDialog());
  $('#newProject').replaceChildren(icon('plus', 15));
  $('#newProject').addEventListener('click', newProjectDialog);
  $('#itemSearch').addEventListener('input', (e) => { searchQuery = e.target.value; renderItems(); });
  $('#wsTogglePanel').addEventListener('click', () => $('#view-work').classList.add('panel'));
  $('#wsBackToChat').addEventListener('click', () => $('#view-work').classList.remove('panel'));
  const sync = () => {
    const narrow = window.innerWidth <= 1180;
    $('#wsTogglePanel').style.display = narrow ? '' : 'none';
    $('#wsBackToChat').style.display = narrow && openItemId ? '' : 'none';
  };
  window.addEventListener('resize', sync);
  sync();
}
