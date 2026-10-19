// Setup page: loads the profile, edits it, saves it with PUT /api/profile.
import { api, el } from './common.js';

const $ = (id) => document.getElementById(id);
const form = $('form');
const KINDS = [['medication', 'Medicine'], ['task', 'Routine'], ['appointment', 'Appointment'], ['call', 'Call'], ['other', 'Other']];
const DAYS = [['daily', 'Every day'], ['mon,tue,wed,thu,fri', 'Weekdays'], ['sat,sun', 'Weekends'],
  ['mon', 'Mondays'], ['tue', 'Tuesdays'], ['wed', 'Wednesdays'], ['thu', 'Thursdays'], ['fri', 'Fridays'],
  ['sat', 'Saturdays'], ['sun', 'Sundays']];

function get(obj, path) { return path.split('.').reduce((o, k) => (o ? o[k] : undefined), obj); }
function set(obj, path, value) {
  const keys = path.split('.');
  let o = obj;
  keys.slice(0, -1).forEach((k) => { o[k] = o[k] || {}; o = o[k]; });
  o[keys.at(-1)] = value;
}

function field(label, input) {
  const f = el('label', 'field');
  f.append(el('span', '', label), input);
  return f;
}
function input(name, value = '', attrs = {}) {
  const i = el('input');
  i.dataset.key = name;
  i.value = value || '';
  Object.entries(attrs).forEach(([k, v]) => i.setAttribute(k, v));
  return i;
}
function select(name, options, value) {
  const s = el('select');
  s.dataset.key = name;
  options.forEach(([v, label]) => { const o = el('option', '', label); o.value = v; s.append(o); });
  if (value !== undefined && value !== null) s.value = value;
  if (s.selectedIndex < 0 && value) {  // custom value (e.g. "mon,wed") kept as an option
    const o = el('option', '', value); o.value = value; s.append(o); s.value = value;
  }
  return s;
}
function removeButton(row) {
  const b = el('button', 'remove', '×');
  b.type = 'button';
  b.setAttribute('aria-label', 'Remove');
  b.addEventListener('click', () => row.remove());
  return b;
}

function addPerson(p = {}) {
  const row = el('div', 'row-item person');
  row.append(
    field('Name', input('name', p.name, { placeholder: 'Priya' })),
    field('Relation', input('relation', p.relation, { placeholder: 'granddaughter' })),
    field('Birthday', input('birthday', p.birthday, { placeholder: 'DD-MM', pattern: '\\d{1,2}-\\d{1,2}', title: 'Day and month, e.g. 14-03' })),
    field('Notes', input('notes', p.notes, { placeholder: 'Studies in Bangalore, calls on Sundays' })),
    removeButton(row));
  $('people-rows').append(row);
}
function addReminder(r = {}) {
  const row = el('div', 'row-item reminder');
  const time = input('time', r.time, { type: 'time' });
  row.append(
    field('Reminder', input('title', r.title, { placeholder: 'BP tablet after breakfast' })),
    field('Type', select('kind', KINDS, r.kind || 'medication')),
    field('Time', time),
    field('Days', select('days', DAYS, r.days || 'daily')),
    removeButton(row));
  $('reminder-rows').append(row);
}
function readRows(container) {
  return [...container.querySelectorAll('.row-item')].map((row) => {
    const out = {};
    row.querySelectorAll('[data-key]').forEach((i) => { out[i.dataset.key] = i.value.trim(); });
    return out;
  });
}

function fill(profile, voices, styles) {
  form.querySelectorAll('[name]').forEach((i) => {
    const v = get(profile, i.name);
    if (v !== undefined && v !== null && i.type !== 'radio') i.value = v;
  });
  const voice = $('voice');
  voice.textContent = '';
  voices.forEach((v) => { const o = el('option', '', v.label); o.value = v.id; voice.append(o); });
  voice.value = profile.companion.voice || voices[0].id;
  const box = $('styles');
  box.textContent = '';
  const titles = { warm: 'Warm', cheerful: 'Cheerful', calm: 'Calm' };
  Object.entries(styles).forEach(([key, desc]) => {
    const label = el('label', 'choice');
    const r = el('input');
    r.type = 'radio'; r.name = 'companion.style'; r.value = key;
    r.checked = (profile.companion.style || 'warm') === key;
    label.append(r, el('b', '', titles[key] || key), el('span', '', desc));
    box.append(label);
  });
  $('people-rows').textContent = '';
  (profile.people.length ? profile.people : [{}]).forEach(addPerson);
  $('reminder-rows').textContent = '';
  (profile.reminders.length ? profile.reminders : [{}]).forEach(addReminder);
  if (profile.configured) $('title').textContent = `${profile.elder.preferred_name || 'Their'} profile`;
}

function collect() {
  const data = {};
  form.querySelectorAll('[name]').forEach((i) => {
    if (i.type === 'radio') { if (i.checked) set(data, i.name, i.value); return; }
    set(data, i.name, i.value.trim());
  });
  data.people = readRows($('people-rows')).filter((p) => p.name);
  data.reminders = readRows($('reminder-rows')).filter((r) => r.title).map((r) => ({ ...r, time: r.time || null }));
  return data;
}

async function load() {
  const { profile, voices, styles } = await api('/api/profile');
  fill(profile, voices, styles);
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!form.reportValidity()) return;
  $('save').disabled = true;
  $('save-status').textContent = 'Saving…';
  try {
    const { profile } = await api('/api/profile', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collect()),
    });
    $('save-status').textContent = `Saved. ${profile.companion.name || 'The companion'} is ready.`;
    $('go-checkin').classList.remove('hidden');
    $('title').textContent = `${profile.elder.preferred_name} profile`;
  } catch (err) {
    $('save-status').textContent = `Couldn't save: ${err.message}`;
  } finally {
    $('save').disabled = false;
  }
});

$('add-person').addEventListener('click', () => addPerson());
$('add-reminder').addEventListener('click', () => addReminder());
$('preview').addEventListener('click', async () => {
  const btn = $('preview');
  btn.disabled = true;
  btn.textContent = 'Loading…';
  try {
    const name = form.querySelector('[name="companion.name"]').value.trim() || 'your companion';
    const who = form.querySelector('[name="companion.address_as"]').value.trim()
      || form.querySelector('[name="elder.preferred_name"]').value.trim();
    const text = `Hello${who ? ` ${who}` : ''}! I'm ${name}. I'm looking forward to our chats every day.`;
    const { audio_url: url } = await api('/api/voices/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ voice: $('voice').value, text }),
    });
    if (url) await new Audio(url).play();
  } catch (err) {
    $('save-status').textContent = `Couldn't play the sample: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Play sample';
  }
});

load().catch((err) => { $('save-status').textContent = `Couldn't load the profile: ${err.message}`; });
