// Simulated loudness patterns for the end-of-answer detector. Run: node clients/web/js/vad.test.mjs
import assert from 'node:assert/strict';
import { createVad } from './vad.js';

const FPS = 60;
const STEP = 1000 / FPS;

// segments: [durationMs, kind] where kind is 'room' (quiet), 'speech', 'fan' (steady noise)
function run(segments, levels = { room: 0.003, speech: 0.06, fan: 0.015 }) {
  const update = createVad();
  let t = 0;
  let i = 0;
  for (const [ms, kind] of segments) {
    for (const end = t + ms; t < end; t += STEP, i++) {
      // speech has natural syllable dips; noise is steady with small jitter
      let rms = levels[kind] * (0.9 + 0.2 * ((i * 7919) % 100) / 100);
      if (kind === 'speech' && i % 9 === 0) rms = levels.room * 2;
      const r = update(rms, t);
      if (r.done) return { ...r, at: Math.round(t) };
    }
  }
  return { done: false, at: Math.round(t) };
}

// 1. Speaking immediately must not raise the threshold above the voice (old bug: cut off at "I").
let r = run([[3000, 'speech'], [4000, 'room']]);
assert.equal(r.reason, 'silence');
assert.ok(r.at > 3000 + 1700, `stopped too early at ${r.at}`);

// 2. A short (1.2 s) pause mid-answer does not end it.
r = run([[300, 'room'], [1200, 'speech'], [1200, 'room'], [1500, 'speech'], [4000, 'room']]);
assert.equal(r.reason, 'silence');
assert.ok(r.at > 300 + 1200 + 1200 + 1500, `ended during the pause at ${r.at}`);

// 3. A long pause (>1.8 s) does end it.
r = run([[300, 'room'], [1500, 'speech'], [5000, 'room']]);
assert.equal(r.reason, 'silence');
assert.ok(r.at < 300 + 1500 + 2200);

// 4. A click/bump shorter than 250 ms is not speech -> waits for real speech, then times out.
r = run([[500, 'room'], [100, 'speech'], [13000, 'room']]);
assert.equal(r.reason, 'no-speech');

// 5. Steady fan noise is learned as the floor; speech over it is still detected and ends normally.
r = run([[1000, 'fan'], [2000, 'speech'], [4000, 'fan']], { room: 0.012, speech: 0.08, fan: 0.015 });
assert.equal(r.reason, 'silence');

// 6. A quiet talker (rms ~0.02) is still heard.
r = run([[300, 'room'], [2500, 'speech'], [4000, 'room']], { room: 0.002, speech: 0.02, fan: 0 });
assert.equal(r.reason, 'silence');
assert.ok(r.at > 2800 + 1700);

// 7. Nothing said at all -> gives up after ~12 s.
r = run([[15000, 'room']]);
assert.equal(r.reason, 'no-speech');

console.log('vad: all 7 scenarios pass');
