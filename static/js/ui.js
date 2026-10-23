// Shared UI helpers: icons, toasts, modals, markdown, formatting.

// Short names for finding elements: $('#id') for one, $$('.class') for all.
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// Create a DOM element with attributes and children.
export function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

// Remove all children of a node and return it.
export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

// ------------------------------------------------------------------ icons
// Hand-drawn line icons (SVG paths on a 20x20 grid), so no icon library is needed.
const P = (d, extra = '') => `<path d="${d}" ${extra}/>`;
const ICONS = {
  chat: P('M3 5.5A2.5 2.5 0 0 1 5.5 3h9A2.5 2.5 0 0 1 17 5.5v6a2.5 2.5 0 0 1-2.5 2.5H8l-4 3v-3H5.5A2.5 2.5 0 0 1 3 11.5z'),
  group: P('M7 9.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM14 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM2.5 16c0-2.2 2-3.8 4.5-3.8s4.5 1.6 4.5 3.8M13 12.4c2.2.1 4 1.5 4 3.6'),
  work: P('M3 6.5A1.5 1.5 0 0 1 4.5 5H8l1.5 2h6A1.5 1.5 0 0 1 17 8.5v6A1.5 1.5 0 0 1 15.5 16h-11A1.5 1.5 0 0 1 3 14.5z'),
  board: P('M3.5 4h13v12h-13zM3.5 8h13M8 8v8'),
  send: P('M3.4 10 16.5 4.2 11.3 16.6 9.4 11.3z', 'stroke-linejoin="round"'),
  sun: P('M10 13.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4ZM10 2.4v1.6M10 16v1.6M2.4 10H4M16 10h1.6M4.6 4.6l1.1 1.1M14.3 14.3l1.1 1.1M15.4 4.6l-1.1 1.1M5.7 14.3l-1.1 1.1'),
  moon: P('M15.5 12.4A6 6 0 0 1 7.6 4.5a6.2 6.2 0 1 0 7.9 7.9Z'),
  gear: P('M10 12.6a2.6 2.6 0 1 0 0-5.2 2.6 2.6 0 0 0 0 5.2ZM16.2 10c0-.5-.05-.9-.13-1.3l1.5-1.1-1.6-2.8-1.75.7a6 6 0 0 0-2.2-1.3L11.7 2.4h-3.4l-.3 1.8a6 6 0 0 0-2.2 1.3l-1.75-.7-1.6 2.8 1.5 1.1a6.3 6.3 0 0 0 0 2.6l-1.5 1.1 1.6 2.8 1.75-.7a6 6 0 0 0 2.2 1.3l.3 1.8h3.4l.3-1.8a6 6 0 0 0 2.2-1.3l1.75.7 1.6-2.8-1.5-1.1c.08-.4.13-.84.13-1.3Z'),
  close: P('M5 5l10 10M15 5 5 15'),
  trash: P('M4.5 6h11M8 6V4.6h4V6M6 6l.7 9.4h6.6L14 6'),
  pencil: P('M4 16h3l8.2-8.2a1.6 1.6 0 0 0 0-2.3l-.7-.7a1.6 1.6 0 0 0-2.3 0L4 13z'),
  copy: P('M7 7h8v8H7zM5 13H4V4h9v1'),
  plus: P('M10 4.5v11M4.5 10h11'),
  lock: P('M5.5 9h9v6.5h-9zM7.5 9V6.8a2.5 2.5 0 0 1 5 0V9'),
  sparkle: P('M10 3.5 11.4 8 16 9.4 11.4 10.8 10 15.4 8.6 10.8 4 9.4 8.6 8z'),
  check: P('M4.5 10.5 8 14l7.5-8'),
  alert: P('M10 4.2 2.8 16.2h14.4zM10 9v3.2M10 14.2v.1'),
  doc: P('M5 3.5h6l4 4v9H5zM11 3.5V8h4'),
  mail: P('M3.5 5.5h13v9h-13zM3.5 6l6.5 5 6.5-5'),
  code: P('M7 7 4 10l3 3M13 7l3 3-3 3'),
  image: P('M3.5 4.5h13v11h-13zM3.5 12.5 7.5 9l3 2.5L13 9.5l3.5 3'),
  audio: P('M5 8v4M8 5.5v9M11 7v6M14 9v2'),
  share: P('M7 10.8 13 7.6M7 9.2 13 12.4M14.5 7a1.9 1.9 0 1 0 0-3.8 1.9 1.9 0 0 0 0 3.8ZM5.5 11.9a1.9 1.9 0 1 0 0-3.8 1.9 1.9 0 0 0 0 3.8ZM14.5 16.8a1.9 1.9 0 1 0 0-3.8 1.9 1.9 0 0 0 0 3.8Z'),
  reply: P('M8 6 4.5 9.2 8 12.4M4.8 9.2h6.4a3.8 3.8 0 0 1 3.8 3.8v1.5'),
  emoji: P('M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM7.4 8.4v.1M12.6 8.4v.1M7 11.6c.7.9 1.7 1.4 3 1.4s2.3-.5 3-1.4'),
  back: P('M12 5 7 10l5 5'),
  clock: P('M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM10 6.2V10l2.6 1.6'),
};

// Inline SVG icon by name.
export function icon(name, size = 16, stroke = 1.6) {
  const span = document.createElement('span');
  span.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 20 20" fill="none" stroke="currentColor"
    stroke-width="${stroke}" stroke-linecap="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  span.style.display = 'inline-flex';
  return span;
}

// ------------------------------------------------------------------ toasts
// A short message in the corner that fades away (errors stay a little longer).
export function toast(message, kind = 'ok') {
  const node = el('div', { class: `toast ${kind}` }, el('span', { class: 'ic' }, icon(kind === 'err' ? 'alert' : 'check', 15)), message);
  $('#toasts').append(node);
  setTimeout(() => { node.style.opacity = '0'; node.style.transition = 'opacity .25s'; }, kind === 'err' ? 4600 : 2800);
  setTimeout(() => node.remove(), kind === 'err' ? 4900 : 3100);
}

// ------------------------------------------------------------------ modal
// A dialog. onConfirm may be async; returning false keeps the dialog open.
export function modal({ title, body, confirmLabel = 'Save', onConfirm, cancelLabel = 'Cancel', danger = false }) {
  const scrim = $('#scrim'), box = $('#modal');
  clear(box);
  const foot = el('div', { class: 'mf' });
  // Buttons: Cancel always; the confirm button only when there is something to confirm.
  const close = () => { scrim.classList.remove('open'); };
  foot.append(el('button', { class: 'btn ghost', onclick: close }, cancelLabel));
  if (onConfirm) {
    const go = el('button', { class: `btn ${danger ? 'danger' : 'primary'}` }, confirmLabel);
    go.addEventListener('click', async () => {
      go.disabled = true;
      try { const ok = await onConfirm(); if (ok !== false) close(); }
      finally { go.disabled = false; }
    });
    foot.append(go);
  }
  box.append(el('div', { class: 'mh' }, el('h3', {}, title)), el('div', { class: 'mb' }, body), foot);
  scrim.classList.add('open');
  setTimeout(() => { const f = box.querySelector('input,textarea,button.primary'); if (f) f.focus(); }, 60);
  return close;
}

// Clicking outside a dialog or pressing Escape closes it.
$('#scrim')?.addEventListener('click', (e) => { if (e.target.id === 'scrim') $('#scrim').classList.remove('open'); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { $('#scrim')?.classList.remove('open'); $('#sidePanel')?.classList.remove('open'); }
});

// ------------------------------------------------------------------ side panel
// Show content in the side panel on the right.
export function sidePanel(title, body) {
  $('#spTitle').textContent = title;
  clear($('#spBody')).append(body);
  $('#sidePanel').classList.add('open');
}
// Close the side panel.
export function closePanel() { $('#sidePanel').classList.remove('open'); }

// ------------------------------------------------------------------ text
// Make text safe to put into HTML (stops injected markup or scripts).
export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Inline Markdown: code, bold, italics and links (on escaped text).
function inline(text) {
  let out = escapeHtml(text);
  out = out.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  out = out.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return out;
}

/** Small, dependency-free Markdown renderer. Everything is escaped first. */
export function markdown(src) {
  const wrap = el('div', { class: 'md' });
  const lines = String(src || '').split('\n');
  let i = 0, html = '';
  // Text is collected as (escaped) HTML and added in one go before each code block.
  const flushTo = () => { if (html) { wrap.insertAdjacentHTML('beforeend', html); html = ''; } };

  // Read line by line: code fences, headings, lists, quotes, tables, then paragraphs.
  while (i < lines.length) {
    const line = lines[i];
    // ```code fences``` become a code block with a Copy button.
    const fence = line.match(/^```(\w*)/);
    if (fence) {
      const lang = fence[1];
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      flushTo();
      wrap.append(codeBlock(buf.join('\n'), lang));
      continue;
    }
    // # Headings (one level smaller than in the source, so they fit in a chat bubble).
    const head = line.match(/^(#{1,4})\s+(.*)$/);
    if (head) { html += `<h${head[1].length + 1}>${inline(head[2])}</h${head[1].length + 1}>`; i++; continue; }
    // Bulleted lists, numbered lists and > quotes: gather consecutive lines into one block.
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(inline(lines[i++].replace(/^\s*[-*]\s+/, '')));
      html += `<ul>${items.map((t) => `<li>${t}</li>`).join('')}</ul>`;
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) items.push(inline(lines[i++].replace(/^\s*\d+\.\s+/, '')));
      html += `<ol>${items.map((t) => `<li>${t}</li>`).join('')}</ol>`;
      continue;
    }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(inline(lines[i++].replace(/^>\s?/, '')));
      html += `<blockquote>${buf.join('<br>')}</blockquote>`;
      continue;
    }
    // Tables: a | row | followed by a | --- | separator row (AI answers often use them).
    if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1] || '')) {
      // Split a | a | b | row into its cells.
      const cells = (row) => row.trim().replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim()));
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      html += `<div class="tablewrap"><table><thead><tr>${head.map((c) => `<th>${c}</th>`).join('')}</tr></thead>`
        + `<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
      continue;
    }
    // Anything else: a paragraph of consecutive plain lines.
    if (!line.trim()) { i++; continue; }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*[-*]\s|\s*\d+\.\s|>|\s*\|)/.test(lines[i])) buf.push(inline(lines[i++]));
    html += `<p>${buf.join('<br>')}</p>`;
  }
  flushTo();
  return wrap;
}

// Code block with a copy button.
export function codeBlock(code, lang = '') {
  const box = el('div', { class: 'codeblock' });
  const pre = el('pre', {}, el('code', {}, code));
  if (lang) pre.dataset.lang = lang;
  const copy = el('button', { class: 'btn sm copy' }, icon('copy', 13), 'Copy');
  copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(code); toast('Copied to clipboard'); }
    catch { toast('Your browser blocked the clipboard. Select the code and copy it.', 'err'); }
  });
  box.append(pre, copy);
  return box;
}

// ------------------------------------------------------------------ format
// Up to two initials from a name, e.g. 'Kavin K' -> 'KK'.
export function initials(name) {
  return String(name || '?').split(/\s+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase();
}

// Coloured avatar with the user's initials.
export function avatar(name, accent, size = 'sm') {
  const node = el('span', { class: `avatar${size === 'lg' ? ' lg' : ''}` }, initials(name));
  node.style.background = accent || 'var(--accent)';
  return node;
}

// Clock time of a timestamp.
export function timeOf(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

// Date group label for messages (Today, Yesterday, ...).
export function dayBucket(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const days = Math.floor((new Date(now.getFullYear(), now.getMonth(), now.getDate()) -
    new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return 'Earlier this week';
  if (days < 30) return 'Earlier this month';
  return 'Older';
}

// Relative time such as '5 min ago'.
export function relative(ts) {
  const s = Math.max(1, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' });
}

// Loading placeholder rows.
export function skeleton(rows = 3) {
  const box = el('div', { style: 'padding:6px 2px' });
  for (let i = 0; i < rows; i++) {
    const line = el('div', { class: 'skel skel-line' });
    line.style.width = `${[92, 76, 84, 64][i % 4]}%`;
    box.append(line);
  }
  return box;
}

// Friendly message shown when a list is empty.
export function emptyState({ art = 'sparkle', title, text, actionLabel, onAction }) {
  const box = el('div', { class: 'empty' });
  const a = icon(art, 34, 1.3);
  a.className = 'art';
  a.style.color = 'var(--text-faint)';
  box.append(a, el('h4', {}, title), el('p', {}, text));
  if (actionLabel) box.append(el('button', { class: 'btn primary', onclick: onAction }, actionLabel));
  return box;
}

// Grow a textarea with its content, up to a limit.
export function autoGrow(textarea) {
  // Measure the content and set the height, up to 180 px.
  const fit = () => { textarea.style.height = 'auto'; textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`; };
  textarea.addEventListener('input', fit);
  fit();
}
