# Implementation notes (deviations from the original plan docs)

These were discovered while actually building and testing the server — kept here so nobody re-guesses them.

1. **Voice emotion model loading:** the model card's only documented, working interface is the `autrainer`
   pip package's CLI (`autrainer inference hf:<model_id> <data-root> <output-root>`), not
   `transformers.AutoModelForAudioClassification`. The HF repo only contains autrainer's own YAML configs and
   a `_best/` checkpoint dir, no `config.json`/`pytorch_model.bin`. `server/app/voice_emotion/model.py` shells
   out to this CLI per request.
2. **CLI output schema** (`results.csv`): `filename,prediction,output,A,H,N,S` — A/H/N/S are per-class
   probabilities (single-letter codes), `prediction` is the winning code. Mapped to full names in `model.py`.
3. **LLM provider: Groq** (`console.groq.com`, free tier), model `openai/gpt-oss-20b`. Its responses spend a
   large chunk of `max_tokens` on hidden reasoning tokens — use `max_tokens=400` even for a short reply, or the
   visible text gets cut off mid-sentence.
4. **Server `.env`:** `GROQ_API_KEY` lives in `server/.env` (gitignored) and is loaded via `python-dotenv` in
   `run_server.py`. Copy `server/.env.example` and fill in your own key if setting this up fresh.
5. **Python environment:** use a standard python.org/Windows Python install for the server venv, not MSYS2's
   `ucrt64` Python — the latter isn't ABI-compatible with prebuilt PyPI wheels (numpy/torch fail to build from
   source there).
6. **`ffmpeg` is a required SYSTEM dependency, not a pip package.** The Android app (and the original Tizen
   plan) record audio as AAC/M4A, but the installed `librosa` version's only backend is `soundfile`
   (libsndfile), which cannot decode AAC/M4A at all and raises `LibsndfileError: Format not recognised.` — the
   old audioread-based fallback that used to shell out to ffmpeg internally is gone. Confirmed by testing a
   real AAC/M4A clip end-to-end: it failed until `ffmpeg` was installed system-wide (`winget install --id
   Gyan.FFmpeg -e` on Windows) and `app/voice_emotion/preprocess.py` was rewritten to explicitly transcode any
   input file to a 16kHz mono WAV via `ffmpeg` before handing it to `soundfile`. Without `ffmpeg` on PATH,
   every real (non-WAV) check-in silently 500s.
7. **`/checkin` now returns metadata in response headers**, not just the audio: `X-Emotion-Label`,
   `X-Emotion-Confidence`, `X-Response-Text` (the latter two percent-encoded since HTTP headers must be
   ASCII/Latin-1-safe). Added so the client can show what was detected and what the reply says, not just play
   blind audio. `X-Response-Text` must be URL-decoded on the client (see `android-app`'s `NetworkClient.kt`).
8. **Unhandled exceptions in `/checkin` used to bubble up as a bare "Internal Server Error" plain-text 500**
   with no detail sent to the client, which is why the first real Android test ("records audio, sends it, then
   nothing happens") failed silently — the app didn't surface the error either. Fixed on both ends: the server
   now wraps the endpoint in try/except and returns `{"error": "..."}` as JSON on failure, and the Android app
   (`MainActivity.kt`) now shows a visible error message instead of quietly resetting to idle.
9. **Upgraded from one-off emotion→canned-reply to a real multi-turn conversation** (explicit user request:
   "instead of sending one off random consoling texts, make it like a conversation"). Two additions:
   - `app/dialogue/stt_client.py`: transcribes the uploaded audio via Groq's hosted Whisper endpoint
     (`whisper-large-v3-turbo`, same `GROQ_API_KEY`) so the LLM responds to what the person actually said, not
     just their detected emotion. Passes the *original* uploaded audio file directly (Whisper decodes its own
     formats) rather than the ffmpeg-transcoded WAV.
   - `app/storage/conversation.py`: a `conversation_turns` SQLite table (same DB file as `mood_log`), with
     `add_turn`/`get_recent_turns`/`reset_conversation`. `/checkin` now passes the last 10 turns to
     `llm_client.generate_response()`, which threads them into the chat messages sent to Groq so replies
     reference earlier context and ask follow-up questions instead of reading like a template. A new
     `POST /reset` endpoint clears the conversation (wired to a "new conversation" button in the app).
   - `/checkin`'s headers gained `X-User-Text` (the transcription) alongside the existing
     `X-Emotion-Label`/`X-Emotion-Confidence`/`X-Response-Text`.
   - Verified via curl with the same synthetic test clip sent twice in a row: Whisper transcribed the tone as
     a word (expected — it's not real speech), but the *second* reply's wording clearly built on the first
     ("It sounds like you're carrying a lot **today**...") rather than repeating an identical canned response
     — confirming the conversation history is actually being threaded through, not just re-running the same
     one-shot prompt. Real validation (actual spoken content) needs a real voice test on the phone.
10. **UI rebuilt as a chat interface** (explicit feedback: the single-card version "looks very bad"). Pulled
    from current chat-UI design guidance (right-aligned colored user bubbles, left-aligned light assistant
    bubbles with an avatar, rounded corners, named persona) rather than guessing. `android-app`'s
    `ChatAdapter`/`ChatMessage`/`item_message_user.xml`/`item_message_assistant.xml` — see
    `android-app/README.md` for the full UI description. Compiles cleanly (`gradle assembleDebug`) but not yet
    re-verified visually on the phone.
11. **Full facial + voice confidence-weighted fusion added** (explicit user request to reinstate this from the
    original plan's deferred Phase 2 work, now feasible because the client is a phone with a camera, not the
    camera-less watch). Concrete additions:
    - `server/app/face_emotion/model.py`: pretrained `trpakov/vit-face-expression` (ViT, standard
      `transformers` checkpoint — confirmed via its model card, unlike the audio model). Outputs 7 classes
      (Angry, Disgust, Fear, Happy, Sad, Surprise, Neutral); only the 4 overlapping with the voice model's
      taxonomy (Angry→Anger, Happy→Happiness, Sad→Sadness, Neutral→Neutral) are kept, with Disgust/Fear/
      Surprise probability mass dropped and the remaining 4 renormalized to sum to 1. **This is a deliberate
      simplification, not a claim those emotions don't matter** — flagging it here so it isn't mistaken for
      an oversight.
    - `server/app/fusion/fuse.py`: implements the exact formula from the original plan's deferred-work
      section, `w_i = conf_i / sum(conf_j)`, then a per-class weighted average of the two probability
      distributions. Falls back to voice-only (weight 1.0/0.0) when no face reading is available — matches
      the original "face is optional" design intent.
    - `/checkin` now accepts an optional second multipart field, `image`; if present, the face model runs and
      its result is fused with voice before being used for the LLM prompt, mood log, and TTS. Response
      headers gained `X-Voice-Label`/`X-Voice-Confidence` (always present) and `X-Face-Label`/
      `X-Face-Confidence` (present only when a face reading was used) — `X-Emotion-Label`/`X-Emotion-
      Confidence` now carry the *fused* result, not voice-only, so anything reading those two headers keeps
      working unchanged.
    - **Deliberately NOT implemented:** the original novelty framing's "age-bias-corrected" qualifier. There
      was never a concrete, documented bias-correction algorithm in the project's planning docs to implement —
      only the confidence-weighted fusion formula was concrete. Treat age-bias correction as a still-open
      design question if it needs to be part of the final deliverable, not something quietly satisfied by
      this change.
    - Android side: `android-app` now requests `CAMERA` alongside `RECORD_AUDIO` (camera denial degrades
      gracefully to voice-only, doesn't block the app), uses CameraX to show a small front-camera preview
      during the recording window and capture one photo right as recording ends (so the face reflects how
      the person looked while actually speaking), and sends it as the second multipart part. The chat UI's
      per-message caption now shows `(voice+face)` vs `(voice)` so it's visible which signals contributed.
    - Verified: face model smoke-tested standalone (synthetic image, confirms correct shape/renormalization),
      fusion math verified against hand-computed weights, and both the audio-only and audio+image paths of
      `/checkin` tested end-to-end via curl (confirmed `X-Voice-*`/`X-Face-*` headers appear/don't appear
      correctly in each case). Android build compiles clean (`gradle assembleDebug`).
    - **Not yet tested:** a real face photo through the pipeline (only a synthetic noise image so far), and
      the whole camera+mic flow on the physical phone.
12. **`openai/gpt-oss-20b` on Groq intermittently 500s with `tool_use_failed: "Tool choice is none, but
    model called a tool"`** — hit this live on the phone on the *second* real check-in of a conversation.
    Confirmed via web search as a known, reported Groq/gpt-oss bug (multiple independent GitHub issues), not
    caused by anything in this project's prompt — we never pass a `tools` field at all, and the model
    spontaneously emits a spurious tool-call-formatted response anyway. Not consistently reproducible, so
    the fix is to retry: `llm_client._call_llm()` now catches `groq.BadRequestError`, checks for
    `error.code == "tool_use_failed"`, and retries up to 3 attempts before giving up. `generate_response()`
    additionally wraps the whole call in try/except so if the LLM provider is still having a bad moment
    after retries, the check-in degrades to a generic "could you say that again?" fallback response instead
    of 500ing the whole `/checkin` request — the user still gets emotion detection + a spoken reply, just
    not a contextual one that turn.

## Verified so far

- `preprocess.py` + `model.py`: ran standalone on both a synthetic WAV and a real AAC/M4A test clip (the
  format both the Android app and the original Tizen plan actually record), returned a valid
  `{label, confidence, probs}` result each time (Step 5 of the setup plan).
- Full `/checkin` endpoint: POSTed a real M4A file via curl, got back a valid MP3 (verified by MPEG sync
  header bytes `FF F3`) plus the new `X-Emotion-Label`/`X-Emotion-Confidence`/`X-Response-Text` headers, and
  confirmed the SQLite mood log recorded the check-in.
- Android app (`android-app/`): runs on a real phone via USB debugging, records, uploads, and — as of this
  fix — should now play back the response and display the detected mood/reply text instead of silently doing
  nothing. Re-verify on-device after this round of fixes.
- Not yet tested: the physical Tizen watch app itself — on hold, see `docs/NEXT_SESSION_PROMPT.md`'s pivot
  note and `watch-app/`.
