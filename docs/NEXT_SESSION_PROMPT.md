Continue the "Elderly Companion" project at C:\Varun\Projects\Elderly_Emotion_Detection (git repo, pushed to
git@github.com:V4run05/elderly-emotion-detection.git, branch main).

**PLATFORM PIVOT (2026-09-15, read this first):** Samsung discontinued the Samsung wearable-certificate
creation flow in Tizen Studio, blocking sideloading any custom app onto the physical Galaxy Watch Active2. A
community cert-generator tool was tried and has no wearable option; an XDA workaround exists but appears
built for pre-signed watchfaces, not custom app iteration, and its source thread blocks automated fetching to
verify further. Decision: for the current course review, the client is now an **Android phone app**
(`android-app/`, Kotlin) instead of the Tizen watch app. `watch-app/` is kept as-is, on hold, not abandoned.
The server is unchanged. Full rationale in memory ([[android-pivot]] if using this session's memory system) —
check memory before re-litigating this.

## What this project is

An Android phone (originally: a Samsung Galaxy Watch Active2) records a voice clip and, now, a face photo on
check-in → sends both to a local Python FastAPI server → server detects emotion from voice AND face
(confidence-weighted fusion of both when a face reading is available), keeps a running conversation, replies
via LLM in context, converts the reply to speech, sends the audio back → client plays it and shows the
conversation as a chat. Heart rate is still out of scope (Phase 2). Face + fusion were originally deferred too
(the watch has no camera) but **were added 2026-09-15** now that the client is a phone — see "What's next"
below and docs/IMPLEMENTATION_NOTES.md point 11 before assuming they're still out of scope. Full original
background/rationale is in docs/VOICE_LOOP_PLAN.md, docs/TEAMMATE_HANDOFF.md, docs/WATCH_SETUP_GUIDE.md.

## What's already done

**Server (server/) — built AND verified working end-to-end, tested live via curl:**
- `app/voice_emotion/preprocess.py` + `model.py`: pretrained `autrainer/msp-podcast-emo-class-big4-w2v2-l-emo`
  model, run via the `autrainer` CLI (NOT `transformers` — that was a wrong assumption in the original plan,
  corrected after checking the actual HF repo). Verified standalone on a synthetic test clip.
- `app/dialogue/llm_client.py`: Groq API (`console.groq.com`, free tier), model `openai/gpt-oss-20b`,
  `max_tokens=400` (needs headroom for hidden reasoning tokens or replies get cut off).
- `app/tts/synthesize.py`: gTTS. `app/storage/mood_log.py`: SQLite. `app/main.py`: `/checkin` endpoint wiring
  it all together. `run_server.py`: binds 0.0.0.0:8000, loads `server/.env` via python-dotenv.
- Full round trip tested: POSTed a test WAV to `/checkin`, got back a valid MP3, confirmed mood log recorded
  the detection. All correctness gotchas found while building are written up in
  docs/IMPLEMENTATION_NOTES.md — read that before touching model.py or llm_client.py again.
- `server/venv/` (standard Windows Python 3.12, NOT the MSYS2 one — that one can't build numpy/torch wheels)
  and `server/.env` (has the real GROQ_API_KEY) exist locally but are gitignored, so they're NOT in the repo.
  If this is a fresh clone/machine, recreate: `python -m venv venv`, `pip install -r requirements.txt`, copy
  `.env.example` to `.env` and fill in a Groq key.

**Watch app (watch-app/) — source written, NOT build-tested, ON HOLD (see pivot note above):**
- `src/`+`inc/`: audio_capture (Recorder API), audio_playback (Player API), network_client (libcurl multipart
  POST), main.c (UI + state machine: idle→recording→sending→speaking). `tizen-manifest.xml` declares
  recorder+internet privileges. `project_def.prop` lists sources.
- Never opened in Tizen Studio or compiled. Left in place in case a watch deployment path reopens later.

**Android app (android-app/) — built, runs on a real phone, UI redesigned, one round of real bugs fixed:**
- Android Studio SDK/Gradle wrapper setup completed this session (Gradle's own distribution download timed
  out on this network — worked around by manually downloading `gradle-8.7-bin.zip` into the wrapper's dists
  cache folder; see android-app/README.md if this recurs).
- `SERVER_URL` in `NetworkClient.kt` is set to this network's real laptop IP
  (`10.180.225.254` — a phone-hosted hotspot, laptop as client. **Re-check/update this if the network
  changes.**).
- First real on-device test: recorded and sent audio, then "nothing happened" — root-caused as TWO
  compounding bugs, both fixed (details in docs/IMPLEMENTATION_NOTES.md points 6-8):
  1. `ffmpeg` wasn't installed on the server machine, so `librosa`/`soundfile` couldn't decode the AAC/M4A
     audio the app records — every real check-in silently 500'd. Fixed: `ffmpeg` installed via winget,
     `preprocess.py` rewritten to explicitly transcode via ffmpeg before reading. **`ffmpeg` must be on PATH
     on whatever machine runs the server — it's a system dependency, not pip-installable.**
  2. The app silently swallowed all failures (network errors, server errors) and just reset to idle with no
     visible message — impossible to debug from the outside. Fixed: `MainActivity.kt` now shows errors
     on-screen; `main.py`'s `/checkin` now returns JSON `{"error": ...}` on failure instead of a bare 500.
- UI redesigned (round 1) per request ("make it look a bit better and intuitive"): Material Components, a
  circular mic button that changes color/icon by state, plus a result card showing the detected mood +
  confidence and the full LLM reply text. **User confirmed this round worked** via a screenshot (device
  mirrored in Android Studio's "Running Devices" panel), but flagged a phrasing bug ("You sound sadness
  (81%)") — fixed with an emotion→natural-phrase map.
- **Round 2 (same session, latest state): conversation + full UI rebuild**, per explicit follow-up request
  ("make it like a conversation" + "upgrade the UI, it looks very bad, use references from the internet").
  Implemented:
  - `server/app/dialogue/stt_client.py`: transcribes the audio via Groq Whisper (`whisper-large-v3-turbo`)
    so the LLM sees actual spoken words, not just the emotion label.
  - `server/app/storage/conversation.py`: SQLite conversation history threaded into the LLM prompt for real
    multi-turn continuity (asks follow-ups, references earlier turns) instead of one-off canned replies.
    `POST /reset` clears it.
  - `/checkin` gained an `X-User-Text` header (the transcription) alongside the existing three.
  - Android UI rebuilt from a single card into an actual chat interface (`ChatAdapter`/`ChatMessage`,
    RecyclerView, distinct user/assistant bubble layouts with an avatar), following current chat-UI design
    patterns pulled from a web search (not guessed) — see docs/IMPLEMENTATION_NOTES.md point 10 and
    android-app/README.md for the specifics.
  - Verified: server-side conversational continuity via two curl calls in a row (second reply's wording
    referenced the first). Verified: `gradle assembleDebug` succeeds.
- **Round 3 (same session, latest state): full facial + voice confidence-weighted fusion**, per explicit
  follow-up request ("full" fusion, reinstating the original plan's deferred Phase 2 work). Implemented:
  - `server/app/face_emotion/model.py`: pretrained `trpakov/vit-face-expression` (standard `transformers`
    ViT checkpoint), reduced from its native 7 classes to the shared 4-class taxonomy (Angry/Happy/Sad/
    Neutral kept, Disgust/Fear/Surprise mass dropped and the rest renormalized — a deliberate, documented
    simplification, not an oversight).
  - `server/app/fusion/fuse.py`: the original plan's exact formula, `w_i = conf_i / sum(conf_j)`, applied
    per-class. Falls back to voice-only when no face reading exists.
  - `/checkin` now accepts an optional `image` multipart field; `X-Emotion-Label`/`X-Emotion-Confidence` now
    carry the *fused* result (backward-compatible for anything already reading just those two), with new
    `X-Voice-*`/`X-Face-*` headers for the breakdown.
  - Android: added `CAMERA` permission (denial degrades gracefully to voice-only, doesn't block the app),
    CameraX front-camera preview shown during the recording window, one photo captured right as recording
    ends, sent as the second multipart part. Chat bubble captions now show `(voice+face)` vs `(voice)`.
  - **Deliberately NOT implemented:** the original novelty framing's "age-bias-corrected" qualifier — no
    concrete algorithm for that was ever specified anywhere in the planning docs, only the fusion formula
    was concrete. This is a real open question if it needs to be part of the final deliverable, not
    something quietly satisfied by this change — flag it back to the user if it comes up.
  - Verified: face model smoke-tested standalone (synthetic image), fusion math checked against
    hand-computed weights, both audio-only and audio+image `/checkin` paths tested via curl (confirmed
    `X-Voice-*` always present, `X-Face-*` only when an image was sent). `gradle assembleDebug` succeeds
    with CameraX added.
  - **CONFIRMED WORKING ON THE PHONE** (screenshot from the user): a real check-in showed a user bubble
    ("Hi.") with caption "sounds a bit down · 57% (voice+face)" and a natural, non-canned assistant reply —
    real transcription, real fusion, real conversational LLM output, all together on-device.
- **Round 4 (same session): fixed a live bug hit during that on-device test.** The *second* check-in in the
  same conversation returned a 500. Root cause: `openai/gpt-oss-20b` on Groq intermittently emits a spurious
  tool-call-formatted response even though this project never passes a `tools` field — confirmed via web
  search as a known, independently-reported Groq/gpt-oss bug, not something wrong in our prompt. Fixed in
  `llm_client.py`: catches `groq.BadRequestError` with `error.code == "tool_use_failed"` and retries up to 3
  attempts; if it's still failing after that, `generate_response()` degrades to a generic "could you say
  that again?" fallback instead of 500ing the whole `/checkin` request. Verified the normal (non-buggy) path
  still works after the change via curl; the actual retry-on-failure branch can't be forced/verified
  directly since the bug isn't reliably reproducible — reasonable code-review confidence, not empirical
  confirmation of the retry itself.

## What's next

1. **Keep testing the conversation on the phone**, especially multiple check-ins in a row, to see if the
   gpt-oss retry fix holds up against the intermittent Groq bug in practice.
2. Try denying camera permission once to confirm graceful voice-only fallback (caption should say `(voice)`
   with no crash) — not yet explicitly tested.
3. Revisit whether "age-bias-corrected" fusion needs to be modeled explicitly, or whether confidence-weighted
   fusion alone satisfies the review's expectations — this was left an open question, not resolved.
4. If time/scope allows later: revisit the Tizen watch path if a certificate workaround is ever found, using
   the untouched `watch-app/` sources and docs/WATCH_SETUP_GUIDE.md.

## Useful context

- Project memory (decisions, gotchas, why things are the way they are) is saved under this session's memory
  system — check it at conversation start, it has more detail than this file on the reasoning behind each
  choice.
- No training step anywhere in this project — the voice model is pretrained, load-and-infer only.
