# Changelog

> **What this file is:** a log of every change, newest first, so we can see what changed,
> why, and how to go back. Add an entry for **every** change (code, docs, config, deps).
> Format: `## YYYY-MM-DD: short title`, then **Added / Changed / Removed / Fixed** bullets,
> with the commit hash once committed. Big decisions also go in PROJECT_SPEC or ARCHITECTURE.
>
> **Going back:** `git log --oneline` to find a commit, then `git checkout <hash> -- <path>` to
> restore files. The whole pre-restart prototype is tagged **`v0-legacy`** (see the bottom).

---

## 2026-10-21: README with install and run steps, submission documents

**Changed**
- `README.md`: now says what to install, how to install (Windows and macOS/Linux), how to run, first use,
  demo data, phone use and tests, then links to the docs. SETUP.md stays the full guide.

**Added**
- `docs/23BAI1350_Source_Code_and_Installation.docx`: GitHub link plus install and run instructions (2 pages).
- `docs/23BAI1350_Flowcharts_Screenshots_Results.docx`: system and message flowcharts, the family alert logic,
  screenshots of the talk page and dashboard, and the final evaluation results (9 pages).
- `.gitignore`: `~$*` (Word lock files).

---

## 2026-10-20: Results document

**Added**
- `docs/Asha_Results.docx`: the evaluation results in plain language for the presentation (summary table,
  then each result: what was measured, the result, what it means). Numbers are from EVALUATION.md §0–§11.

---

## 2026-10-20: Showcase demo conversation, plainer analysis, chart low line

Request: remove "Includes demo data", add a good demo conversation where Asha reminds her of good things,
and make "vs. their normal" easier to understand. (A separate Conversations page was tried and removed.)

**Added**
- `seed_demo.py`: the masked scenario's last day (yesterday) is a scripted 7-message conversation (masked, then
  opening up, then Asha recalls her roses, Priya's exams and Kamala, checks the BP tablet, and she brightens;
  the conversation still reads masked). Three more demo memories; demo days get readable summaries.
- Talk page analysis cards start with one plain sentence ("Said they're fine, but seemed lower than their usual.").

**Changed**
- Dashboard: no "Includes demo data" label and no "demo" tags on conversations or memories
  (`has_demo_data` stays in the API).
- "Vs. their normal" → "Compared with usual … (low below …)".

**Fixed**
- The chart's dashed low line was drawn at the threshold value (a drop from normal, e.g. −0.32) once the
  personal baseline was ready, so masked days could sit above it. It's now at the voice's normal − drop.

---

## 2026-10-20: Project renamed from "I'm Fine" to Asha

Request: name the project after the companion (Asha, `COMPANION_NAME`).

**Changed**
- Page titles and wordmarks (talk, dashboard, setup), the dashboard's tab title, the FastAPI app title,
  README, PROJECT_SPEC and CLAUDE.md headings, and the page-title test in `test_api.py`.
- "I'm fine" as the reassurance phrase the system detects is unchanged. Older changelog entries keep the old name.

---

## 2026-10-19: Fixes from the evaluation (safety, LLM budget, baseline, invention)

Request: make all the changes the evaluation recommended, using only the data we have (no older adults
available yet). Re-tested results in EVALUATION.md §11.

**Changed**
- **Self-harm screen** (`analysis/safety.py`): keyword regex + LLM screen (`gpt-oss-safeguard-20b`, then
  gpt-oss-20b, qwen3.8-27b) on every message, with the last 3 messages and the profile's losses as context,
  run in parallel with the reply. A flag replaces the reply with a fixed `llm.safety_reply()` (helpline:
  Tele-MANAS 14416, configurable) and later replies follow `SAFETY_FOLLOWUP`. A screen result that arrives
  late still flags the message. Re-test: 100% of direct and indirect statements on a new held-out set, 0
  false alarms (keywords alone: 33% / 0%). A prompt tweak that cut context false alarms was rejected: it
  missed one real risk.
- **LLM budget:** 20b is asked only if 120b hasn't answered after 1.5 s (was: both at once, double tokens);
  rate-limited models go on cooldown and replies move to `LLM_BACKUP_MODELS` (qwen3.8-27b, reasoning off);
  if nothing answers the reply says "I'm having a little trouble thinking right now…" instead of "I didn't
  catch that". `/api/health` and the dashboard show when a backup is in use.
- **Fixed low line −0.20 → −0.55** until the baseline is ready (measured: −0.20 flagged 75% of calm "I'm fine"
  answers; −0.55 flags 17%, 7% false alerts).
- **Personal baseline per channel** (voice, face), 7 calibration conversations (was 5, fused), the **voice
  decides** (`BASELINE_COMBINE=voice`). New session columns `voice_valence`, `face_valence`, `readings`
  (backfilled at startup); days weighted by readings.
- **Readings** need ≥ 0.4 s of speech (`audio.speech_seconds`); a higher cut-off would mostly drop sad answers.
- **Words:** Indian-English reassurances ("okay only", "what to say", "all good"); "I'm fine, but I miss him"
  counts as opening up (emotion word or clearly negative clause after but/though/just).
- **Prompt:** Asha is an app (no body, family, senses, past); only facts from notes or this conversation; gently
  correct confusion; drop a joke when they move on; greeting hook in its own sentence.
- **Sensitive topics enforced in code:** names from the profile's sensitive topics are hidden from the LLM
  (profile, memories, greeting hook) until the person mentions them in the conversation.
- Memory prompt: visitors count as social contact; skipping meals = poor appetite.

**Fixed**
- Typed-only days were dropped from the daily series, so a typed self-harm disclosure never raised the
  urgent alert.

**Added**
- `evaluation/voice_short.py`, `voice_length.py`, `channel_sim.py`, `safety_context.py`; held-out and context
  safety sets in `verbal_safety.py`; `tests/test_evaluation_fixes.py` (26 tests).

---

## 2026-10-19: Evaluation on real data and simulated conversations

Request: run simulations and tests, get real results, say whether it works and what to change.

**Added**
- `server/evaluation/` (scripts + summary results, datasets gitignored) and **docs/EVALUATION.md** (full report):
  - `voice_crema.py`, `voice_analysis.py`, `voice_tuning.py`: voice model on CREMA-D (4,900 clips, 91 actors aged
    20–74): accuracy 49% (happy 11%), neutral reads −0.34, no clear age trend; masking per message and a 14-day
    family-alert simulation on real readings: fixed line 88% false alerts, personal baseline 12% false / 62% caught
    (87% caught at 6 spoken answers a day); baseline setting sweep.
  - `face_utk.py`: face model on UTKFace by decade; non-smiling faces over 50 read as sad ~2× as often.
  - `verbal_safety.py`: "says OK" 96% on masking phrases; self-harm keyword screen catches 8% of indirect statements,
    gpt-oss-safeguard-20b 92% with 0 false alarms.
  - `conversation_sim.py`: LLM-played Lakshmi in 8 scenarios against the real companion code, auto metrics + LLM judge.
    Style rules hold (0 dashes, 0 semicolons), support only in low scenarios; problems: invented details, claims to be
    human, raised the late husband unprompted, deflected suicidal ideation, which the keyword screen also missed.
  - `memory_eval.py` (memory extraction vs ground truth), `latency_bench.py` (per-step timings).
- `.gitignore`: `server/evaluation/datasets/`, `server/evaluation/results/raw/`.

**Found (not fixed yet, see EVALUATION.md §8)**
- When the free Groq budget runs out (~80 replies/day), every reply becomes "Sorry, I didn't quite catch that."

---

## 2026-10-19: Camera back top-right and hidden by default, no semicolons

Feedback: the earlier camera placement was fine; keep it hidden by default; avoid semicolons in replies.

**Changed**
- Camera preview back at the top-right of the conversation; **hidden by default** (Show camera in the
  header, remembered per browser). Hidden still means the camera works for the face reading, with a
  "Camera on" indicator in its place (verified: frames still captured while hidden).
- The talk page now fits exactly one screen: the conversation area shrinks and scrolls inside, so showing the
  camera no longer pushes the buttons off-screen.
- **No semicolons:** prompt rule plus `llm.tidy()` turns "; " into a new sentence ("…lemon rice. It still…").

---

## 2026-10-19: Camera self-view and Show/Hide camera

Feedback: place the webcam footage more pleasingly, with an option to show or hide it.

**Changed**
- The camera preview moved from the top-right of the conversation (where it pushed the text down) to a
  rounded **self-view in the controls row**, next to the mic button, like a video call ("You" label).
- **Hide camera / Show camera** in the header (remembered per browser). Hiding only hides the picture: the
  camera keeps reading facial expression, the video keeps rendering off-screen (verified frames are still
  captured), and a "Camera on" indicator replaces the picture so it's always clear the camera is active.
- Typed messages no longer show a masking score in the analysis card (it needs voice/face).

---

## 2026-10-19: Words appear as they're spoken, interrupt button, sentence cap back, scrollbar

Feedback: the scrollbar looked bad; text should appear as the companion speaks; a button to
interrupt without ending the conversation; bring the sentence cap back (long replies are annoying).

**Added**
- **Words light up as they're heard:** edge-tts word boundaries are recorded while the audio streams
  (`tts.stream`, `boundary="WordBoundary"`) and served at `GET /api/speech/{id}/timing`. The talk page
  shows each companion line faint and lights up words in time with `audio.currentTime` (estimates from the
  audio position if timings are missing; `onboundary` for the browser voice). The view follows the spoken
  word if it goes below the fold.
- **"Let me talk" interrupt:** while the companion speaks, the main button becomes "Let me talk"; it stops
  the audio, shows the rest of the text, and goes straight to listening (or pauses after a typed message).
  The conversation continues. Verified in Edge with Playwright: words revealed 0 to 33 of 96 over ~13 s,
  the interrupt revealed all and kept the conversation open.

**Changed**
- **Sentence cap back, smarter** (`llm.tidy`): at most 3 sentences and ~75 words, cut only between
  sentences; a closing question ("Would you like the next steps?") is always kept so long answers continue
  in the next turn; list numbers ("2. ") are removed instead of counted. Prompt: long things (recipes,
  stories) are given in small parts.
- **Scrollbar:** thin rounded thumb, no arrows or track, darker on hover, own colour token per theme
  (`--scroll-thumb`). WebKit pseudo-elements for Chromium (the standard properties make Chrome on Windows
  draw arrows and a track); `scrollbar-width/color` only where `::-webkit-scrollbar` isn't supported.
- Tests: timing endpoint, caps (50 pass).

---

## 2026-10-19: See what you said, no length cap, rename the companion

Feedback: with a long reply the person can't see their own message to check it was heard right;
remove the sentence cap (it cut a recipe off mid-step at "5."); let the companion's name be changed
in setup.

**Fixed**
- **Your own message stays visible:** the transcript used `justify-content: flex-end`, which makes
  overflowing content above unreachable by scrolling. Now bottom-aligned with `margin-top: auto`, and
  after each reply the page scrolls so the person's message ("You said") is at the top if both don't
  fit. Their latest message is shown larger; long replies (>180 characters) use a smaller, still large,
  size; older lines fade at the top edge.

**Changed**
- **No sentence cap** in `llm.tidy()`. Prompt: usually 1-2 sentences, longer when they ask for a recipe,
  story or explanation, spoken step by step without numbered lists.
- **Companion's name:** the "Their companion" section moved to second place on the setup page (name,
  how it addresses them, voice, personality). The spoken "get to know you" now asks "would you like to
  call me something else?" (skipped if a name is already set) and saves the answer.
- Tests: rename via setup and via onboarding (49 pass).

---

## 2026-10-19: Natural conversation: support only when needed, no em dashes

Feedback: replies used em dashes; Asha kept repeating the same things and not responding to what
was asked; emotional support felt forced into every reply. The user's own conversations showed
why: single-message voice readings marked ordinary lines ("Um", "Oh no, I forgot") as low, and each
"low" triggered a cheer-up suggestion (call Priya, hum M.S. Subbulakshmi, the roses) almost every turn.

**Changed**
- **Support only when needed** (`plan.support`): emotional notes are added only for (a) distress in
  words: negative sentiment AND an emotion word (lonely, miss, sad, scared, worried...), (b) the last
  four spoken messages all reading low, or (c) the answer to the daily question reading low/masked.
  Otherwise the note just says "keep chatting naturally". **Listen first:** a concrete suggestion is
  only offered when support is still needed on the next message too, never on the daily answer, and at
  most once every 5 messages.
- **Conversation style** (system prompt rewritten): a friend, not a therapist or assistant; answer what
  was asked first and actually do what's asked (joke, game, guess); don't steer back to family, garden,
  songs or health; mention notes at most once per conversation; don't interview (questions at most
  every other reply, enforced per message: if the last reply asked a question, the next is told not to);
  short replies to "okay"/"yes"; can't sing, says so; never name specific song or film titles; respond
  to adult topics calmly; time of day stated explicitly.
- Reminders and follow-ups at most **once a day** across conversations (was once per conversation).
- **`llm.tidy()`** on every spoken reply: em/en dashes and " - " become commas, markdown/asterisks and
  line breaks removed, missing spaces after sentence ends fixed, max 3 sentences.
- Live test (11 spoken lines incl. the user's problem cases): 0 dashes, questions in 4/11 replies
  (was 8/11), jokes/facts/games answered directly, support only for "I miss my husband... alone".
- Tests: support rules, tidy, notes (47 pass).

---

## 2026-10-19: From check-in to companion conversation

Feedback: the structured check-in "feels weird or unnatural"; it should be a normal companion
that holds conversations in context, with the check-in as a once-a-day thing. Analysis entries were
hard to tell apart. Also: create a sample profile.

**Changed**
- **Open-ended conversations** (`server/app/services/conversation.py`, replaces `services/checkin.py`):
  no answer limit (`MAX_TURNS_PER_SESSION=0`), last 20 exchanges kept in context, the companion follows
  the person's lead and can answer questions (songs, recipes, stories). Starting a conversation closes
  any stale open one.
- **Daily question once a day:** the first conversation of the day greets with "how are you feeling
  today?" (`sessions.checkin=1`, that answer stored as `turns.context='wellbeing'`); later ones get a
  casual hello. Conversation summary: "said" = daily answer if present else all messages; "seemed" =
  spoken messages only.
- **Hints instead of a script** (`plan.hints`): follow-up on a remembered event (early, if not already
  mentioned), a due reminder (once per conversation), one cheer-up idea when they seem low. All optional.
- **Replies hedged across two models:** 120b (better: natural, culturally fitting, fewer invented facts)
  and 20b asked together; 120b used if it answers within 3 s, else 20b. Live run: 5 of 6 replies from
  120b, all within ~2 s (one 4 s). 120b alone had 7–10 s spikes; 20b alone invented song titles,
  offered to "play a recording", and wrote a long recipe.
- Prompt rules: at most one question per reply, don't keep returning to a topic, don't invent titles or
  facts, never sound like an assistant. Casual greetings don't re-mention events.
- Talk page (`clients/web/js/talk.js`, replaces `checkin.js`): auto-listens after each reply, pauses after
  ~12 s of silence (press Talk), typing box (`POST /api/sessions/{id}/messages`), End conversation →
  spoken goodbye, conversation closed on tab close (`sendBeacon`). Nav "Talk".
- **Analysis cards:** each message is a bordered card with its number, status, the words quoted, and a
  "daily question" / "typed" tag.
- Dashboard and alert wording: conversations / days talked instead of check-ins.

**Added**
- `POST /api/sessions/{id}/messages` (typed), farewell on `/end`, DB columns `sessions.checkin`,
  `turns.context`, `turns.input` (auto-migrated), config `LLM_FAST_MODEL`, `LLM_PRIMARY_WAIT_S`,
  `HISTORY_TURNS`, `MEMORY_EVERY_N_TURNS`.
- A sample profile (Lakshmi) saved into the local database for testing.
- Tests: open conversation, daily question once a day, typed messages, summary rule, hedging (44 pass).

---

## 2026-10-19: "Get to know you" voice setup, full-width larger layout, streamed voice

Feedback: build the spoken onboarding (backlog #3); the pages left a lot of unused width; make
everything bigger and more readable for older users.

**Added**
- **"Get to know you" conversation** (`server/app/companion/onboarding.py`, `POST /api/onboarding`,
  `/api/onboarding/{id}/answer`, `/api/onboarding/{id}/finish`, table `onboarding`): Asha asks up to 9
  questions (name, story, living situation, important people, usual day, interests, what cheers them
  up, medicines/tasks to be reminded of, topics to avoid). Each answer is turned into profile fields
  (strict JSON) and saved immediately; already-filled topics are skipped; "skip" works. Not counted as
  a check-in. Started from the check-in page ("Get to know each other", shown until a profile exists)
  or the setup page ("Set up by talking", `index.html?mode=get-to-know`). The analysis column shows a
  progress bar and what was saved from each answer.
- **Streamed voice** (`GET /api/speech/{id}`, `tts.speech_url()`): with edge-tts the reply URL is
  returned immediately and audio streams while it is generated. First audio in ~0.5 s instead of
  waiting ~3.5 s for the whole file. Bytes are cached for 15 min; gTTS fallback if edge fails.
- Tests: onboarding API flow, merge, speech endpoint (41 pass).

**Changed**
- **Layout and size:** base text 17 px (was 15); check-in page uses the full width (latest line scales
  to 54 px, 80 px button, larger camera preview and analysis column); dashboard is two columns on wide
  screens (main: summary, chart, check-ins; side: reminders, wellbeing, memories) up to 1760 px; setup
  page wider with 46 px fields; larger chart (380 px), labels and table text.
- **Server listens on IPv4 and IPv6** (`run_server.py`, dual-stack socket). On Windows `localhost`
  resolves to ::1 first, so with an IPv4-only server every new connection waited ~2 s. This also
  inflated earlier latency measurements by ~2 s per request.
- Onboarding extraction uses `gpt-oss-20b` at low effort (`ONBOARDING_MODEL`): ~1 s and as accurate as
  120b on single answers (120b took 1-9 s).

**Fixed**
- Groq rejected an extraction because the model wrote `null` for an empty list (`json_validate_failed`),
  losing the whole answer (two people). `llm.complete_json` now recovers the generated JSON from the
  error, schemas allow null lists, and callers tolerate nulls (memory step too).
- Onboarding stored relation "unknown" and "city" from where they grew up; prompts and merge fixed.

---

## 2026-10-19: Personal companion (setup, memory, reminders, suggestions) + personal baseline

Feedback: the companion felt generic ("only offering help or asking how my day was"); it should
learn about the person and the people in their life, cheer them up, remind them of daily tasks
and suggest activities, with an onboarding setup. Also: test a personal baseline and integrate
it if it works; put the silence cut-off back to the default.

**Added**
- **Setup page** (`clients/web/setup.html`, `js/setup.js`, `GET/PUT /api/profile`): who they are, how to
  address them, pronouns, story, people in their life (with birthdays), routine, interests, cheer-up
  ideas, activities, health notes, topics to handle gently, reminders, companion name, voice (with a
  sample button, `POST /api/voices/preview`), personality (warm / cheerful / calm), family contact.
- **`server/app/companion/`**: `profile.py` (profile → LLM prompt text), `memory.py` (background
  extraction with `gpt-oss-120b` strict JSON: memories, reminders done, wellbeing signals, summary;
  recall before each check-in), `reminders.py` (daily / weekday / once schedules, done/due/soon/later,
  spoken times like "5:30 pm"), `plan.py` (per-turn aims + greeting hook).
- **Personalised conversation**: system prompt rebuilt each reply from profile + memories + time;
  personal greeting; replies follow up on memories, check due reminders, suggest one activity
  (cheer-up ideas when low), close by mentioning what's coming up later.
- **Personal baseline** (`analysis/baseline.py`): low line relative to the person's own normal after 5
  check-ins. Evaluated with `scripts/evaluate_baseline.py` (synthetic, 300 people per profile):

  | Drop | Profile | Fixed: false alerts / alerted | Baseline: false alerts / alerted |
  |---|---|---|---|
  | 0.15 | expressive | 0% / 0% | 0% / 6% |
  | 0.15 | flat | 0% / 38% | 3% / 88% |
  | 0.15 | reads sad | 100% / 100% | 10% / 79% |
  | 0.25 | expressive | 0% / 0% | 0% / 63% |
  | 0.25 | flat | 0% / 100% | 3% / 99% |
  | 0.25 | reads sad | 100% / 100% | 10% / 96% |
  | 0.35 | expressive | 0% / 9% | 0% / 96% |
  | 0.35 | flat | 0% / 100% | 3% / 100% |
  | 0.35 | reads sad | 100% / 100% | 10% / 100% |

  It works, so it's integrated and on by default (`BASELINE_ENABLED`).
- **Dashboard**: today's reminders (mark done, add, remove), wellbeing mentions over 7 days (poor
  sleep, poor appetite, pain, loneliness, no contact), which low line is in use, and "What <companion>
  has learned" with Remove per memory. Setup link in the nav on every page.
- **DB**: tables `profile`, `reminders`, `reminder_log`, `memories`; columns `sessions.summary`,
  `sessions.signals_json` (added to existing databases automatically via `db.MIGRATIONS`).
- **API**: `/api/reminders` (GET/POST), `/api/reminders/{id}` (DELETE), `/api/reminders/{id}/done`,
  `/api/memories` (GET), `/api/memories/{id}` (DELETE); health/dashboard/session responses gained fields.
- `seed_demo.py` also creates a sample profile (only if none exists), wellbeing signals and 3 demo memories.
- Tests: `test_companion.py` (baseline, reminders, profile, plan, memory extraction, greeting hook,
  spoken times) and API tests for profile/reminders/memories; 38 pass.

**Changed**
- Check-ins have 4 answers (was 3) to make room for follow-up, reminder and suggestion.
- Alert messages use the person's name and pronouns ("she's fine").
- Silence cut-off back to 1.8 s (was 2.6 s); other listening fixes kept.

**Fixed (found in live end-to-end runs on a scratch database)**
- Greeting invented events from profile interests ("your roses looked lovely yesterday"): the server
  now picks the hook from real memories (today/yesterday/tomorrow events, birthdays within 2 days) or none.
- Replies switched to Tamil when the profile listed Tamil: replies are now forced to English.
- Reply misattributed who called whom: stricter faithfulness rules ("who did what"; one idea per reply).
- Memory step stored a companion suggestion as a fact about the person; now told to use only what the
  person said and to skip profile facts.

---

## 2026-10-19: Natural voice, better listening and speech recognition

Feedback: the companion's voice was "slow and robotic", and it often misheard what was said.
Real check-ins in the DB showed answers cut off mid-thought ("Yeah, but…", "I") and misheard
words ("never was at me" for "never visit me", "I hate channel Samasa" for "I ate chana samosa").

**Changed**
- **TTS:** default is now `edge-tts` with Microsoft's `en-IN-NeerjaNeural` voice (natural Indian
  English, free, no key, ~1.4 s per reply). Provider chain in `dialogue/tts.py`: configured provider,
  then edge, then gTTS; the browser voice is the final fallback. Groq **Orpheus** is supported
  (`TTS_PROVIDER=orpheus`) but needs a one-time terms acceptance in the Groq console. Replies over
  200 characters are split by sentence and the WAVs joined. Audio endpoint serves `.wav` or `.mp3`.
- **STT:** `whisper-large-v3` instead of `-turbo`, `temperature=0`. On 8 noisy, quiet, band-limited
  Indian-English clips: turbo 15.7% word errors, large-v3 11.4%. Clean clips: both 100% correct.
- **No Whisper prompt** (tried and rejected): a descriptive context prompt made Whisper invent text
  ("Lakshmi replied, …") and raised word errors to 18.6%; prompting with just the last question
  gave no gain (11.4%).
- **Listening (`clients/web/js/vad.js`, new):** the old detector learned the noise floor from the
  first 300 ms, so speaking immediately set the threshold above the voice (speech never detected).
  It also stopped after 1.8 s of silence, cutting off thinking pauses. New: adaptive noise floor (drops
  instantly, rises slowly), ≥250 ms of sound before it counts as speech, stops after 2.6 s of silence,
  30 s cap. Simulated tests in `vad.test.mjs` (7 scenarios); the old logic fails the
  "speaks immediately" and "2 s pause" scenarios.
- **Recording:** browser noise suppression and echo cancellation off (they clip word onsets; the
  companion never speaks while recording), auto-gain on, 128 kbps Opus.
- Silence-hallucination filter ("you", "thank you", …) now applies only to quiet clips, so real short
  answers like "Okay" or "Thank you" are kept.
- Browser fallback voice rate 0.95 → 1.0.

**Added**
- `edge-tts` dependency; config `TTS_PROVIDER`, `TTS_EDGE_VOICE`, `TTS_EDGE_RATE`, `TTS_ORPHEUS_VOICE`.
- `tests/test_dialogue.py` (hallucination filter, TTS text splitting), `clients/web/js/vad.test.mjs`.

---

## 2026-10-19: Frontend redesign: professional and minimal

Feedback: the first UI "looked AI-generated". Redesigned from current references (Vercel Geist,
Linear, minimal UI-craft guidance, articles on AI-design tells). Rules are recorded in ARCHITECTURE §12.

**Changed**
- `clients/web/css/style.css` rewritten: monochrome UI with near-black as the only action colour;
  1px hairlines instead of boxed cards and shadows; radii 6–8px; Geist + Geist Mono (Google Fonts,
  system-font fallback); colour reserved for chart series and status dots.
- Check-in page: transcript as large captions (latest line 34px, earlier lines faded) instead of
  chat bubbles; rectangular primary button instead of the pulsing circle; 5-bar level meter;
  analysis column restyled as a key/value readout with mono numbers; "Hide/Show analysis" text toggle.
- Dashboard: summary sentence as the focal point, 4-figure stats row, chart with a softer gap band
  and per-day status dots, check-ins as an expandable table.
- Status shown as dot + word everywhere (`common.status()`), replacing pill badges and emoji-like icons.

**Removed**
- Pills, tinted alert boxes, circular icon badges, ✓/◆/!! glyphs, the teal accent colour.

---

## 2026-10-19: Restart as the "I'm fine" masked-mood companion (laptop version)

Professor's feedback from the last review: identify **one core problem** for older adults related
to emotion detection, solve it, and include hardware (Raspberry Pi). Chosen problem: older adults
hide low mood ("I'm fine"). The project was rebuilt around detecting that gap. Laptop-first,
with Pi integration designed in but not built yet.

**Added**
- New server structure under `server/app/`: `config.py` (all thresholds), `services/checkin.py`
  (device-agnostic pipeline), `models/` (voice, face, text plus background warm-up registry),
  `analysis/` (audio, fusion, masking, trends, safety), `dialogue/` (stt, llm, tts), `storage/db.py`.
- **Masking detection**: verbal valence (RoBERTa sentiment + reassurance phrases) vs non-verbal
  valence (voice + face fusion); one rule (ok / low / masked) applied per answer, session and day.
- **Family alerts** over a 7-day window (ok / watch / alert / urgent / none), including missed
  check-ins and a self-harm keyword screen → urgent.
- Session-based API: `POST /api/sessions`, `POST /api/sessions/{id}/turns`, `.../end`,
  `GET /api/dashboard`, `GET /api/health`, `GET /api/audio/{name}`.
- Companion replies guided by the analysis (masked → make room gently; low → acknowledge;
  last turn → close warmly).
- Browser client `clients/web/`: elder-friendly check-in page (auto-stop on silence, 3 camera
  frames per answer, analysis panel) and family dashboard (alert card, 14-day said-vs-seemed
  SVG chart with hover and table view, conversation history). Light and dark themes.
- `run_server.py --https` with an auto-generated self-signed cert, so a phone browser can be the device.
- `scripts/seed_demo.py` (synthetic 14-day scenarios, flagged `is_demo`), `scripts/smoke_test.py`
  (real end-to-end run; doubles as reference device client).
- Tests: masking, fusion, trends, API flow with stubbed models (23 tests).
- Fixtures: `face_astronaut.jpg` (NASA portrait, public domain, via scikit-image sample data).
- YuNet face detector model `server/app/models/assets/face_detection_yunet_2023mar.onnx`.
- Docs: `CLAUDE.md`, `docs/PROJECT_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/SETUP.md`, this file.

**Changed**
- Voice model now runs **in-process** via `autrainer.serving.Inference` (loaded once): ~0.3 s per
  answer instead of ~36 s with the per-request CLI subprocess.
- Face detection: YuNet instead of MediaPipe (old API gone in MediaPipe 1.x, so cropping never
  actually ran in the old code) or Haar (removed in OpenCV 5). Face reading averaged over several frames.
- Fusion weights = quality × confidence; removed the 2.5× "salience boost" for non-Neutral labels.
- Responses are JSON with an audio URL (old API returned MP3 with `X-*` headers).
- SQLite DB moved to `server/data/companion.db` with new `sessions` / `turns` schema.
- `requirements.txt` trimmed: added `opencv-python-headless`, `cryptography`, `httpx`; removed
  `mediapipe`, `scikit-learn`, `pandas`, `librosa`, `scipy`, `pytest-asyncio`.
- `test_face.jpg` renamed `noise_no_face.jpg` (it is random noise, not a face).

**Removed** (all recoverable from tag `v0-legacy`)
- `android-app/`, `watch-app/`, `dashboard/`, `wokwi/`, `design.md`, `package.json`.
- Old server modules: `voice_emotion/`, `face_emotion/`, `physio_emotion/` (WESAD RandomForest),
  `fusion/`, `storage/mood_log.py`, `storage/conversation.py`, `tts/`, old `main.py`, `scripts/train_wesad.py`,
  old tests, `dummy.jpg`, `test.webm`.
- Old docs: `NEXT_SESSION_PROMPT.md`, `TEAMMATE_HANDOFF.md`, `IMPLEMENTATION_NOTES.md`,
  `VOICE_LOOP_PLAN.md`, `WATCH_SETUP_GUIDE.md`, `CLAUDE_CODE_SETUP_PROMPT.md`, old `SETUP.md`, old `README.md`.
- Local-only files that were never in git moved to `archive/` (gitignored): trained
  `rf_model.pkl` (physio model), old `mood_log.db`, old test outputs, Android build caches.

**Fixed**
- Whisper "hearing" words like "you" on silence/noise: those transcripts are now treated as no speech.
- Removed the duplicate `opencv-contrib-python` install (pulled in by MediaPipe) that broke `cv2`.

**Commits:** `8c50e07` archived the uncommitted physio WIP before the restart (tagged `v0-legacy`).
The restart and every 2026-10-19 entry above were committed together in one commit ("Restart as the I'm Fine companion", see `git log`).

---

## Pre-restart history (tag `v0-legacy`, 2026-09-11 → 2026-09-16)

Restore anything with `git checkout v0-legacy -- <path>` (e.g. `-- android-app`).

| Date | Commit | What |
|---|---|---|
| 2026-09-11 | `9b892b7`, `bac6187` | Scaffold: Tizen native C++ watch app (Galaxy Watch Active2) + FastAPI voice-emotion server (autrainer CLI, Groq LLM, gTTS) |
| 2026-09-15 | `75985a7` | Pivot client to an Android (Kotlin) phone app: Samsung stopped issuing Tizen wearable certificates, so custom apps can't be installed on the watch |
| 2026-09-15 | `65a018e` | Multi-turn conversation (Groq Whisper + SQLite history), chat UI, voice+face confidence-weighted fusion; ffmpeg decoding fix |
| 2026-09-16 | `8bae5ac` | (Sandhyaa Sriram) Laptop + Wokwi ESP32 POC: WESAD physio RandomForest, web dashboard, salience-weighted 3-way fusion, HR/SpO2/fall triggers |
| 2026-09-16 | `923f30f` | Fix `/checkin` and `/chat` crashes; retry empty gpt-oss completions, `reasoning_effort=low` |
| 2026-10-19 | `8c50e07` | Physio features reduced to `[hr_bpm, acc_mag]` (WIP, archived) |

Lessons carried forward from that phase are in [ARCHITECTURE.md §10](ARCHITECTURE.md#10-technical-decisions-and-gotchas-load-bearing-read-before-changing).
