// Family dashboard: summary sentence + key figures, a 14-day "said vs seemed" chart, and a
// table of conversations. The chart is hand-drawn SVG (no chart library, works offline).

import { api, status, signed, el } from './common.js';

const $ = (id) => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
const LEVEL_LABEL = {
  ok: 'All OK', watch: 'Keep an eye on', alert: 'Check in with them', urgent: 'Urgent', none: 'No data yet',
};
const DOT_COLOR = { ok: 'var(--good)', low: 'var(--warning)', masked: 'var(--serious)', urgent: 'var(--critical)' };
let data = null;
let showTable = false;
const open = new Set();  // expanded conversation rows survive auto-refresh

function svg(tag, attrs = {}, parent) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.append(node);
  return node;
}
function dayLabel(iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, opts);
}
function dayStatus(d) {
  if (!d.checkins) return 'none';
  return d.safety_flag ? 'urgent' : d.status;
}
function lastCheckinText(days) {
  if (days === null || days === undefined) return '–';
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  return `${days} days ago`;
}

// ---------- summary ----------
function renderSummary(alert) {
  const level = $('level');
  level.textContent = '';
  level.append(status(alert.level, LEVEL_LABEL[alert.level]));
  $('message').textContent = alert.message;
  const updated = new Date().toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  $('meta').textContent = `Last ${alert.window_days} days · Updated ${updated}` +
    (data.has_demo_data ? ' · Includes demo data' : '');
  const none = alert.level === 'none';
  $('s-days').innerHTML = '';
  if (none) {
    $('s-days').textContent = '–';
  } else {
    $('s-days').append(document.createTextNode(String(alert.checkin_days)), el('small', '', ` / ${alert.window_days}`));
  }
  $('s-low').textContent = none ? '–' : String(alert.concern_days);
  $('s-masked').textContent = none ? '–' : String(alert.masked_days);
  $('s-last').textContent = lastCheckinText(alert.days_since_last_checkin);
}

// ---------- chart ----------
function renderChart() {
  const wrap = $('chart-wrap');
  const chart = $('chart');
  chart.textContent = '';
  const series = data.series;
  const W = Math.max(320, wrap.clientWidth);
  const H = 380;
  const m = { top: 10, right: 72, bottom: 60, left: 44 };
  chart.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const iw = W - m.left - m.right;
  const ih = H - m.top - m.bottom;
  const step = iw / series.length;
  const x = (i) => m.left + step * (i + 0.5);
  const y = (v) => m.top + ((1 - v) / 2) * ih;

  // masked-day bands (behind everything)
  series.forEach((d, i) => {
    if (d.checkins && d.status === 'masked') {
      svg('rect', { x: m.left + step * i, y: m.top, width: step, height: ih, fill: 'var(--band)' }, chart);
    }
  });
  // grid + y labels
  [1, 0.5, 0, -0.5, -1].forEach((v) => {
    svg('line', { x1: m.left, x2: m.left + iw, y1: y(v), y2: y(v),
      stroke: v === 0 ? 'var(--line-strong)' : 'var(--line)', 'stroke-width': 1 }, chart);
    const t = svg('text', { x: m.left - 10, y: y(v) + 4, 'text-anchor': 'end', class: 'axis-label' }, chart);
    t.textContent = v === 0 ? '0' : signed(v, v % 1 ? 1 : 0);
  });
  // "low" threshold
  const low = data.thresholds.low_nonverbal;
  svg('line', { x1: m.left, x2: m.left + iw, y1: y(low), y2: y(low), stroke: 'var(--ink-3)',
    'stroke-dasharray': '2 4', 'stroke-width': 1 }, chart);
  const lowLabel = svg('text', { x: m.left + 6, y: y(low) - 6, class: 'axis-label' }, chart);
  lowLabel.textContent = 'low threshold';

  // lines (broken on days without a conversation) + markers
  const lines = [['verbal_valence', '--series-said', 'Said'], ['nonverbal_valence', '--series-seemed', 'Seemed']];
  for (const [key, color, label] of lines) {
    let dPath = '';
    let pen = false;
    series.forEach((d, i) => {
      if (d[key] === null) { pen = false; return; }
      dPath += `${pen ? 'L' : 'M'}${x(i)},${y(d[key])} `;
      pen = true;
    });
    if (dPath) svg('path', { d: dPath, fill: 'none', stroke: `var(${color})`, 'stroke-width': 2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, chart);
    series.forEach((d, i) => {
      if (d[key] === null) return;
      svg('circle', { cx: x(i), cy: y(d[key]), r: 3.5, fill: `var(${color})`,
        stroke: 'var(--bg)', 'stroke-width': 2 }, chart);
    });
    const lastIdx = series.map((d) => d[key] !== null).lastIndexOf(true);
    if (lastIdx >= 0) {
      const t = svg('text', { x: x(lastIdx) + 10, y: y(series[lastIdx][key]) + 4, class: 'direct-label' }, chart);
      t.textContent = label;
    }
  }
  const labels = chart.querySelectorAll('.direct-label');
  if (labels.length === 2) {
    const [a, b] = labels;
    const ya = +a.getAttribute('y'), yb = +b.getAttribute('y');
    if (Math.abs(ya - yb) < 14) {
      const up = ya <= yb ? a : b, down = ya <= yb ? b : a;
      up.setAttribute('y', Math.min(ya, yb) - 7);
      down.setAttribute('y', Math.max(ya, yb) + 7);
    }
  }

  // one status dot per day + date labels
  series.forEach((d, i) => {
    const st = dayStatus(d);
    const cy = m.top + ih + 16;
    svg("circle", { cx: x(i), cy, r: 5, fill: DOT_COLOR[st] || 'none',
      stroke: st === 'none' ? 'var(--line-strong)' : 'none', 'stroke-width': 1 }, chart);
    if (i % 2 === (series.length - 1) % 2) {
      const t = svg('text', { x: x(i), y: H - 8, 'text-anchor': 'middle', class: 'axis-label' }, chart);
      t.textContent = dayLabel(d.date, { day: 'numeric', month: 'short' });
    }
  });

  // hover: crosshair + one tooltip listing both series
  const cross = svg('line', { y1: m.top, y2: m.top + ih, stroke: 'var(--line-strong)', 'stroke-width': 1,
    visibility: 'hidden' }, chart);
  const hit = svg('rect', { x: m.left, y: m.top, width: iw, height: ih + 28, fill: 'transparent' }, chart);
  const tip = $('tooltip');
  hit.addEventListener('pointermove', (evt) => {
    const rect = chart.getBoundingClientRect();
    const px = ((evt.clientX - rect.left) / rect.width) * W;
    const i = Math.max(0, Math.min(series.length - 1, Math.floor((px - m.left) / step)));
    const d = series[i];
    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i));
    cross.setAttribute('visibility', 'visible');
    tip.textContent = '';
    tip.append(el('div', 'label t-date', dayLabel(d.date)));
    if (!d.checkins) {
      tip.append(el('div', 'muted', 'No conversation'));
    } else {
      for (const [key, color, label] of lines) {
        const r = el('div', 't-row');
        const name = el('span', 't-name');
        const k = el('span', 't-key'); k.style.borderColor = `var(${color})`;
        name.append(k, document.createTextNode(label));
        r.append(name, el('b', '', signed(d[key])));
        tip.append(r);
      }
      tip.append(status(dayStatus(d)));
    }
    tip.classList.remove('hidden');
    const left = (x(i) / W) * rect.width;
    tip.style.left = `${Math.min(rect.width - tip.offsetWidth - 4, Math.max(4, left + 12))}px`;
    tip.style.top = '8px';
  });
  hit.addEventListener('pointerleave', () => { tip.classList.add('hidden'); cross.setAttribute('visibility', 'hidden'); });
}

function renderDotLegend() {
  const box = $('dot-legend');
  box.textContent = '';
  ['ok', 'low', 'masked'].forEach((k) => box.append(status(k)));
}

function renderTable() {
  const box = $('table-view');
  box.textContent = '';
  box.classList.toggle('hidden', !showTable);
  if (!showTable) return;
  const t = el('table', 'list');
  const head = el('tr');
  [['Day', ''], ['Check-ins', 'num'], ['Said', 'num'], ['Seemed', 'num'], ['Status', '']]
    .forEach(([h, c]) => head.append(el('th', c, h)));
  t.append(head);
  for (const d of [...data.series].reverse()) {
    const r = el('tr');
    r.append(el('td', 'date', dayLabel(d.date)), el('td', 'num', String(d.checkins)),
      el('td', 'num', signed(d.verbal_valence)), el('td', 'num', signed(d.nonverbal_valence)));
    const s = el('td'); s.append(status(dayStatus(d))); r.append(s);
    t.append(r);
  }
  box.append(t);
}

// ---------- conversations table ----------
function renderSessions(sessions) {
  const box = $('sessions');
  box.textContent = '';
  if (!sessions.length) {
    box.append(el('p', 'muted', 'No conversations yet. They appear here after the first chat on the Talk page.'));
    return;
  }
  const t = el('table', 'list');
  const head = el('tr');
  [['When', ''], ['Status', ''], ['Started with', 'hide-sm'], ['Said', 'num'], ['Seemed', 'num']]
    .forEach(([h, c]) => head.append(el('th', c, h)));
  t.append(head);
  for (const s of sessions) {
    const when = new Date(s.started_at).toLocaleString(undefined,
      { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    const row = el('tr', 'row');
    row.tabIndex = 0;
    row.setAttribute('aria-expanded', String(open.has(s.id)));
    const st = el('td'); st.append(status(s.safety_flag ? 'urgent' : s.status));
    const quote = el('td', 'quote hide-sm', s.turns[0] ? `“${s.turns[0].transcript}”` : '');
    if (s.is_demo) quote.append(el('span', 'demo-tag', 'demo'));
    row.append(el('td', 'date', when), st, quote,
      el('td', 'num', signed(s.verbal_valence)), el('td', 'num', signed(s.nonverbal_valence)));

    const detail = el('tr', 'detail');
    detail.classList.toggle('hidden', !open.has(s.id));
    const cell = el('td');
    cell.colSpan = 5;
    const convo = el('div', 'convo');
    for (const tr of s.turns) {
      const you = el('div');
      you.append(el('span', 'label who', data.elder_name), el('p', '', tr.transcript));
      const bits = [`said ${signed(tr.verbal_valence)}`, `seemed ${signed(tr.nonverbal_valence)}`];
      if (tr.voice) bits.push(`voice ${tr.voice}`);
      if (tr.face) bits.push(`face ${tr.face}`);
      if (tr.reassurance.length) bits.push(`“${tr.reassurance.join('”, “')}”`);
      you.append(el('div', 'meta', bits.join(' · ')));
      const them = el('div');
      them.append(el('span', 'label who', data.companion_name), el('p', 'muted', tr.reply_text));
      convo.append(you, them);
    }
    cell.append(convo);
    detail.append(cell);

    const toggle = () => {
      if (open.has(s.id)) open.delete(s.id); else open.add(s.id);
      detail.classList.toggle('hidden', !open.has(s.id));
      row.setAttribute('aria-expanded', String(open.has(s.id)));
    };
    row.addEventListener('click', toggle);
    row.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
    t.append(row, detail);
  }
  box.append(t);
}


// ---------- today's reminders ----------
const REMINDER_STATUS = { done: ['ok', 'Done'], due: ['low', 'Not confirmed'], soon: ['none', 'Soon'], later: ['none', 'Later'] };
function renderReminders(items) {
  const box = $('reminders');
  box.textContent = '';
  if (!items.length) {
    box.append(el('li', 'muted', 'No reminders today. Add medicines and routines on the setup page or below.'));
    return;
  }
  for (const r of items) {
    const li = el('li');
    const [dot, word] = REMINDER_STATUS[r.status] || ['none', r.status];
    const main = el('div', 'grow');
    main.append(el('div', '', r.title));
    const sub = r.status === 'done' && r.confirmed_by
      ? `${word.toLowerCase()} · ${r.confirmed_by === 'conversation' ? 'mentioned in conversation' : 'ticked here'}`
      : (r.notes || r.kind);
    main.append(el('div', 'sub-text', sub));
    li.append(el('span', 'time', r.time || 'Any'), main, status(dot, word));
    if (r.status !== 'done') {
      const done = el('button', 'link-button', 'Mark done');
      done.type = 'button';
      done.addEventListener('click', async () => { await api(`/api/reminders/${r.id}/done`, { method: 'POST' }); load(); });
      li.append(done);
    }
    if (r.source === 'family') {
      const del = el('button', 'link-button', 'Remove');
      del.type = 'button';
      del.addEventListener('click', async () => { await api(`/api/reminders/${r.id}`, { method: 'DELETE' }); load(); });
      li.append(del);
    }
    box.append(li);
  }
}

// ---------- wellbeing signals mentioned in conversation ----------
function renderWellbeing(w) {
  const box = $('wellbeing');
  box.textContent = '';
  $('wellbeing-sub').textContent = w.days_with_signals
    ? `Days in the last ${w.days} when it came up (from ${w.days_with_signals} day${w.days_with_signals === 1 ? '' : 's'} of conversations).`
    : `Nothing yet. Picked up from conversations.`;
  const rows = [['sleep', 'Slept poorly'], ['appetite', 'Poor appetite'], ['pain', 'Pain mentioned'],
    ['loneliness', 'Felt lonely'], ['social_contact', 'No contact with anyone']];
  for (const [key, label] of rows) {
    const n = w.counts[key];
    const row = el('div', 'kv');
    const name = el('dt'); name.append(status(n >= 3 ? 'low' : n > 0 ? 'none' : 'ok', label));
    row.append(name, el('dd', '', w.days_with_signals ? `${n} day${n === 1 ? '' : 's'}` : '–'));
    box.append(row);
  }
}

// ---------- personal baseline note ----------
function renderBaselineNote(b) {
  const note = $('baseline-note');
  const today = data.series[data.series.length - 1];
  const readings = today && today.readings
    ? ` Today: ${today.readings} spoken ${today.readings === 1 ? 'answer' : 'answers'} read (more answers make the day more reliable).`
    : '';
  if (!b.enabled) {
    note.textContent = `Low line: fixed at ${signed(b.low_threshold)} (personal baseline switched off).${readings}`;
  } else if (b.mode === 'channels') {
    const parts = [['voice', 'voice'], ['face', 'face']]
      .filter(([c]) => b.channels[c].ready)
      .map(([c, label]) => `${label} ${signed(b.channels[c].normal)}`);
    note.textContent = `“Seemed low” is judged against ${data.elder_name}'s own normal (${parts.join(', ')}): ` +
      `a drop of ${(-b.low_threshold).toFixed(2)} or more.${readings}`;
  } else if (b.ready) {
    note.textContent = `Low line is personal: ${data.elder_name}'s normal is ${signed(b.normal)} (spread ${b.spread.toFixed(2)}), so “low” means ${signed(b.low_threshold)} or below.${readings}`;
  } else {
    note.textContent = `Learning ${data.elder_name}'s normal: ${b.sessions} of ${b.needed} conversations so far. ` +
      `Until then only clearly low readings count (below ${signed(b.low_threshold)}).${readings}`;
  }
}

// ---------- companion model status ----------
function renderLlmNote(s) {
  const note = $('llm-note');
  if (!s || !s.degraded) { note.classList.add('hidden'); return; }
  note.classList.remove('hidden');
  note.textContent = s.unavailable
    ? `${data.companion_name} can't reach its language model right now (usage limit reached). Replies will say so until it's back.`
    : `${data.companion_name} is using a backup language model (usage limit on the usual one). Replies may feel a little different.`;
}

// ---------- memories ----------
function renderMemories(memories) {
  $('learned-title').textContent = `What ${data.companion_name} has learned`;
  const box = $('memories');
  box.textContent = '';
  if (!memories.length) {
    box.append(el('li', 'muted', 'Nothing yet. New things the person mentions (people, plans, events) appear here as you chat.'));
    return;
  }
  for (const m of memories) {
    const li = el('li');
    const when = new Date(m.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
    const main = el('div', 'grow');
    main.append(el('div', '', m.text));
    main.append(el('div', 'sub-text', [m.kind, m.event_date ? `on ${dayLabel(m.event_date)}` : '', m.is_demo ? 'demo' : '']
      .filter(Boolean).join(' · ')));
    const forget = el('button', 'link-button', 'Remove');
    forget.type = 'button';
    forget.addEventListener('click', async () => { await api(`/api/memories/${m.id}`, { method: 'DELETE' }); load(); });
    li.append(el('span', 'time', when), main, forget);
    box.append(li);
  }
}

$('add-reminder').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const days = f.get('days') === 'once' ? `once:${data.today}` : f.get('days');
  await api('/api/reminders', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: f.get('title'), time: f.get('time') || null, days, kind: 'task' }),
  });
  e.target.reset();
  load();
});

async function load() {
  try {
    if (data) $('dash').style.opacity = '0.6';
    data = await api('/api/dashboard?days=14');
  } catch (err) {
    $('message').textContent = `Couldn’t reach the server (${err.message}).`;
    return;
  } finally {
    $('dash').style.opacity = '1';
  }
  document.title = `${data.elder_name} · I'm Fine`;
  renderSummary(data.alert);
  renderChart();
  renderDotLegend();
  renderTable();
  renderSessions(data.recent_sessions);
  renderReminders(data.reminders);
  renderWellbeing(data.wellbeing);
  renderBaselineNote(data.baseline);
  renderLlmNote(data.llm);
  renderMemories(data.memories);
}

$('table-toggle').addEventListener('click', () => {
  showTable = !showTable;
  $('table-toggle').textContent = showTable ? 'Hide table' : 'Show as table';
  if (data) renderTable();
});
window.addEventListener('resize', () => { if (data) renderChart(); });
load();
setInterval(load, 15000);
