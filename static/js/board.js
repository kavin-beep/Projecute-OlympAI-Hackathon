// Group workspace: Brief, Tasks, Decisions, Alerts, Activity, Team outputs.

import { api, on, state } from './api.js';
import { $, clear, codeBlock, el, emptyState, icon, markdown, modal, relative, skeleton, timeOf, toast } from './ui.js';

const SECTIONS = [
  ['brief', 'Brief', 'doc'],
  ['tickets', 'Tasks', 'board'],
  ['decisions', 'Decisions', 'check'],
  ['alerts', 'Alerts', 'alert'],
  ['activity', 'Activity', 'clock'],
  ['outputs', 'Team outputs', 'share'],
];

let section = 'brief';
let gotoChannelMessage = null;   // set by app.js

// Let app.js provide a function that jumps to a chat message.
export function setMessageJumper(fn) { gotoChannelMessage = fn; }

// Load the group workspace and render the current section.
export async function loadBoard() {
  if (!state.group) return;
  const body = clear($('#boardBody'));
  body.append(skeleton(5));
  state.workspace = await api(`/groups/${state.group.group.id}/workspace`);
  renderNav();
  renderSection();
}

// Draw the six workspace sections with their count badges.
function renderNav() {
  const nav = clear($('#boardNav'));
  nav.append(el('div', { class: 'sectionlabel' }, 'Shared with the team'));
  for (const [key, label, ic] of SECTIONS) {
    const count = state.workspace.counts[key] ?? 0;
    const row = el('button', { class: `listitem${section === key ? ' active' : ''}` },
      icon(ic, 15), el('span', { class: 'label' }, label),
      el('span', { class: `count${key === 'alerts' && count ? ' alarm' : ''}` }, String(count)));
    row.addEventListener('click', () => { section = key; renderNav(); renderSection(); });
    nav.append(row);
  }
}

// Section heading with a subtitle and an optional action button.
function heading(title, sub, action) {
  const box = el('div', {});
  box.append(el('div', { class: 'board-title' }, el('h1', {}, title), el('span', { style: 'flex:1' }), action || null));
  box.append(el('div', { class: 'board-sub' }, sub));
  return box;
}

// Render whichever workspace section is selected.
function renderSection() {
  const body = clear($('#boardBody'));
  ({ brief: renderBrief, tickets: renderTickets, decisions: renderDecisions,
     alerts: renderAlerts, activity: renderActivity, outputs: renderOutputs })[section](body);
}

// ---------------------------------------------------------------- brief
function renderBrief(body) {
  const w = state.workspace;
  const isHost = state.group.is_host;
  const approved = w.brief?.status === 'approved';

  const action = el('div', { class: 'row-between' });
  if (w.brief && !approved && isHost) {
    const approve = el('button', { class: 'btn primary' }, icon('check', 15), 'Approve brief');
    approve.addEventListener('click', async () => {
      try {
        await api(`/groups/${state.group.group.id}/brief/approve`, { method: 'POST' });
        toast('Brief approved. Tasks can be generated now.');
      } catch (err) { toast(err.message, 'err'); }
    });
    action.append(approve);
  }
  body.append(heading('Project brief',
    w.brief ? (approved ? `Approved by ${w.brief.approved_by ? 'the host' : ''}. Everyone works from this.`
                        : 'Draft — the team can edit it, then the host approves.')
            : 'One agreed starting point, written from your group chat.',
    action));

  if (!w.brief) {
    body.append(emptyState({
      art: 'doc', title: 'No brief yet',
      text: 'The PM agent reads your project channel and writes a first draft you can edit.',
      actionLabel: 'Write the brief from our chat',
      onAction: extractBrief,
    }));
    return;
  }

  const card = el('div', { class: 'card' });
  card.append(el('div', { class: 'cardhead' },
    el('span', { class: approved ? 'sev ok' : 'sev low' }, icon(approved ? 'check' : 'pencil', 12), approved ? 'Approved' : 'Draft'),
    el('span', { class: 'spacer', style: 'flex:1' }),
    el('span', { class: 'meta' }, `Updated ${relative(w.brief.updated_at)}`)));
  card.append(markdown(w.brief.content));

  const row = el('div', { class: 'row-between', style: 'margin-top:14px' });
  const edit = el('button', { class: 'btn sm' }, icon('pencil', 13), 'Edit brief');
  edit.addEventListener('click', () => editBrief(w.brief));
  const redo = el('button', { class: 'btn sm ghost' }, icon('sparkle', 13), 'Rewrite from chat');
  redo.addEventListener('click', extractBrief);
  row.append(edit, redo);
  card.append(row);
  body.append(card);

  if (approved) {
    const next = el('div', { class: 'card' });
    next.append(el('h4', {}, 'Next step'),
      el('p', { class: 'meta' }, 'Turn the approved brief into tasks with owners, priorities and estimates.'));
    const go = el('button', { class: 'btn primary' }, icon('sparkle', 15), 'Generate tasks');
    go.addEventListener('click', async () => {
      go.disabled = true;
      try {
        const { tickets } = await api(`/groups/${state.group.group.id}/tickets/propose`, { method: 'POST' });
        toast(tickets.length ? `${tickets.length} tasks proposed` : 'No new tasks to add');
        section = 'tickets';
      } catch (err) { toast(err.message, 'err'); } finally { go.disabled = false; }
    });
    next.append(go);
    body.append(next);
  }

  body.append(futuresBlock());
}

// Ask the PM agent to draft the brief from the group chat.
async function extractBrief() {
  toast('Reading the group chat…');
  try { await api(`/groups/${state.group.group.id}/brief/extract`, { method: 'POST' }); }
  catch (err) { toast(err.message, 'err'); }
}

// Open the brief editor; saving sends it back to draft.
function editBrief(brief) {
  const area = el('textarea', { class: 'field', style: 'min-height:300px' });
  area.value = brief.content;
  modal({
    title: 'Edit the brief',
    body: el('div', {},
      el('p', { class: 'meta' }, 'Editing puts the brief back to draft, so the host approves the final wording.'),
      area),
    confirmLabel: 'Save brief',
    onConfirm: async () => {
      await api(`/groups/${state.group.group.id}/brief`, { method: 'PATCH', body: { content: area.value } });
      toast('Brief saved as a draft');
    },
  });
}

// ---------------------------------------------------------------- futures
function futuresBlock() {
  const w = state.workspace;
  const card = el('div', { class: 'card' });
  card.append(el('div', { class: 'cardhead' }, icon('group', 15), el('h4', {}, 'Does the team actually agree?')));
  card.append(el('p', { class: 'meta' },
    'Everyone answers the same concrete scenario on their own. Comparing the answers shows what people quietly assumed.'));

  if (!w.futures.length) {
    const add = el('button', { class: 'btn sm' }, icon('plus', 13), 'Ask a scenario');
    add.addEventListener('click', newFutureDialog);
    card.append(add);
    return card;
  }
  for (const f of w.futures) {
    const box = el('div', { style: 'margin-top:14px;padding-top:14px;border-top:1px solid var(--line-soft)' });
    box.append(el('p', { style: 'font-weight:500' }, f.scenario));
    const mine = f.answers.find((a) => a.user_id === state.me.id);
    box.append(el('div', { class: 'meta' }, `${f.answers.length} of ${state.group.members.length} answered`));

    if (!mine) {
      const ans = el('button', { class: 'btn sm primary', style: 'margin-top:10px' }, 'Write my answer');
      ans.addEventListener('click', () => answerFutureDialog(f));
      box.append(ans);
    } else if (f.comparison) {
      const c = f.comparison;
      box.append(el('div', { class: 'card flat', style: 'margin-top:10px;padding:0' },
        el('p', { style: 'margin-top:10px' }, c.summary),
        c.hidden_assumptions.length
          ? el('div', {}, el('div', { class: 'meta', style: 'margin-bottom:4px' }, 'Hidden assumptions'),
              el('ul', { style: 'margin:0 0 10px;padding-left:20px' }, ...c.hidden_assumptions.map((h) => el('li', {}, h))))
          : null,
        c.agreements.length
          ? el('div', {}, el('div', { class: 'meta', style: 'margin-bottom:4px' }, 'Agreed'),
              el('ul', { style: 'margin:0;padding-left:20px' }, ...c.agreements.map((h) => el('li', {}, h))))
          : null));
      box.append(answersList(f));
    } else {
      box.append(answersList(f));
      const cmp = el('button', { class: 'btn sm', style: 'margin-top:10px' }, icon('sparkle', 13), 'Compare answers');
      cmp.disabled = f.answers.length < 2;
      cmp.addEventListener('click', async () => {
        cmp.disabled = true;
        try { await api(`/groups/${state.group.group.id}/futures/${f.id}/compare`, { method: 'POST' }); }
        catch (err) { toast(err.message, 'err'); cmp.disabled = false; }
      });
      box.append(cmp);
      if (f.answers.length < 2) box.append(el('div', { class: 'meta', style: 'margin-top:6px' }, 'Two answers are needed before comparing.'));
    }
    card.append(box);
  }
  return card;
}

// List each member's answer to a scenario.
function answersList(f) {
  const list = el('div', { style: 'margin-top:10px' });
  for (const a of f.answers) {
    list.append(el('div', { class: 'quote' },
      el('div', { class: 'qhead' }, a.author, el('span', {}, relative(a.created_at))),
      el('div', { class: 'qtext' }, a.answer)));
  }
  return list;
}

// Dialog to start a Parallel Futures scenario.
function newFutureDialog() {
  const area = el('textarea', { class: 'field', style: 'min-height:90px' });
  area.value = 'A shopper with items in their cart opens checkout for the first time. Describe exactly what they see and what they have to do before they can pay.';
  modal({
    title: 'Ask everyone the same scenario',
    body: el('div', { class: 'row' }, el('label', {}, 'Scenario'), area),
    confirmLabel: 'Ask the team',
    onConfirm: async () => {
      if (!area.value.trim()) return false;
      await api(`/groups/${state.group.group.id}/futures`, { method: 'POST', body: { scenario: area.value.trim() } });
      toast('Scenario sent to the team');
    },
  });
}

// Dialog to answer a scenario independently.
function answerFutureDialog(f) {
  const area = el('textarea', { class: 'field', style: 'min-height:110px', placeholder: 'Answer in your own words. You cannot see other answers until you submit.' });
  modal({
    title: 'Your answer',
    body: el('div', {}, el('p', { class: 'meta' }, f.scenario), area),
    confirmLabel: 'Submit answer',
    onConfirm: async () => {
      if (!area.value.trim()) return false;
      await api(`/groups/${state.group.group.id}/futures/${f.id}/answer`, { method: 'POST', body: { answer: area.value.trim() } });
      toast('Answer submitted');
    },
  });
}

// ---------------------------------------------------------------- tasks
function renderTickets(body) {
  const w = state.workspace;
  const proposed = w.tickets.filter((t) => t.status === 'proposed');
  const action = el('div', { class: 'row-between' });
  if (proposed.length && state.group.is_host) {
    const ok = el('button', { class: 'btn primary' }, icon('check', 15), `Approve ${proposed.length} assignment${proposed.length > 1 ? 's' : ''}`);
    ok.addEventListener('click', async () => {
      try { await api(`/groups/${state.group.group.id}/tickets/approve`, { method: 'POST' }); toast('Assignments approved'); }
      catch (err) { toast(err.message, 'err'); }
    });
    action.append(ok);
  }
  const confirmed = w.tickets.filter((t) => t.hours_confirmed).reduce((s, t) => s + t.estimated_hours, 0);
  body.append(heading('Tasks',
    w.tickets.length
      ? `${w.tickets.length} tasks, ${confirmed ? `about ${round(confirmed)} hours confirmed by the team` : 'no estimates confirmed yet'}.`
      : 'Tasks come from the approved brief, with an owner, a priority and an estimate.',
    action));

  if (!w.tickets.length) {
    body.append(emptyState({
      art: 'board', title: 'No tasks yet',
      text: 'Approve the brief first, then the PM agent proposes tasks from what the team agreed.',
      actionLabel: 'Go to the brief',
      onAction: () => { section = 'brief'; renderNav(); renderSection(); },
    }));
    return;
  }
  for (const t of w.tickets) body.append(ticketRow(t));
}

// Round to one decimal place.
function round(n) { return Math.round(n * 10) / 10; }

// One clickable row in the task list.
function ticketRow(t) {
  const row = el('div', { class: 'ticketrow' },
    el('span', { class: 'key' }, t.key),
    el('span', { class: 'title truncate' }, t.title),
    el('span', { class: `pri ${t.priority}` }, t.priority),
    el('span', { class: `hours${t.hours_confirmed ? ' confirmed' : ''}`, title: t.hours_confirmed ? 'Estimate confirmed by the team' : 'Estimate not confirmed yet' },
      `${round(t.estimated_hours)} h${t.hours_confirmed ? ' ✓' : ''}`),
    el('span', { class: 'owner meta truncate' }, t.owner_name || 'Unassigned'));
  row.addEventListener('click', () => openTicket(t));
  return row;
}

// Open a task in the side panel: details, criteria, hours and Human Unit Test.
export function openTicket(t) {
  const box = el('div', {});
  box.append(el('div', { class: 'row-between', style: 'margin-bottom:10px' },
    el('span', { class: 'chip' }, t.key),
    el('span', { class: `pri ${t.priority}` }, t.priority),
    el('span', { class: 'spacer' }),
    el('span', { class: 'meta' }, t.status === 'proposed' ? 'Waiting for host approval' : 'Approved')));
  box.append(el('h3', { style: 'margin-bottom:8px' }, t.title));
  if (t.detail) box.append(el('p', { class: 'meta' }, t.detail));

  box.append(el('div', { class: 'impact' },
    el('span', { class: 'big' }, `${round(t.estimated_hours)} hours`),
    el('span', { class: 'meta' }, t.hours_confirmed ? 'Estimate confirmed by the team' : 'Estimate not confirmed yet'),
    el('span', { class: 'spacer', style: 'flex:1' }),
    el('span', { class: 'meta' }, t.owner_name || 'Unassigned')));

  if (!t.hours_confirmed) {
    const c = el('button', { class: 'btn wide', style: 'margin-bottom:10px' }, icon('check', 14), 'Confirm this estimate');
    c.addEventListener('click', async () => {
      await api(`/groups/${state.group.group.id}/tickets/${t.id}/confirm-hours`, { method: 'POST' });
      toast('Estimate confirmed');
    });
    box.append(c);
  }

  if (t.acceptance_criteria?.length) {
    const card = el('div', { class: 'card' });
    card.append(el('div', { class: 'cardhead' }, icon('check', 15), el('h4', {}, 'Done means')));
    card.append(el('ul', { style: 'margin:0;padding-left:20px' }, ...t.acceptance_criteria.map((c) => el('li', {}, c))));
    box.append(card);
  }

  box.append(unitTestBlock(t));

  if (state.group.is_host) {
    const edit = el('button', { class: 'btn wide', style: 'margin-top:10px' }, icon('pencil', 14), 'Change owner, priority or estimate');
    edit.addEventListener('click', () => editTicketDialog(t));
    box.append(edit);
  }
  openSide(`Task ${t.key}`, box);
}

// Human Unit Test panel for a task.
function unitTestBlock(t) {
  const ut = state.workspace.unit_tests.find((u) => u.ticket_id === t.id);
  const card = el('div', { class: 'card' });
  card.append(el('div', { class: 'cardhead' }, icon('group', 15), el('h4', {}, 'Before work starts')));
  card.append(el('p', { class: 'meta' },
    'The person who wrote the task and the person doing it each describe it. If the two descriptions do not line up, it shows here.'));

  const mineIsAssignee = t.owner_user_id === state.me.id;
  const myField = mineIsAssignee ? 'assignee_desc' : 'creator_desc';
  const mineDone = ut && ut[myField];

  if (ut?.verdict) {
    const bad = ut.verdict === 'mismatch';
    card.append(el('div', { class: `sev ${bad ? 'high' : 'ok'}`, style: 'margin-bottom:8px' },
      icon(bad ? 'alert' : 'check', 12), bad ? 'The two descriptions do not match' : 'Both descriptions match'));
    card.append(el('p', {}, ut.comparison?.summary || ''));
    if (ut.comparison?.differences?.length) {
      card.append(el('ul', { style: 'margin:0;padding-left:20px' }, ...ut.comparison.differences.map((d) => el('li', {}, d))));
    }
    card.append(el('div', { class: 'divider' }));
    card.append(el('div', { class: 'quote' },
      el('div', { class: 'qhead' }, ut.creator_name || 'Task author'),
      el('div', { class: 'qtext' }, ut.creator_desc)));
    card.append(el('div', { class: 'quote', style: 'margin-top:8px' },
      el('div', { class: 'qhead' }, ut.assignee_name || 'Assignee'),
      el('div', { class: 'qtext' }, ut.assignee_desc)));
    return card;
  }

  if (mineDone) {
    card.append(el('div', { class: 'meta' }, 'Your description is in. Waiting for the other person.'));
    return card;
  }
  const go = el('button', { class: 'btn sm primary' }, 'Describe this task in my words');
  go.addEventListener('click', () => {
    const area = el('textarea', { class: 'field', style: 'min-height:110px', placeholder: 'What will be built, and what it does when it is done.' });
    modal({
      title: 'Describe this task',
      body: el('div', {}, el('p', { class: 'meta' }, t.title), area),
      confirmLabel: 'Submit description',
      onConfirm: async () => {
        if (!area.value.trim()) return false;
        await api(`/groups/${state.group.group.id}/tickets/${t.id}/unit-test`, { method: 'POST', body: { description: area.value.trim() } });
        toast('Description submitted');
      },
    });
  });
  card.append(go);
  return card;
}

// Host-only dialog to edit a task.
function editTicketDialog(t) {
  const owner = el('select', { class: 'field' });
  owner.append(el('option', { value: '' }, 'Unassigned'));
  for (const m of state.group.members) owner.append(el('option', { value: m.id }, m.display_name));
  owner.value = t.owner_user_id || '';
  const pri = el('select', { class: 'field' });
  for (const p of ['Low', 'Medium', 'High']) pri.append(el('option', { value: p }, p));
  pri.value = t.priority;
  const hours = el('input', { class: 'field', type: 'number', min: '0.5', step: '0.5', value: String(t.estimated_hours) });
  modal({
    title: `Change ${t.key}`,
    body: el('div', {},
      el('div', { class: 'row' }, el('label', {}, 'Owner'), owner),
      el('div', { class: 'row' }, el('label', {}, 'Priority'), pri),
      el('div', { class: 'row' }, el('label', {}, 'Estimated hours — changing this clears the team confirmation'), hours)),
    confirmLabel: 'Save changes',
    onConfirm: async () => {
      const body = { owner_user_id: owner.value || null, priority: pri.value };
      if (Number(hours.value) !== t.estimated_hours) body.estimated_hours = Number(hours.value);
      await api(`/groups/${state.group.group.id}/tickets/${t.id}`, { method: 'PATCH', body });
      toast('Task updated');
    },
  });
}

// ---------------------------------------------------------------- alerts
function renderAlerts(body) {
  const w = state.workspace;
  const open = w.alerts.filter((a) => a.status === 'open');
  body.append(heading('Alerts',
    open.length ? `${open.length} open. Each one shows the messages behind it and the work it affects.`
                : 'Nothing open. New messages are checked against what the team already agreed.'));
  if (!w.alerts.length) {
    body.append(emptyState({
      art: 'alert', title: 'Nothing flagged',
      text: 'Once the brief is approved, every new message in the project channel is checked against earlier ones.',
      actionLabel: 'Check the chat again',
      onAction: async () => {
        toast('Checking the group chat…');
        try { const { alerts } = await api(`/groups/${state.group.group.id}/alerts/scan`, { method: 'POST' });
          toast(alerts.length ? `${alerts.length} flagged` : 'Nothing to flag'); }
        catch (err) { toast(err.message, 'err'); }
      },
    }));
    return;
  }
  for (const a of w.alerts) body.append(alertCard(a));
}

const KIND_TEXT = {
  duplicate: 'Looks like the same task',
  contradiction: 'These two messages disagree',
  assumption: 'People assumed different things',
  unclear: 'Needs a person to look',
};

// One alert: source messages, affected tasks, impact and resolution options.
export function alertCard(a, compact = false) {
  const card = el('div', { class: `alert ${a.severity}${a.status === 'resolved' ? ' resolved' : ''}` });
  card.append(el('div', { class: 'strip' }));
  const body = el('div', { class: 'alertbody' });

  body.append(el('div', { class: 'kindrow' },
    el('span', { class: `sev ${a.status === 'resolved' ? 'ok' : a.severity}` },
      icon(a.status === 'resolved' ? 'check' : 'alert', 12),
      a.status === 'resolved' ? 'Resolved' : KIND_TEXT[a.kind] || 'Flagged'),
    el('span', { class: 'spacer', style: 'flex:1' }),
    el('span', { class: 'meta' }, relative(a.created_at))));

  body.append(el('h3', {}, a.headline));
  if (a.explanation) body.append(el('div', { class: 'explain' }, a.explanation));

  if (a.sources.length) {
    const ev = el('div', { class: 'evidence' });
    for (const s of a.sources) {
      const q = el('div', { class: 'quote' },
        el('div', { class: 'qhead' }, s.author || 'Someone', el('span', {}, timeOf(s.created_at)), icon('reply', 11)),
        el('div', { class: 'qtext' }, s.content));
      q.title = 'Open this message in the group chat';
      q.addEventListener('click', () => gotoChannelMessage && gotoChannelMessage(s.id));
      ev.append(q);
    }
    body.append(ev);
  }

  const impact = el('div', { class: 'impact' }, el('span', { class: 'big' }, a.impact_label));
  if (a.tickets.length) {
    const chips = el('span', { class: 'chips' });
    for (const t of a.tickets) {
      const chip = el('button', { class: 'chip' }, t.key);
      chip.title = t.title;
      chip.addEventListener('click', () => openTicket(t));
      chips.append(chip);
    }
    impact.append(chips);
  }
  body.append(impact);

  if (a.status === 'resolved') {
    body.append(el('div', { class: 'card flat', style: 'padding:0' },
      el('div', { class: 'meta' }, `Decided by ${a.resolved_by_name || 'the host'}`),
      el('p', { style: 'margin:4px 0 0' }, a.resolution)));
  } else if (state.group.is_host) {
    let picked = null;
    const opts = el('div', { class: 'options' });
    const custom = el('textarea', { class: 'field hidden', style: 'min-height:80px', placeholder: 'Write what the team decided.' });
    const choices = [...a.options, 'Something else'];
    for (const text of choices) {
      const opt = el('button', { class: 'option' }, el('span', { class: 'radio' }), el('span', {}, text));
      opt.addEventListener('click', () => {
        picked = text;
        [...opts.children].forEach((c) => c.classList.toggle('picked', c === opt));
        custom.classList.toggle('hidden', text !== 'Something else');
        if (text === 'Something else') custom.focus();
      });
      opts.append(opt);
    }
    body.append(opts, custom);
    const approve = el('button', { class: 'btn primary', style: 'margin-top:12px' }, icon('check', 15), 'Approve this resolution');
    approve.addEventListener('click', async () => {
      const resolution = picked === 'Something else' ? custom.value.trim() : picked;
      if (!resolution) return toast('Pick what the team decided first.', 'err');
      approve.disabled = true;
      try {
        await api(`/groups/${state.group.group.id}/alerts/${a.id}/resolve`, { method: 'POST', body: { resolution } });
        toast('Resolution approved. Everyone\'s dashboard is updated.');
      } catch (err) { toast(err.message, 'err'); approve.disabled = false; }
    });
    body.append(approve);
  } else {
    body.append(el('div', { class: 'meta' }, 'Waiting for the host to approve a resolution.'));
  }
  card.append(body);
  return card;
}

// ---------------------------------------------------------------- decisions
function renderDecisions(body) {
  const w = state.workspace;
  body.append(heading('Decisions', 'What the team settled, and what it came from.'));
  if (!w.decisions.length) {
    body.append(emptyState({
      art: 'check', title: 'No decisions yet',
      text: 'When the host approves a resolution on an alert, it is recorded here with its source.',
      actionLabel: 'See open alerts',
      onAction: () => { section = 'alerts'; renderNav(); renderSection(); },
    }));
    return;
  }
  for (const d of w.decisions) {
    const card = el('div', { class: 'card' });
    card.append(el('div', { class: 'cardhead' }, icon('check', 15), el('h4', {}, d.title),
      el('span', { class: 'meta' }, relative(d.created_at))));
    card.append(el('p', {}, d.content));
    const foot = el('div', { class: 'row-between' }, el('span', { class: 'meta' }, `Approved by ${d.decided_by_name}`));
    if (d.alert_id) {
      const link = el('button', { class: 'btn sm ghost' }, 'See the messages behind it');
      link.addEventListener('click', async () => {
        const { alert } = await api(`/groups/${state.group.group.id}/alerts/${d.alert_id}`);
        openSide('Alert', alertCard(alert));
      });
      foot.append(el('span', { class: 'spacer', style: 'flex:1' }), link);
    }
    card.append(foot);
    body.append(card);
  }
}

// ---------------------------------------------------------------- activity
function renderActivity(body) {
  const w = state.workspace;
  body.append(heading('Activity', 'What each agent and person did, newest first.'));
  if (!w.activity.length) {
    body.append(emptyState({ art: 'clock', title: 'Nothing has happened yet', text: 'Agent and host actions are logged here as they happen.' }));
    return;
  }
  const line = el('div', { class: 'timeline' });
  for (const a of w.activity) {
    const row = el('div', { class: `tl${a.actor_kind === 'agent' ? ' agent' : ''}` });
    row.append(el('div', { class: 'when' }, `${relative(a.created_at)} · ${timeOf(a.created_at)}`));
    row.append(el('div', { class: 'what' }, el('span', { class: 'actor' }, a.actor), ' ', a.action.toLowerCase()));
    if (a.detail) row.append(el('div', { class: 'meta' }, a.detail));
    if (a.ref_kind === 'alert' && a.ref_id) {
      const link = el('button', { class: 'btn sm ghost' }, 'Open alert');
      link.addEventListener('click', async () => {
        try {
          const { alert } = await api(`/groups/${state.group.group.id}/alerts/${a.ref_id}`);
          openSide('Alert', alertCard(alert));
        } catch (err) { toast(err.message, 'err'); }
      });
      row.append(link);
    }
    if (a.ref_kind === 'ticket' && a.ref_id) {
      const t = state.workspace.tickets.find((x) => x.id === a.ref_id);
      if (t) {
        const link = el('button', { class: 'btn sm ghost' }, `Open ${t.key}`);
        link.addEventListener('click', () => openTicket(t));
        row.append(link);
      }
    }
    line.append(row);
  }
  body.append(line);
}

// ---------------------------------------------------------------- outputs
function renderOutputs(body) {
  const w = state.workspace;
  body.append(heading('Team outputs', 'Items people chose to share from their own workspace.'));
  if (!w.outputs.length) {
    body.append(emptyState({
      art: 'share', title: 'Nothing shared yet',
      text: 'Items in a personal workspace stay private until someone shares them here.',
      actionLabel: 'Open my workspace',
      onAction: () => document.querySelector('#rail button[data-view="work"]').click(),
    }));
    return;
  }
  for (const o of w.outputs) {
    const card = el('div', { class: 'card itemcard' });
    card.append(el('div', { class: 'cardhead' },
      el('span', { class: 'kindtag' }, o.kind), el('h4', {}, o.name),
      el('span', { class: 'meta' }, o.owner_name)));
    card.append(el('div', { class: 'meta truncate' }, o.kind === 'image' ? 'Image' : o.body.slice(0, 120)));
    card.addEventListener('click', () => openSharedItem(o));
    body.append(card);
  }
}

// Open a shared item in the side panel.
function openSharedItem(o) {
  const box = el('div', {});
  box.append(el('div', { class: 'meta', style: 'margin-bottom:10px' }, `Shared by ${o.owner_name} · ${relative(o.created_at)}`));
  if (o.kind === 'image') box.append(el('img', { class: 'gen', src: o.data_url, alt: o.name }));
  else if (o.kind === 'code') box.append(codeBlock(o.body, o.language || ''));
  else box.append(markdown(o.body));
  openSide(o.name, box);
}

// ---------------------------------------------------------------- live
function openSide(title, node) {
  $('#spTitle').textContent = title;
  clear($('#spBody')).append(node);
  $('#sidePanel').classList.add('open');
}

// Apply live workspace updates pushed over the WebSocket.
export function initBoardLive() {
  const refresh = async () => {
    if (!state.group) return;
    state.workspace = await api(`/groups/${state.group.group.id}/workspace`);
    renderNav();
    renderSection();
  };
  for (const ev of ['brief', 'tickets', 'alert', 'alerts', 'decisions', 'activity', 'outputs', 'futures', 'unit_tests']) {
    on(`ws:${ev}`, async ({ group_id }) => {
      if (!state.group || group_id !== state.group.group.id) return;
      await refresh();
      if ($('#sidePanel').classList.contains('open')) { /* keep panel content as is */ }
    });
  }
  on('ws:alert', ({ group_id, data }) => {
    if (!state.group || group_id !== state.group.group.id) return;
    if (data.status === 'open') toast(`Alert: ${data.headline}`, 'err');
  });
}

// Jump to a workspace section.
export function showSection(name) { section = name; renderNav(); renderSection(); }
