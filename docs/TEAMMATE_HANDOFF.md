# Teammate Handoff — Cognitive Robotics Watch Project

## Current focus

A closed loop on a real smartwatch: user speaks → watch records it → a laptop server detects the emotion in
their voice → generates an empathetic LLM response conditioned on that emotion → converts it to speech → sends
it back → the watch speaks it through its own built-in speaker.

Heart rate, face detection, and multimodal fusion are explicitly out of scope right now (documented future
Phase 2, not abandoned).

## Device

Samsung Galaxy Watch Active2 (SM-R830), Tizen OS 5.5. Confirmed sensors: HR (PPG), mic, speaker, WiFi,
Bluetooth — no camera. This is the one and only target device (a Fire-Boltt watch was evaluated and ruled out —
closed proprietary firmware, no SDK).

## Critical technical decision: native C++, not Tizen Web app

`getUserMedia()`-based audio recording is confirmed broken on physical Tizen wearable hardware (works in
simulator only). Native Recorder/Player APIs are reliable. Native C++ via Tizen Studio is required, not
optional.

- Recording: `<recorder.h>` — `recorder_create()` → `recorder_attr_set_audio_device(rec, RECORDER_AUDIO_DEVICE_MIC)`
  → `recorder_prepare()` → `recorder_start()` → `recorder_commit()`. Output: M4A. Privilege:
  `http://tizen.org/privilege/recorder`.
- Playback: `<player.h>` — `player_create()` → `player_set_uri()` → `player_prepare()` → `player_start()`,
  `player_set_completed_cb()`. Supports MP3 directly. No special privilege for local playback.
- Network: libcurl, POST/response. Privilege: `http://tizen.org/privilege/internet`.

See `docs/WATCH_SETUP_GUIDE.md` for device/certificate setup and `docs/VOICE_LOOP_PLAN.md` for the full data
flow and module spec.

## Model/TTS/LLM decisions (already made, don't relitigate without new evidence)

- Voice emotion: pretrained `autrainer/msp-podcast-emo-class-big4-w2v2-l-emo` (audEERING, MSP-Podcast, real
  spontaneous speech) — no training pipeline. Chosen over a custom RAVDESS/CREMA-D-trained CNN because acted
  speech generalizes poorly to real spontaneous speech (per the EMOVOME paper comparison).
- TTS: gTTS (free, MP3 output, no conversion needed for the watch's Player API).
- LLM: any capable provider, swappable behind one function.

## Sequencing (don't skip)

Prove the dumb end-to-end plumbing (watch → server → fixed test MP3 → watch plays it) before wiring in the real
emotion→LLM→speech pipeline. This isolates "does the hardware round-trip work" from "does the pipeline produce
good output."
