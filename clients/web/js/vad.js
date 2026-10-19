// Voice activity detection for "when has the person finished answering?".
// Pure logic (no browser APIs) so it can be tested with node: `node clients/web/js/vad.test.mjs`.
//
// Design:
// - adaptive noise floor: drops instantly to quieter levels and creeps up slowly, so starting
//   to speak immediately (or a loud room) doesn't push the threshold above the voice itself;
// - speech must last minVoicedMs before it counts (ignores clicks and bumps);
// - stops only after silenceMs of quiet following speech.

export const LISTEN_DEFAULTS = {
  maxMs: 30000,          // hard cap on one answer
  noSpeechMs: 12000,     // give up if nothing is said at all
  silenceMs: 1800,       // stop after this much silence following speech
  minVoicedMs: 250,      // sound above the floor needed before it counts as speech
  floorStart: 0.004,
  floorCreep: 0.0005,    // per update (~60/s): time constant ~30 s
  minThreshold: 0.008,
  maxThreshold: 0.03,
  floorMultiple: 3,
};

export function createVad(options = {}) {
  const o = { ...LISTEN_DEFAULTS, ...options };
  let floor = o.floorStart;
  let prev = null;
  let lastVoice = 0;
  let voicedMs = 0;
  let spoke = false;

  // rms: loudness of the latest audio frame (0..1); now: ms since recording started.
  return function update(rms, now) {
    const dt = prev === null ? 0 : now - prev;
    prev = now;
    floor = rms < floor ? rms : floor + (rms - floor) * o.floorCreep;
    const threshold = Math.min(o.maxThreshold, Math.max(o.minThreshold, floor * o.floorMultiple));
    if (rms > threshold) {
      voicedMs += dt;
      lastVoice = now;
      if (voicedMs >= o.minVoicedMs) spoke = true;
    }
    let reason = null;
    if (now > o.maxMs) reason = 'max';
    else if (!spoke && now > o.noSpeechMs) reason = 'no-speech';
    else if (spoke && now - lastVoice > o.silenceMs) reason = 'silence';
    return { done: reason !== null, reason, spoke, threshold };
  };
}
