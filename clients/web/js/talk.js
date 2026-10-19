// Talk page: an open-ended conversation with the companion.
//   Start talking -> greeting -> listen (auto-stops on silence) -> send audio + 3 camera frames ->
//   show and speak the reply -> listen again ... until "End conversation" or a quiet pause.
// Typing works too (no voice/face reading for typed messages).
// The same page runs the "get to know you" setup conversation (flow = 'onboarding').
// This page is one "device" talking to the server API; a Raspberry Pi client would do the same
// steps with a USB mic, Pi camera and a physical button (see docs/ARCHITECTURE.md).

import { api, status, signed, verbalWord, el, storageGet, storageSet } from './common.js';
import { createVad } from './vad.js';

const $ = (id) => document.getElementById(id);
const ui = {
  layout: $('layout'), analysis: $('analysis'), toggle: $('toggle-analysis'),
  cameraToggle: $('toggle-camera'), camIndicator: $('cam-indicator'),
  status: $('status'), button: $('main-button'), end: $('end-button'), error: $('error'),
  transcript: $('transcript'), empty: $('empty'), hint: $('hint'), hintSub: $('hint-sub'),
  answers: $('answers'), bars: $('bars'), preview: $('preview'), camera: $('camera'),
  eyebrow: $('eyebrow'), setupHint: $('setup-hint'), knowButton: $('know-button'),
  analysisTitle: $('analysis-title'), analysisSub: $('analysis-sub'),
  progress: $('progress'), progressBar: $('progress-bar'),
  typeForm: $('type-form'), typeInput: $('type-input'),
};

const FRAME_TIMES = [800, 2000, 3500];   // when to grab camera frames while they speak
const BAR_SHAPE = [0.55, 0.8, 1, 0.8, 0.55];

// mode: loading | idle | busy | listening | paused | retry
let mode = 'loading';
let flow = new URLSearchParams(location.search).get('mode') === 'get-to-know' ? 'onboarding' : 'chat';
let stream = null;
let audioCtx = null;
let sessionId = null;
let onboardingId = null;
let companionName = 'Asha';
let elderName = '';
let stopListening = null;   // set while recording; call to finish the message early
let discardRecording = false;
let messageCount = 0;
let epoch = 0;   // bumped when the user interrupts (types, ends); stale async steps then stop

// ---------- small UI helpers ----------
function setStatus(text) { ui.status.textContent = text; }
function showError(text) { ui.error.textContent = text; ui.error.classList.toggle('hidden', !text); }
function setButton(label, newMode, { disabled = false, listening = false } = {}) {
  mode = newMode;
  ui.button.textContent = label;
  ui.button.disabled = disabled;
  ui.button.classList.toggle('listening', listening);
}
function setHint(main, sub = '') {
  ui.transcript.textContent = '';
  ui.hint.textContent = main;
  ui.hintSub.textContent = sub;
  ui.transcript.append(ui.empty);
}
function addLine(who, text, extra = '') {
  ui.empty.remove();
  const mine = who === 'You';
  ui.transcript.querySelectorAll('.line.latest').forEach((n) => n.classList.remove('latest'));
  if (mine) ui.transcript.querySelectorAll('.line.heard').forEach((n) => n.classList.remove('heard'));
  const line = el('div', `line latest ${mine ? 'you heard' : 'them'}`);
  if (!mine && text.length > 180) line.classList.add('long');   // long replies: smaller, still large, type
  const para = el('p');
  if (mine) {
    para.textContent = text;
  } else {
    text.split(/(\s+)/).forEach((part) => {
      if (!part) return;
      para.append(/\s/.test(part) ? document.createTextNode(part) : el('span', 'w', part));
    });
  }
  line.append(el('span', 'label who', mine ? (extra ? `You said · ${extra}` : 'You said') : who), para);
  ui.transcript.append(line);
  // Keep the person's own last message in view, so they can check it was heard right:
  // if their message and this reply don't both fit, scroll so their message is at the top.
  const heard = ui.transcript.querySelector('.line.heard');
  if (!mine && heard && heard.nextElementSibling === line) {
    const fits = ui.transcript.scrollHeight - heard.offsetTop <= ui.transcript.clientHeight;
    ui.transcript.scrollTop = fits ? ui.transcript.scrollHeight : heard.offsetTop - 12;
  } else {
    ui.transcript.scrollTop = ui.transcript.scrollHeight;
  }
  return line;
}
function keepInView(node) {
  // Follow the speech: if the word being spoken goes below the visible area, scroll just enough.
  if (!node) return;
  const box = ui.transcript.getBoundingClientRect();
  const r = node.getBoundingClientRect();
  if (r.bottom > box.bottom - 16) ui.transcript.scrollTop += r.bottom - box.bottom + 16;
}
function setLevel(level) {
  ui.bars.querySelectorAll('span').forEach((bar, i) => {
    bar.style.height = `${5 + Math.min(1, level) * 26 * BAR_SHAPE[i]}px`;
  });
}
function inConversation() { return Boolean(sessionId || onboardingId); }

// ---------- analysis column ----------
function scale(value, colorVar) {
  const s = el('div', 'scale');
  s.append(el('span', 'zero'));
  const mark = el('span', 'mark');
  mark.style.left = `${((Math.max(-1, Math.min(1, value)) + 1) / 2) * 100}%`;
  mark.style.background = `var(${colorVar})`;
  s.append(mark);
  return s;
}
function kv(dl, key, value) {
  const row = el('div', 'kv');
  row.append(el('dt', '', key), el('dd', '', value));
  dl.append(row);
}
function channelText(ch, kind) {
  if (!ch) return kind === 'face' ? 'no face' : 'too quiet';
  const pct = Math.round(ch.confidence * 100);
  return kind === 'face' ? `${ch.label} ${pct}% · ${ch.frames_used}/${ch.frames_total}` : `${ch.label} ${pct}%`;
}
function cardShell(title, statusEl, quote, tag) {
  ui.answers.querySelector('p.muted')?.remove();
  const card = el('article', 'answer');
  const head = el('div', 'answer-head');
  const left = el('div', 'answer-title');
  left.append(el('span', '', title));
  if (tag) left.append(el('span', 'tag', tag));
  head.append(left, statusEl);
  card.append(head);
  if (quote) card.append(el('p', 'answer-quote', `“${quote}”`));
  return card;
}
function addAnalysis(data) {
  const a = data.analysis;
  const tag = data.context === 'wellbeing' ? 'daily question' : (data.input === 'typed' ? 'typed' : '');
  const card = cardShell(`Message ${data.turn_index + 1}`, status(a.safety_flag ? 'urgent' : a.status), data.transcript, tag);
  const said = el('dl');
  kv(said, 'Said', `${verbalWord(a.verbal.valence)} ${signed(a.verbal.valence)}`);
  card.append(said, scale(a.verbal.valence, '--series-said'));
  if (a.verbal.reassurance.length) card.append(el('div', 'quote-small', `Reassurance: “${a.verbal.reassurance.join('”, “')}”`));
  const seemed = el('dl');
  if (data.input === 'typed') {
    kv(seemed, 'Seemed', 'n/a (typed)');
  } else {
    kv(seemed, 'Voice', channelText(a.nonverbal.channels.voice, 'voice'));
    kv(seemed, 'Face', channelText(a.nonverbal.channels.face, 'face'));
    kv(seemed, 'Seemed', a.nonverbal.available ? signed(a.nonverbal.valence) : 'n/a');
    if (a.baseline) kv(seemed, 'Low line', `${signed(a.low_threshold)} ${a.baseline.ready ? '(personal)' : `(fixed, ${a.baseline.sessions}/${a.baseline.needed})`}`);
  }
  card.append(seemed);
  if (data.input !== 'typed') card.append(scale(a.nonverbal.valence, '--series-seemed'));
  const rest = el('dl');
  if (data.input !== 'typed') kv(rest, 'Masking score', a.masking_score.toFixed(2));   // needs voice/face
  if (data.timings_s) kv(rest, 'Processing', `${data.timings_s.total.toFixed(1)} s`);
  card.append(rest);
  ui.answers.prepend(card);
}
function addLearned(data) {
  const label = data.learned.length ? 'Saved' : (data.skipped ? 'Skipped' : 'Nothing new');
  const card = cardShell(`Answer ${data.progress.answered}`, status(data.learned.length ? 'ok' : 'none', label), data.transcript);
  if (data.learned.length) {
    const ul = el('ul');
    data.learned.forEach((line) => ul.append(el('li', '', line)));
    card.append(ul);
  }
  ui.answers.prepend(card);
  const total = data.progress.answered + data.progress.remaining;
  ui.progressBar.style.width = `${Math.round((100 * data.progress.answered) / total)}%`;
}
function setAnalysisMode(onboarding) {
  ui.analysisTitle.textContent = onboarding ? 'Getting to know you' : 'Analysis';
  ui.analysisSub.textContent = onboarding
    ? 'Saved to the profile after every answer. Family can review and change it on the setup page.'
    : 'For each spoken message: what was said compared with how they seemed. For demos and evaluation.';
  ui.progress.classList.toggle('hidden', !onboarding);
  ui.progressBar.style.width = '0%';
  ui.answers.textContent = '';
  ui.answers.append(el('p', 'muted', onboarding ? 'What you share appears here.' : 'Each message you send appears here.'));
}

// ---------- media ----------
const AUDIO = { echoCancellation: false, noiseSuppression: false, autoGainControl: true, channelCount: 1 };
async function getMedia(audioOnly = false) {
  if (audioOnly) return navigator.mediaDevices.getUserMedia({ audio: AUDIO });
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: AUDIO, video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
    });
  } catch {
    return navigator.mediaDevices.getUserMedia({ audio: AUDIO });   // no camera: voice only
  }
}
async function ensureMedia(audioOnly) {
  if (stream) return true;
  try {
    stream = await getMedia(audioOnly);
  } catch {
    showError('The microphone is needed to talk. Allow microphone access in the browser and try again.');
    return false;
  }
  if (stream.getVideoTracks().length) {
    ui.preview.srcObject = stream;
    applyCamera();
  }
  audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
  await audioCtx.resume();
  return true;
}
function hasVideo() { return !!stream && stream.getVideoTracks().length > 0; }
function stopMedia() {
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null;
  applyCamera();
}
function grabFrame() {
  return new Promise((resolve) => {
    const v = ui.preview;
    if (!hasVideo() || !v.videoWidth) return resolve(null);
    const s = Math.min(1, 640 / v.videoWidth);
    const c = document.createElement('canvas');
    c.width = Math.round(v.videoWidth * s);
    c.height = Math.round(v.videoHeight * s);
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
    c.toBlob((b) => resolve(b), 'image/jpeg', 0.85);
  });
}
function pickMime() {
  const options = [['audio/webm;codecs=opus', 'webm'], ['audio/webm', 'webm'],
                   ['audio/mp4', 'm4a'], ['audio/ogg;codecs=opus', 'ogg']];
  for (const [mime, ext] of options) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(mime)) return { mime, ext };
  }
  return { mime: '', ext: 'webm' };
}

// ---------- speaking ----------
let currentAudio = null;
function speakWithBrowser(text, onWord) {
  return new Promise((resolve) => {
    if (!('speechSynthesis' in window)) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    u.onboundary = (e) => { if (e.name === 'word') onWord(text.slice(0, e.charIndex).split(/\s+/).filter(Boolean).length + 1); };
    u.onend = resolve; u.onerror = resolve;
    speechSynthesis.speak(u);
    setTimeout(resolve, 30000);
  });
}

// Speak a companion line, lighting up each word as it is heard. Word timings come from the server
// (edge-tts word boundaries); without them, progress is estimated from the audio's position.
async function speak(text, url, line) {
  setStatus(`${companionName} is speaking`);
  setButton('Let me talk', 'speaking', { listening: true });
  const words = line ? [...line.querySelectorAll('.w')] : [];
  if (line) line.classList.add('speaking');
  let shown = 0;
  const show = (n) => {
    const target = Math.min(words.length, Math.max(0, n));
    for (; shown < target; shown += 1) words[shown].classList.add('said');
    if (target) keepInView(words[target - 1]);
  };
  const finish = () => { show(words.length); line?.classList.remove('speaking'); };
  if (url) {
    const ok = await new Promise((resolve) => {
      const audio = new Audio(url);
      currentAudio = audio;
      const timingUrl = url.startsWith('/api/speech/') ? `${url}/timing` : null;
      let timing = null;
      let raf = 0;
      const poll = async () => {
        if (!timingUrl || currentAudio !== audio) return;
        try { timing = await api(timingUrl); } catch { /* keep estimating */ }
        if (!timing?.done && currentAudio === audio) setTimeout(poll, 300);
      };
      const tick = () => {
        const t = audio.currentTime;
        if (timing?.words.length) {
          const spoken = timing.words.filter((o) => o <= t + 0.05).length;
          const total = timing.done ? timing.words.length : Math.max(timing.words.length, words.length);
          show(Math.round((spoken * words.length) / total));
        } else if (Number.isFinite(audio.duration) && audio.duration > 0) {
          show(Math.round((words.length * t) / audio.duration));
        } else {
          show(Math.floor(t * 2.6));   // ~2.6 words a second
        }
        raf = requestAnimationFrame(tick);
      };
      const done = (played) => { cancelAnimationFrame(raf); resolve(played); };
      audio.onplaying = () => { poll(); cancelAnimationFrame(raf); raf = requestAnimationFrame(tick); };
      audio.onended = () => done(true);
      audio.onerror = () => done(false);
      audio.play().catch(() => done(false));
    });
    currentAudio = null;
    if (ok) { finish(); return; }
  }
  await speakWithBrowser(text, show);
  finish();
}
function stopSpeaking() {
  if (currentAudio) { currentAudio.pause(); currentAudio.onended?.(); }
  window.speechSynthesis?.cancel?.();
}

// ---------- listening ----------
function record() {
  return new Promise((resolve) => {
    const audioStream = new MediaStream(stream.getAudioTracks());
    const { mime, ext } = pickMime();
    const recorder = new MediaRecorder(audioStream,
      { ...(mime ? { mimeType: mime } : {}), audioBitsPerSecond: 128000 });
    const chunks = [];
    const frames = [];
    const timers = (flow === 'chat' ? FRAME_TIMES : []).map((t) => setTimeout(async () => {
      const f = await grabFrame(); if (f) frames.push(f);
    }, t));
    const source = audioCtx.createMediaStreamSource(audioStream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    const start = performance.now();
    const vad = createVad();
    let raf = 0, done = false, reason = 'manual';

    const finish = () => {
      if (done) return;
      done = true;
      cancelAnimationFrame(raf);
      timers.forEach(clearTimeout);
      if (recorder.state !== 'inactive') recorder.stop();
    };
    stopListening = finish;
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = async () => {
      source.disconnect();
      stopListening = null;
      if (flow === 'chat' && frames.length < 2) { const f = await grabFrame(); if (f) frames.push(f); }
      resolve({ blob: new Blob(chunks, { type: mime || 'audio/webm' }), ext, frames, reason });
    };
    const tick = () => {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      setLevel(rms / 0.1);
      const r = vad(rms, performance.now() - start);
      if (r.done) { reason = r.reason; finish(); return; }
      raf = requestAnimationFrame(tick);
    };
    recorder.start();
    raf = requestAnimationFrame(tick);
  });
}

async function listen() {
  if (!inConversation() || !stream) return;
  const my = epoch;
  showError('');
  setStatus('Listening. Take your time.');
  setButton('I’m done', 'listening', { listening: true });
  ui.bars.classList.remove('hidden');
  discardRecording = false;
  const { blob, ext, frames, reason } = await record();
  ui.bars.classList.add('hidden');
  setLevel(0);
  if (discardRecording || !inConversation() || my !== epoch) return;
  if (reason === 'no-speech') return pause();
  await sendVoice(blob, ext, frames);
}

function pause(message = 'Paused. Press Talk when you want to say something, or type below.') {
  setStatus(message);
  setButton('Talk', 'paused');
}

// ---------- sending ----------
async function handleReply(data, { autoListen }) {
  const my = epoch;
  const next = () => {
    if (my !== epoch || !inConversation()) return undefined;
    return autoListen ? listen() : pause();
  };
  if (!data.heard) {
    const line = addLine(companionName, data.reply_text);
    await speak(data.reply_text, data.reply_audio_url, line);
    return next();
  }
  addLine('You', data.transcript, data.input === 'typed' ? 'typed' : '');
  const replyLine = addLine(companionName, data.reply_text);
  messageCount += 1;
  if (flow === 'onboarding') addLearned(data); else addAnalysis(data);
  await speak(data.reply_text, data.reply_audio_url, replyLine);
  if (my !== epoch) return undefined;
  if (flow === 'onboarding' && data.done) return finishOnboarding();
  if (data.session_done) return endConversation(false);
  return next();
}

async function sendVoice(blob, ext, frames) {
  setStatus('Thinking');
  setButton('Please wait', 'busy', { disabled: true });
  const form = new FormData();
  form.append('audio', blob, `message.${ext}`);
  frames.forEach((f, i) => form.append('images', f, `frame${i}.jpg`));
  const url = flow === 'onboarding' ? `/api/onboarding/${onboardingId}/answer` : `/api/sessions/${sessionId}/turns`;
  try {
    const data = await api(url, { method: 'POST', body: form });
    await handleReply(data, { autoListen: true });
  } catch (err) {
    showError(err.message);
    setStatus('');
    setButton('Try again', 'retry');
  }
}

async function sendTyped(text) {
  if (flow === 'onboarding') return;   // the setup conversation is spoken
  epoch += 1;
  if (mode === 'listening' && stopListening) { discardRecording = true; stopListening(); }
  stopSpeaking();
  if (!sessionId && !(await startConversation({ listenAfterGreeting: false }))) return;
  setStatus('Thinking');
  setButton('Please wait', 'busy', { disabled: true });
  try {
    const data = await api(`/api/sessions/${sessionId}/messages`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
    });
    await handleReply(data, { autoListen: false });
  } catch (err) {
    showError(err.message);
    pause('');
  }
}

// ---------- conversation lifecycle ----------
async function startConversation({ listenAfterGreeting = true } = {}) {
  flow = 'chat';
  showError('');
  ui.setupHint.classList.add('hidden');
  setAnalysisMode(false);
  setButton('Please wait', 'busy', { disabled: true });
  setStatus('Turning on the microphone');
  if (!(await ensureMedia(false))) { setButton('Start talking', 'idle'); setStatus(''); return false; }
  try {
    const s = await api('/api/sessions', { method: 'POST' });
    sessionId = s.session_id;
    companionName = s.companion_name || companionName;
    messageCount = 0;
    ui.end.textContent = 'End conversation';
    ui.end.classList.remove('hidden');
    ui.transcript.textContent = '';
    const greetLine = addLine(companionName, s.greeting_text);
    const my = epoch;
    await speak(s.greeting_text, s.greeting_audio_url, greetLine);
    if (my === epoch && sessionId) { if (listenAfterGreeting) listen(); else pause(''); }
    return true;
  } catch (err) {
    showError(err.message);
    setButton('Start talking', 'idle');
    stopMedia();
    return false;
  }
}

async function endConversation(sayGoodbye = true) {
  epoch += 1;
  const id = sessionId;
  sessionId = null;
  if (stopListening) { discardRecording = true; stopListening(); }
  stopSpeaking();
  ui.end.classList.add('hidden');
  stopMedia();
  if (id) {
    try {
      const r = await api(`/api/sessions/${id}/end`, { method: 'POST' });
      if (sayGoodbye) {
        const byeLine = addLine(companionName, r.farewell_text);
        await speak(r.farewell_text, r.farewell_audio_url, byeLine);
      }
    } catch { /* ignore */ }
  }
  setStatus('Talk again whenever you like.');
  setButton('Start talking', 'idle');
}

// ---------- "get to know you" lifecycle ----------
async function startOnboarding() {
  flow = 'onboarding';
  showError('');
  ui.setupHint.classList.add('hidden');
  setAnalysisMode(true);
  ui.eyebrow.textContent = 'Getting to know you';
  setButton('Please wait', 'busy', { disabled: true });
  setStatus('Turning on the microphone');
  if (!(await ensureMedia(true))) { setButton('Start', 'idle'); setStatus(''); return; }
  try {
    const s = await api('/api/onboarding', { method: 'POST' });
    onboardingId = s.onboarding_id;
    companionName = s.companion_name || companionName;
    ui.end.textContent = 'Stop for now';
    ui.end.classList.remove('hidden');
    ui.transcript.textContent = '';
    const helloLine = addLine(companionName, s.text);
    await speak(s.text, s.audio_url, helloLine);
    listen();
  } catch (err) {
    showError(err.message);
    setButton('Start', 'idle');
    stopMedia();
  }
}

async function finishOnboarding(message = 'All set. Your profile is saved, so the chats can be about you.') {
  epoch += 1;
  const id = onboardingId;
  onboardingId = null;
  if (stopListening) { discardRecording = true; stopListening(); }
  if (id) { try { await api(`/api/onboarding/${id}/finish`, { method: 'POST' }); } catch { /* ignore */ } }
  flow = 'chat';
  history.replaceState(null, '', location.pathname);
  stopMedia();
  ui.end.classList.add('hidden');
  ui.eyebrow.textContent = talkLabel();
  setStatus(message);
  setButton('Start talking', 'idle');
}

// ---------- controls ----------
ui.button.addEventListener('click', () => {
  if (mode === 'idle') (flow === 'onboarding' ? startOnboarding : startConversation)();
  else if (mode === 'listening' && stopListening) stopListening();
  else if (mode === 'speaking') stopSpeaking();   // interrupt: the reply ends early, then it listens
  else if (mode === 'paused' || mode === 'retry') listen();
});
ui.end.addEventListener('click', () => {
  if (flow === 'onboarding') finishOnboarding('Saved what we talked about. You can carry on any time from the setup page.');
  else endConversation(true);
});
ui.knowButton.addEventListener('click', startOnboarding);
ui.typeForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = ui.typeInput.value.trim();
  if (!text || mode === 'busy') return;
  ui.typeInput.value = '';
  sendTyped(text);
});
window.addEventListener('pagehide', () => {
  if (sessionId) navigator.sendBeacon(`/api/sessions/${sessionId}/end`);
});

// ---------- camera preview toggle ----------
// Hiding the preview doesn't stop the camera (it still reads facial expression), so the video
// element keeps playing off-screen and a "Camera on" indicator replaces the picture.
let showCamera = storageGet('showCamera', 'false') === 'true';   // hidden by default
function applyCamera() {
  const live = hasVideo();
  ui.camera.classList.toggle('hidden', !live);
  ui.camera.classList.toggle('off', live && !showCamera);
  ui.camIndicator.classList.toggle('hidden', !(live && !showCamera));
  ui.cameraToggle.textContent = showCamera ? 'Hide camera' : 'Show camera';
  ui.cameraToggle.setAttribute('aria-pressed', String(showCamera));
}
applyCamera();
ui.cameraToggle.addEventListener('click', () => {
  showCamera = !showCamera;
  storageSet('showCamera', String(showCamera));
  applyCamera();
});

// ---------- analysis toggle ----------
function applyAnalysis(show) {
  ui.analysis.classList.toggle('hidden', !show);
  ui.layout.classList.toggle('no-analysis', !show);
  ui.toggle.textContent = show ? 'Hide analysis' : 'Show analysis';
  ui.toggle.setAttribute('aria-pressed', String(show));
}
let showAnalysis = storageGet('showAnalysis', 'true') === 'true';
applyAnalysis(showAnalysis);
ui.toggle.addEventListener('click', () => {
  showAnalysis = !showAnalysis;
  storageSet('showAnalysis', String(showAnalysis));
  applyAnalysis(showAnalysis);
});

// ---------- warm-up ----------
function talkLabel() {
  return `Talking with ${companionName} · ${new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}`;
}

async function waitForServer() {
  const names = { voice: 'voice model', face: 'face model', text: 'language model' };
  for (;;) {
    try {
      const h = await api('/api/health');
      companionName = h.companion_name;
      elderName = h.elder_name;
      ui.eyebrow.textContent = flow === 'onboarding' ? 'Getting to know you' : talkLabel();
      if (!h.groq_key_set) showError('Server setup: GROQ_API_KEY is missing in server/.env.');
      else if (!h.ffmpeg_found) showError('Server setup: ffmpeg is not installed or not on PATH.');
      const failed = Object.entries(h.models).filter(([, s]) => s === 'error');
      if (failed.length) {
        showError(`A model failed to load (${failed.map(([n]) => n).join(', ')}). Check the server log.`);
        return;
      }
      if (h.ready) {
        if (flow === 'onboarding') {
          setHint('Let’s get to know each other.',
            `${companionName} will ask a few questions about you and the people in your life, so your chats feel personal. It takes about five minutes, and you can say “skip” to any question.`);
          setButton('Start', 'idle');
          return;
        }
        if (h.configured) {
          setHint(`Hello, ${elderName}.`, `Talk to ${companionName} about anything you like: your day, your family, old memories, or just a chat.`);
        } else {
          setHint('Welcome. Let’s get to know each other first.',
            `${companionName} will ask a few questions about you, so your chats feel personal. Or just start talking.`);
          ui.setupHint.classList.remove('hidden');
        }
        break;
      }
      const loading = Object.entries(h.models).filter(([, s]) => s !== 'ready').map(([n]) => names[n]);
      setHint('Getting ready…', `Loading the ${loading.join(', ')}.`);
    } catch {
      setHint('Waiting for the server…', 'Make sure the server is running.');
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  setButton('Start talking', 'idle');
}
waitForServer();
