# Architecture

> **What this file is:** how the system is built: components, repo layout, data flow, API,
> data model, models, configuration, the device/Raspberry Pi integration path, and the
> load-bearing technical decisions. *What* we're building and *why*: [PROJECT_SPEC.md](PROJECT_SPEC.md).
> Update this file whenever files move, the API or schema changes, or a technical decision is made.

---

## 1. Overview

```
 ┌──────────────── device (any) ────────────────┐         ┌──────────────── server (laptop) ────────────────┐
 │ today: browser page (laptop webcam/mic,       │  HTTPS  │ FastAPI  (server/app/main.py)                   │
 │        or a phone browser via --https)        │ ──────► │   /api/sessions ... ──► services/conversation.py│
 │ later: Raspberry Pi client (button, LED,      │ ◄────── │                              │                  │
 │        USB mic / Pi camera, sensors)          │  JSON + │   models/  voice · face · text (loaded once)    │
 └───────────────────────────────────────────────┘   MP3   │   analysis/ fusion · masking · trends · safety  │
                                                           │   companion/ profile · memory · reminders · plan│
                                                           │   dialogue/ Groq Whisper · Groq LLM · edge-tts  │
 ┌──────── family (any browser) ─────────┐                 │   storage/  SQLite (server/data/companion.db)   │
 │ /dashboard  — alert, 14-day chart      │ ──────────────► │   /api/dashboard                                │
 └────────────────────────────────────────┘                 └─────────────────────────────────────────────────┘
```

**Key rule:** all analysis lives on the server, behind one HTTP API. A device only records
audio, grabs frames, plays audio and shows text. Adding the Raspberry Pi means adding a client,
not changing the analysis.

## 2. Repo layout

```
CLAUDE.md                  context + routing for new Claude Code sessions
README.md                  short project intro → points to docs/
docs/
  PROJECT_SPEC.md          problem, method, thresholds, hardware plan, open questions
  ARCHITECTURE.md          this file
  SETUP.md                 install / run / demo / troubleshooting (for the team)
  CHANGELOG.md             every change, newest first (+ how to restore pre-restart code)
server/
  run_server.py            entry point (HTTP :8000, or --https :8443 for phones)
  requirements.txt         Python deps (ffmpeg is a separate system install)
  .env.example             copy to .env: GROQ_API_KEY, names, optional overrides
  pytest.ini
  app/
    config.py              ALL settings + thresholds (env-overridable)
    main.py                FastAPI routes + serves clients/web as static files
    services/conversation.py  the device-agnostic pipeline: start (greeting), spoken/typed message, summarise, end
    companion/             what makes it *their* companion
      profile.py           profile (setup page): defaults, validation, voices, text for the LLM prompt
      memory.py            background extraction every 4 messages + at the end (strict JSON); recall
      reminders.py         schedules (daily / weekdays / once), today's status, what to mention
      plan.py              support(): when emotional care is needed; hints (once-a-day follow-up/reminder,
                           suggestion only when support continues); greeting hook
      onboarding.py        "get to know you" conversation: questions -> profile fields (strict JSON)
    models/                local ML models, each loaded once (registry.py = background warm-up)
      voice.py             autrainer wav2vec2 speech emotion (in-process autrainer Inference)
      face.py              YuNet face detection + ViT facial expression, averaged over frames
      text.py              RoBERTa sentiment → verbal valence
      assets/              face_detection_yunet_2023mar.onnx (230 KB, MIT)
    analysis/              pure functions, no I/O (easy to unit-test)
      audio.py             ffmpeg decode → 16 kHz mono, voice quality
      fusion.py            voice+face → one distribution + non-verbal valence
      masking.py           reassurance phrases + the masked/low/ok rule
      trends.py            daily series + family alert level
      baseline.py          personal baseline: the person's normal + personal low line
      safety.py            self-harm keyword screen
    dialogue/
      stt.py               Groq whisper-large-v3 (+ filter for silence hallucinations on quiet clips)
      llm.py               Groq LLM: personalised system prompt, greeting, replies, strict-JSON helper
      tts.py               edge-tts (default, streamed via /api/speech) / Groq Orpheus / gTTS
    storage/db.py          SQLite schema + queries
  scripts/
    seed_demo.py           synthetic 14-day history + sample profile + demo memories (is_demo=1)
    evaluate_baseline.py   simulation: fixed low line vs personal baseline
    smoke_test.py          real end-to-end run against a live server; also a reference device client
  evaluation/              evaluation on real data (docs/EVALUATION.md)
    common.py              paths, CSV, bootstrap/Wilson CIs, Groq calls with rate-limit waits
    voice_crema.py, voice_analysis.py, voice_tuning.py   voice model on CREMA-D: accuracy, age, masking, 14-day alerts
    face_utk.py            face model age bias on UTKFace
    verbal_safety.py       words side + keyword vs LLM self-harm screen
    conversation_sim.py    LLM-played user vs the real companion code, auto metrics + LLM judge
    memory_eval.py, latency_bench.py
    datasets/              (gitignored) CREMA-D, UTKFace
    results/               summary JSON (committed); raw/ per-item outputs (gitignored)
  tests/                   pytest: masking, fusion, trends, dialogue, companion, API (models stubbed)
    fixtures/              test_clip.wav/.m4a (synthetic, not speech), face_astronaut.jpg (NASA, public domain), noise_no_face.jpg
  data/                    (gitignored) companion.db, audio/, certs/, media/
clients/
  web/                     browser device + family dashboard (no build step, plain ES modules)
    index.html, js/talk.js        talk page (conversation + "get to know you")
    js/vad.js, js/vad.test.mjs    end-of-answer detection + simulated tests (node)
    dashboard.html, js/dashboard.js  family dashboard (hand-drawn SVG chart, reminders, memories)
    setup.html, js/setup.js       profile setup (people, routine, reminders, voice, personality)
    js/common.js, css/style.css
  pi/                      (future) Raspberry Pi client, see §9
archive/                   (gitignored) local-only leftovers from the old prototype
```

## 3. Components

| Component | Responsibility | Notes |
|---|---|---|
| `main.py` | HTTP layer only: parse uploads, call the service, return JSON | Endpoints are sync `def` → FastAPI runs them in a thread pool |
| `services/conversation.py` | Orchestrates one message end to end; owns the conversation lifecycle | The only place that knows the pipeline order |
| `companion/*` | Profile, onboarding, memory, reminders, support decisions + hints | Memory extraction runs on its own background thread |
| `models/registry.py` | Loads all models on a background thread at startup; `/api/health` reports status | One global `inference_lock` serialises torch calls |
| `analysis/*` | Pure scoring logic | All thresholds read from `config.py` at call time |
| `dialogue/*` | External services (Groq, edge-tts, gTTS) | Each degrades gracefully: LLM → fallback line, TTS → browser speech |
| `storage/db.py` | SQLite access | New connection per call; fine at this scale |
| `clients/web` | Device UI + dashboard | Talks to the API only |

## 4. Data flow

**Conversation start** (`POST /api/sessions`): close stale open conversations → load profile →
`memory.recall()` → if the daily question hasn't been answered today: `plan.greeting_hook()` +
`llm.greeting()` (ends with "how are you feeling today?", session `checkin=1`); else
`llm.casual_greeting()` → streamed voice. Typed messages (`/messages`) skip the audio/face steps.

**One spoken message (turn):**

```
POST /api/sessions/{id}/turns   (multipart: audio=answer.webm, images=frame0..2.jpg)
  │
  ├─ audio.load_waveform()        ffmpeg → 16 kHz mono float32
  ├─ [thread] stt.transcribe()    Groq Whisper on the ORIGINAL upload  ─────────┐
  ├─ voice.predict(waveform)      → 4-class probs  (quality = RMS)              │  run
  ├─ face.predict_frames(images)  → 4-class probs  (quality = frames × score)   │  concurrently
  ├─ fusion.fuse(voice, face)     → non-verbal valence                          │
  ├─ transcript ◄───────────────────────────────────────────────────────────────┘
  │     empty / hallucination → "Sorry, I didn't hear anything" (turn not stored)
  ├─ text.predict(transcript)     → verbal valence
  ├─ masking.find_reassurance()   → phrases
  ├─ baseline.compute(past sessions) → personal low line (fixed until 5 conversations)
  ├─ masking.analyse(.., low_line) → status (ok | low | masked) + masking_score
  ├─ safety.is_safety_concern()   → safety_flag
  ├─ plan.support(recent statuses, words, daily answer) → mode (None | daily | distress | sustained), suggest
  ├─ plan.hints(follow-up / reminder not yet said today, suggestion only if support.suggest)
  ├─ llm.reply(profile + memory + time + last 20 exchanges; guidance + optional hints in a private note;
  │            hedged: 120b if it answers within 3 s, else 20b)
  ├─ tts.speech_url(reply, profile voice) → /api/speech/<id> (streamed; word timings at /timing)
  └─ db.add_turn(context, input); conversation summary recomputed; memory step every 4 messages
```

**Get to know you** (`/api/onboarding`): per answer, Whisper → in parallel {`gpt-oss-20b` strict-JSON
extraction of profile fields, short reply + next question} → merge into the profile and save → reply
streamed. Topics already filled are skipped.

**Conversation end** (`POST .../end`, a new conversation starting, or the tab closing via `sendBeacon`): `memory.extract_in_background()` →
`gpt-oss-120b` with a strict JSON schema → new memories, reminders done (logged as
`conversation`), wellbeing signals and a summary saved on the session.

Typical timing on the dev laptop (CPU): models ~0.6 s, STT ~0.6 s (overlapped), LLM ~1–3 s (hedged),
**about 2 s until the reply text**, then streamed voice starts ~0.5 s later. Model warm-up at startup is
about 30–60 s.

## 5. API

All JSON. Errors that the user should see come back as `400 {"error": "..."}`.

| Method & path | Body | Returns |
|---|---|---|
| `GET /api/health` | – | `{models: {voice, face, text: not_loaded\|loading\|ready\|error}, errors, ready, groq_key_set, ffmpeg_found, configured, elder_name, companion_name}` |
| `POST /api/sessions` | – | `{session_id, greeting_text, greeting_audio_url, daily_question, max_turns (0 = open), companion_name}`; closes any stale open conversation |
| `POST /api/sessions/{id}/turns` | multipart: `audio` (required, any ffmpeg-readable format), `images` (0..n JPEG/PNG) | see below |
| `POST /api/sessions/{id}/messages` | JSON `{text}` | same shape as a turn, `input: "typed"`, no voice/face reading |
| `POST /api/sessions/{id}/end` | – | `{session, farewell_text, farewell_audio_url}` |
| `GET /api/sessions/{id}` | – | session row + `turns[]` (with full analysis) |
| `GET /api/dashboard?days=14` | – | `{elder_name, companion_name, configured, today, alert, series[], recent_sessions[], has_demo_data, baseline, thresholds, reminders[], memories[], wellbeing}` |
| `GET /api/audio/{name}` | – | `audio/mpeg` or `audio/wav` (file-based providers) |
| `GET /api/speech/{id}` | – | `audio/mpeg`, streamed while edge-tts generates it (ids come from reply/greeting URLs) |
| `GET /api/speech/{id}/timing` | – | `{words: [start seconds per spoken word], done}` for showing text as it's spoken |
| `POST /api/onboarding` | – | `{onboarding_id, text, audio_url, total, companion_name}` |
| `POST /api/onboarding/{id}/answer` | multipart: `audio` | `{heard, transcript, reply_text, reply_audio_url, learned[], skipped, topic, done, progress{answered, remaining}}` |
| `POST /api/onboarding/{id}/finish` | – | `{ok}` (stop early; what was saved stays saved) |
| `GET /api/profile` | – | `{profile (with configured), voices[], styles{}}` |
| `PUT /api/profile` | profile JSON (see `companion/profile.py` DEFAULT) | `{profile}`; also replaces reminders with `source='setup'` |
| `POST /api/voices/preview` | `{voice, text?}` | `{audio_url}` |
| `GET /api/reminders` | – | `{today: [.. status, confirmed_by], all: [..]}` |
| `POST /api/reminders` | `{title, kind, time "HH:MM"\|null, days, notes}` | `{id}` (source `family`) |
| `DELETE /api/reminders/{id}` · `POST /api/reminders/{id}/done` | – | `{ok}` |
| `GET /api/memories` · `DELETE /api/memories/{id}` | – | `{memories}` · `{ok}` |

Turn response:

```json
{
  "heard": true,
  "turn_index": 0,
  "transcript": "I'm fine, nothing to worry about.",
  "reply_text": "It's okay to have days like that. How did you sleep last night?",
  "reply_audio_url": "/api/audio/62bc....mp3",
  "session_done": false,
  "analysis": {
    "verbal":    {"valence": 0.75, "probs": {"positive": .., "neutral": .., "negative": ..},
                  "reassurance": ["I'm fine", "nothing to worry about"]},
    "nonverbal": {"label": "Sadness", "confidence": .., "probs": {..}, "valence": -0.65,
                  "weights": {"voice": 1.0}, "available": true,
                  "channels": {"voice": {label, confidence, probs, quality},
                               "face":  {label, confidence, probs, quality, frames_used, frames_total} | null}},
    "status": "masked", "masking_score": 0.70, "safety_flag": false,
    "low_threshold": -0.20, "baseline": {"ready": false, "sessions": 2, "needed": 5, ...}
  },
  "input": "voice", "context": "wellbeing",   // wellbeing = answer to the daily question
  "hints": ["A reminder is due: BP tablet at 9 am. ..."],
  "session_summary": {"turn_count": 1, "verbal_valence": .., "nonverbal_valence": .., "masking_score": ..,
                      "status": "masked", "reassurance": 1, "safety_flag": 0},
  "timings_s": {"models": 0.61, "stt_wait": 0.64, "llm": 1.03, "tts": 0.68, "total": 2.97}
}
```

When nothing intelligible was said: `{"heard": false, "reply_text": "...", "reply_audio_url": ..., "session_done": false}`.

## 6. Data model (SQLite, `server/data/companion.db`)

**sessions** (one conversation): `id` (hex uuid), `started_at` (ISO, local offset), `ended_at`, `greeting`,
`is_demo` (1 = seeded), `turn_count`, `verbal_valence`, `nonverbal_valence`, `masking_score`,
`status`, `reassurance`, `safety_flag`, `summary`, `signals_json`, `checkin` (greeting asked the daily
question). Scores: "said" = the daily answer if present else all messages; "seemed" = spoken messages
only (`nonverbal_valence` is NULL for a typed-only conversation). The score columns are recomputed
after every turn; `summary` and `signals_json` are written by the memory step after the session.

**turns** (one message): `id`, `session_id` (FK, cascade delete), `turn_index`, `created_at`, `transcript`,
`reply_text`, `verbal_valence`, `nonverbal_valence`, `masking_score`, `status`, `safety_flag`,
`analysis_json` (the full analysis object above), `context` (wellbeing | chat), `input` (voice | typed).

**profile**: one row (`id = 1`), the profile as JSON.

**reminders**: `id`, `title`, `kind` (medication | task | appointment | call | other), `time`
("HH:MM" or NULL), `days` (daily | "mon,wed" | "once:YYYY-MM-DD"), `notes`, `source`
(setup | family | companion), `active`, `created_at`.
**reminder_log**: `reminder_id`, `date`, `status` (done), `at`, `source` (conversation | dashboard);
unique per reminder per day.

**memories**: `id`, `created_at`, `kind` (person | event | preference | health | fact), `text`,
`person`, `event_date`, `session_id`, `is_demo`.

**onboarding**: `id`, `started_at`, `done`, `state_json` (remaining topics + log of question, answer,
reply and what was learned). Not a conversation: never used for trends, alerts or the baseline.

Daily series and alerts are **computed on read** (`analysis/trends.py`), not stored, so changing
a threshold re-scores history immediately.

No migrations framework: the schema is created with `CREATE TABLE IF NOT EXISTS`, and new columns
on existing tables are added by `db.MIGRATIONS` in `db.init()` (add an entry there for any new column).

## 7. Models

| Role | Model | Format / loading | Load | Per call | Licence |
|---|---|---|---|---|---|
| Voice emotion | `autrainer/msp-podcast-emo-class-big4-w2v2-l-emo` | autrainer checkpoint, **not** `transformers`; loaded with `autrainer.serving.Inference` from the torch-hub cache | ~15 s | ~0.3 s | CC-BY-NC-SA-4.0 |
| Face detection | OpenCV YuNet `face_detection_yunet_2023mar.onnx` | `cv2.FaceDetectorYN`, file in repo | <1 s | ~10 ms | MIT |
| Face expression | `trpakov/vit-face-expression` | `transformers` image classification | ~3 s | ~0.1 s | see model card |
| Verbal sentiment | `cardiffnlp/twitter-roberta-base-sentiment-latest` | `transformers` pipeline | ~5 s | ~20 ms | see model card |
| Speech-to-text | Groq `whisper-large-v3` (no prompt, temperature 0) | API | – | ~0.8 s | Groq ToS |
| Companion LLM | Groq `openai/gpt-oss-120b`, hedged with `openai/gpt-oss-20b` | both asked at once; 120b used if it answers within 3 s, else 20b. `max_tokens=400`, `reasoning_effort=low` | – | ~1–3 s | Groq ToS |
| Memory extraction | Groq `openai/gpt-oss-120b` | API, strict `json_schema` output, `reasoning_effort=medium`, background | – | ~2 s | Groq ToS |
| Onboarding extraction | Groq `openai/gpt-oss-20b` | API, strict `json_schema`, `reasoning_effort=low`, runs alongside the reply | – | ~1 s | Groq ToS |
| Text-to-speech | `edge-tts`, voice `en-IN-NeerjaNeural` (fallbacks: gTTS, then browser voice); optional Groq `canopylabs/orpheus-v1-english` | API | – | ~1.4 s | edge-tts/gTTS: unofficial, free; Orpheus: Groq ToS (terms acceptance required) |

First run downloads about 2 GB of model weights (torch-hub and Hugging Face caches under `%USERPROFILE%\.cache`).

## 8. Configuration

- **`server/app/config.py`** is the single source for paths, model IDs, names, conversation settings,
  valence mapping, masking thresholds, quality constants and alert rules. Most values can be
  overridden by environment variables of the same name.
- **`server/.env`** (gitignored; template `.env.example`): `GROQ_API_KEY` (required),
  `ELDER_NAME`, `COMPANION_NAME`, optional overrides (`LLM_MODEL`, `STT_MODEL`, `TTS_PROVIDER`, `TTS_EDGE_VOICE`, `TTS_EDGE_RATE`, `TTS_ORPHEUS_VOICE`,
  `MEMORY_MODEL`, `ONBOARDING_MODEL`, `LLM_FAST_MODEL`, `LLM_PRIMARY_WAIT_S`, `MAX_TURNS_PER_SESSION` (0 = open-ended), `HISTORY_TURNS`, `MEMORY_EVERY_N_TURNS`, `KEEP_MEDIA`, `BASELINE_*`, any threshold).
  `ELDER_NAME` / `COMPANION_NAME` are only fallbacks once a profile exists.
- Never hard-code a threshold elsewhere; add it to `config.py` and document it in PROJECT_SPEC §6.

## 9. Devices and the Raspberry Pi integration path

**Device contract:** any device that can do these steps works without server changes:

1. `GET /api/health` until `ready` (optional: show "warming up").
2. `POST /api/sessions` → play `greeting_audio_url` (or speak `greeting_text` locally).
3. Record what the person says (any format ffmpeg reads) and capture 0–3 camera frames.
4. `POST /api/sessions/{id}/turns` (multipart) → play `reply_audio_url` (optionally show words using
   `/api/speech/{id}/timing`). Typed text goes to `/messages`.
5. Repeat as long as they like (open-ended); `POST .../end` when they stop → play the farewell.

[`server/scripts/smoke_test.py`](../server/scripts/smoke_test.py) is a complete, standard-library-only
implementation of steps 1–4. Start the Pi client from it.

**Planned shapes (pick one when the Pi arrives; see PROJECT_SPEC §9):**

| | A. Phone browser + Pi hardware hub (recommended) | C. Pi as a standalone device |
|---|---|---|
| Camera/mic/speaker | phone, via the existing web page over `--https` | USB webcam/mic + speaker on the Pi |
| Pi's job | GPIO button, LED ring, PIR sensor (+ optional pulse sensor) | everything in the device contract + GPIO |
| New code | `clients/pi/` hub service + a small server "device events" channel so a Pi button press can start a conversation on the phone (e.g. Server-Sent Events `GET /api/device/events`, `POST /api/device/events`) | `clients/pi/` Python client based on `smoke_test.py` (+ `sounddevice`/`picamera2`, `gpiozero`) |
| Server changes | add the events endpoints; the web page subscribes to them | none |

**Where the server runs:** the laptop by default. Running it on a Pi 5 is a deployment change
(same code, CPU torch), but voice-model latency must be measured first.

Rules that keep Pi integration easy: analysis stays in `server/app/services` + `analysis`;
clients never compute scores; the API stays backwards-compatible (add fields, don't rename);
device-specific code lives only under `clients/<device>/`.

## 10. Technical decisions and gotchas (load-bearing; read before changing)

1. **The voice model is not a `transformers` checkpoint.** It's in autrainer's own format, so
   `AutoModel.from_pretrained` fails. Use `autrainer.serving.Inference` in-process. (The old
   prototype shelled out to the `autrainer` CLI per request: ~36 s per answer.)
   `voice._local_model_dir()` reads the torch-hub cache directly to skip an ~8 s Hugging Face API call.
2. **ffmpeg is a system dependency.** Browsers send WebM/Opus, phones AAC/M4A; `soundfile` can't
   decode either. Without ffmpeg on PATH every spoken message fails (`/api/health` → `ffmpeg_found`).
3. **Whisper gets the original upload**, not the transcoded WAV. Known silence hallucinations
   ("you", "thank you") are filtered to "not heard" (`stt.HALLUCINATIONS`), only on quiet clips.
   Use `whisper-large-v3` (11.4% vs 15.7% word errors for turbo on noisy accented clips) and **no
   `prompt`**: a context prompt made Whisper invent text ("Lakshmi replied, …").
4. **gpt-oss on Groq:** hidden reasoning tokens count against `max_tokens`, so keep 400 (~150
   truncates replies); `reasoning_effort="low"`. Groq intermittently returns
   `tool_use_failed` even though no tools are passed (known Groq bug), so retry up to 3 times,
   then fall back to a generic line. Empty completions are retried too.
5. **Text model choice:** a 7-class text-emotion model read "I'm fine, nothing to worry about" as
   67% *fear*. The sentiment model reads it 74% positive. Keep a sentiment model for "what they claim".
6. **Face detection = YuNet.** MediaPipe 1.x removed `mediapipe.python.solutions`; OpenCV 5
   removed the Haar `CascadeClassifier`. Only one OpenCV package may be installed
   (`opencv-python-headless`); having `opencv-contrib-python` alongside it breaks `cv2`.
7. **No "salience boost" in fusion.** The old prototype multiplied non-Neutral channels by 2.5,
   which would inflate false "masked" flags.
8. **Python environment:** use the standard Windows Python 3.12 build. MSYS2's Python can't
   install the numpy/torch wheels.
9. **Browsers only allow mic/camera on `https://` or `localhost`.** Phones need `--https`
   (self-signed cert auto-generated per LAN IP in `server/data/certs/`).
10. **End-of-answer detection** (`clients/web/js/vad.js`) must not learn the noise floor from the
    first moments only (people often start speaking immediately) and must allow thinking pauses
    (2.6 s). Record raw audio: browser noise suppression/echo cancellation clip word onsets.
    Run `node clients/web/js/vad.test.mjs` after changing it.
11. **TTS fallbacks:** Orpheus fails with `model_terms_required` until the Groq org admin accepts its
    terms; `tts.synthesize()` then falls back to edge-tts, then gTTS.
12. **Never let the LLM pick its own greeting hook.** Asked to "mention something you remember",
    gpt-oss invented events from profile interests ("your roses looked lovely yesterday"). The
    server picks a real, timely memory (`plan.greeting_hook`) or tells it to mention nothing.
13. **Replies must be forced to English.** With "Tamil" in the profile, the model replied in Tamil
    (speech recognition and voice are English-only).
14. **Memory extraction uses gpt-oss-120b**; 20b invented a relationship ("her daughter Priya").
    Give it a dated calendar for the week (it mis-resolved "Friday" without one), the profile, and
    known memories, and tell it to ignore what only the companion said.
15. **Groq strict JSON can reject on technicalities** (`json_validate_failed`, e.g. `null` for a list).
    `llm.complete_json` recovers the generated JSON from the error body; callers must tolerate nulls.
16. **Stream the voice.** edge-tts needs ~3.5 s for a two-sentence reply; `/api/speech/{id}` streams it so
    playback starts in ~0.5 s. Keep replies short anyway.
17. **Dual-stack socket** (`run_server.py`): Windows resolves `localhost` to ::1 first; an IPv4-only
    server costs ~2 s per new connection. `--reload` mode still binds 0.0.0.0 only.
18. **Hedged replies:** 120b is better but has 7–10 s spikes on Groq; asking 20b in parallel caps the
    wait at ~3 s (`llm.hedged`). Greetings use the same.
19. **Open conversation, analysed per message:** the masking rule applies to every spoken message, but
    a conversation's "said" uses the daily-question answer when there is one, because chit-chat
    sentiment ("the film was sad") isn't a self-report.
20. **Don't drive the conversation from single-message mood readings.** They are noisy ("Um" can read
    low). Reacting to each one made every reply a cheer-up suggestion. Support needs words with an emotion
    word, four low messages in a row, or the daily answer (`plan.support`), and suggestions wait a turn.
21. **Per-message notes beat general rules** for gpt-oss: "don't ask a question every time" in the system
    prompt was ignored; telling it per message "your last reply asked a question, don't this time" works.
22. **`llm.tidy()` every spoken reply:** the model uses em dashes and markdown despite instructions;
    strip them (and semicolons). Cap: 3 sentences / ~75 words, only between sentences, keeping a closing question so long
    answers continue next turn (a hard cut mid-list made "5." dangle; no cap made replies too long).
23. **Transcript scrolling:** never bottom-align a scrolling flex column with `justify-content: flex-end`
    (overflow above becomes unreachable); use `margin-top: auto` on the first child. After a reply,
    scroll so the person's own last message stays visible.
24. **Bind 0.0.0.0 / ::** so phones and the Pi on the same network can reach the server.

## 11. Testing

- `pytest` (from `server/`): unit tests for masking, fusion and trends, plus a full API flow with
  every model and cloud call stubbed. Runs in about 1 s, with no network or key needed.
- `python scripts/smoke_test.py [--audio file] [--image file]` against a running server: real
  models, real Groq. Note: it records a real conversation (clear with `seed_demo.py --clear-all`).
- `node clients/web/js/vad.test.mjs`: simulated loudness patterns for end-of-answer detection.
- `python scripts/evaluate_baseline.py [--drop 0.25]`: fixed vs personal low line on synthetic people.
- `server/evaluation/`: evaluation on real data and simulated conversations; results and how to re-run in
  [EVALUATION.md](EVALUATION.md). The Groq-based scripts use up the free daily budget.
- Manual: open the talk page and have a real conversation. The "Show analysis" panel shows every score.

## 12. Frontend design rules

The web client follows a quiet, editorial direction (references: Vercel Geist, Linear, Plausible).
Keep new UI consistent with it:

- **Monochrome.** Near-black (`--btn`) is the only action colour. Colour is used only for data:
  chart series (`--series-said` blue, `--series-seemed` orange, validated for colour-blind
  separation) and status dots (`--good`, `--warning`, `--serious`, `--critical`).
- **Status = dot + word** via `common.status(kind, label)`. Never colour alone, no pills or badges.
- **Hairlines, not boxes.** 1px `--line` borders and whitespace separate sections; no shadows
  (except the floating chart tooltip); radii 6px (buttons) / 8px (stat strip, big button).
- **Type:** Geist for text, Geist Mono for numbers, dates and small uppercase labels (`.label`).
  Weights 400/500 (600 only for the wordmark). Headings tracked −0.02em. Fonts load from Google
  Fonts and fall back to system fonts offline.
- **One focal point per screen:** the current spoken line (talk page), the summary sentence (dashboard).
- **Size for older readers:** 17px base; use the screen width (no narrow centred columns on
  desktop): the talk page stage is full width, dashboard is main + side column, setup is wide.
- **Elder-facing page:** latest line scales 34–54px, one primary 80px-tall button, no jargon. The analysis
  column is for demos/evaluation and can be hidden.
- **Avoid:** gradients, glass, glows, emoji/glyph icons, tinted alert boxes, card grids, chat bubbles.
- **Camera:** preview at the top-right of the talk stage (`.camera`), **hidden by default**, toggled by
  "Show/Hide camera". Hidden means off-screen but still playing (`.camera.off`, not `display:none`, which can
  stop frames), with a "Camera on" indicator; the camera itself stays on for the face reading.
- The talk page is exactly one screen tall; the transcript (`min-height: 0`) shrinks and scrolls inside.
- **Companion speech:** words are faint until spoken, then full ink (`.line.speaking .w.said`); the main
  button reads "Let me talk" while speaking (interrupt).
- **Scrollbars:** thin rounded thumb, no arrows/track (`--scroll-thumb`); WebKit rules for Chromium, the
  standard properties only as a Firefox fallback.
- Light and dark themes come from `:root` tokens in `style.css` (`prefers-color-scheme`, `data-theme`).
