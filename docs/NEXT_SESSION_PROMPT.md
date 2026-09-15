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

Samsung Galaxy Watch Active2 (Tizen OS, native C++) records a voice clip on a button tap → sends it to a local
Python FastAPI server → server detects emotion from voice (pretrained model), generates an empathetic LLM
response conditioned on that emotion, converts it to speech, sends the audio back → watch plays it through its
speaker. Heart rate/face/fusion are explicitly out of scope for this build (documented Phase 2, not now). Full
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

**Android app (android-app/) — source written this session, NOT yet run on a device:**
- Kotlin/Gradle project: `MainActivity.kt` (record via `MediaRecorder` ~5s AAC/M4A → send → play response via
  `MediaPlayer`, same idle/recording/sending/speaking state machine as the watch plan had), `NetworkClient.kt`
  (OkHttp multipart POST to `/checkin`).
- **`android-app/app/src/main/java/com/example/elderlycompanion/NetworkClient.kt`'s `SERVER_URL` is a
  placeholder IP (192.168.1.100) — must be edited to the laptop's actual LAN IP before running.**
- No `gradlew`/wrapper jar committed (binary, environment-specific) — Android Studio will generate it on
  first open/sync. Android Studio + its bundled JDK are already installed on this machine; the Android SDK
  itself was NOT yet configured as of this session — Android Studio should prompt to install missing SDK
  components on first project open.
- See android-app/README.md for the full run steps (USB debugging on a real phone — no cert needed, unlike
  Tizen).

## What's next

1. Open `android-app/` in Android Studio, let it configure the SDK/Gradle wrapper, fix `SERVER_URL`.
2. Connect the Android phone via USB debugging, run the app, grant the mic permission on first tap.
3. Confirm the full loop works with the real server (already built and working — see below) on real phone-mic
   audio. This is the first real qualitative check on the pretrained model with real human speech (only
   tested on a synthetic sine-wave clip so far).
4. If time/scope allows later: revisit the Tizen watch path if a certificate workaround is ever found, using
   the untouched `watch-app/` sources and docs/WATCH_SETUP_GUIDE.md.

## Useful context

- Project memory (decisions, gotchas, why things are the way they are) is saved under this session's memory
  system — check it at conversation start, it has more detail than this file on the reasoning behind each
  choice.
- No training step anywhere in this project — the voice model is pretrained, load-and-infer only.
