# Elderly Companion — Android client

Pivoted here from the Tizen native watch app because Samsung discontinued the Samsung wearable-certificate
creation flow in Tizen Studio (no cert = no way to sideload a custom-built app onto the physical Galaxy Watch
Active2 anymore). This Android app implements the same client-side loop — record → send to server → play the
response — as a normal Android phone app, which only needs USB debugging, not a platform-specific signing
certificate. `watch-app/` is left in place for later; the server (`server/`) is unchanged in spirit, though it
now does more (speech-to-text + real conversation, see below).

## Loop

Tap the mic button → record ~5s via `MediaRecorder` (AAC/M4A) → POST multipart to the server's `/checkin`
(OkHttp) → server transcribes the speech, detects emotion, and replies as part of an ongoing conversation
(not a one-off canned response) → app reads the returned MP3 plus `X-User-Text`/`X-Emotion-Label`/
`X-Emotion-Confidence`/`X-Response-Text` headers → adds a user chat bubble (with a small "sounds a bit down ·
81%" caption) and an assistant chat bubble to the conversation → plays the MP3 via `MediaPlayer` → back to
idle. Any failure (network, server error, playback error) is shown on screen instead of silently doing
nothing. Tap the refresh icon in the top bar to clear the conversation and start fresh (calls the server's
`/reset`).

## UI

Redesigned as a chat interface (previous version was a single card, felt static and "very bad" per direct
feedback) using patterns pulled from current chat-UI design guidance: right-aligned colored bubbles for the
user, left-aligned light bubbles with a small avatar for the assistant, rounded corners, a named companion
persona (avatar icon), and a bottom input bar (here: a big circular mic button instead of a text field, since
this app is voice-only).

- Top app bar: "Companion" title + a reset/new-conversation icon button.
- Scrolling chat history (RecyclerView) with distinct user/assistant bubble styles.
- Bottom bar: circular mic button that changes color/icon per state (idle → blue mic, recording → red stop,
  sending → orange cloud + spinner, speaking → green speaker), a status line, and an error message slot.
- An empty-state prompt ("Tap the microphone below...") shown before the first check-in.

## Before running

1. Edit `SERVER_URL_BASE` in `app/src/main/java/com/example/elderlycompanion/NetworkClient.kt` to your
   laptop's LAN IP (the phone and laptop must be on the same WiFi network — including a phone-hosted hotspot,
   as long as the laptop connects to it and you use the laptop's IP *on that hotspot's subnet*).
2. Make sure `ffmpeg` is installed on the server machine and on PATH — the server needs it to decode the
   AAC/M4A audio this app records (see `server/requirements.txt`'s note and
   `docs/IMPLEMENTATION_NOTES.md` point 6). Without it, every check-in will 500.
3. Start the server (`cd server && ./venv/Scripts/python.exe run_server.py` on Windows) and confirm it prints
   `Uvicorn running on http://0.0.0.0:8000`.

## Running it

1. Open the `android-app/` folder in Android Studio. If it has never had an Android SDK configured, it will
   prompt to install one (Settings → Languages & Frameworks → Android SDK — install SDK Platform 35 and, on
   the SDK Tools tab, Command-line Tools + Build-Tools + Platform-Tools).
2. If the Gradle wrapper download times out (`Could not install Gradle distribution ... Connect timed out`),
   download `gradle-8.7-bin.zip` manually from `services.gradle.org` in a browser and place it in
   `%USERPROFILE%\.gradle\wrapper\dists\gradle-8.7-bin\<hash-folder>\` (the empty hash folder gets created by
   the failed attempt) — then re-sync.
3. Enable Developer Options + USB debugging on the Android phone, connect via USB, accept the debugging
   prompt on the phone.
4. Select the phone in Android Studio's device dropdown and click Run (▶) — builds a debug APK and
   installs/launches it, no certificate needed beyond the phone's own debug-signing key.
5. On first tap, accept the microphone permission prompt.

**Tip for iterating without picking up the phone:** Android Studio's "Running Devices" panel (View → Tool
Windows → Running Devices) mirrors the connected phone's screen inside the IDE and interacts with it directly
— click the `+` in that panel and select the device to start mirroring. It also has a camera-icon button to
save a screenshot straight to the laptop, useful for sharing what's on screen without photographing the phone.

## Status

- The original "records, sends, then nothing happens" symptom was root-caused: the server was silently
  500ing because `ffmpeg` (needed to decode AAC/M4A) wasn't installed, and the app was swallowing errors
  instead of showing them. Both are fixed — see `docs/IMPLEMENTATION_NOTES.md`.
- Confirmed working on a real phone: the emotion+response card version was verified visually via the device
  mirror (correctly showed "You sound [emotion] (81%)" and a real, non-canned reply).
- Since then, upgraded from a one-off "detect emotion → generate one consoling line" flow to a real multi-turn
  conversation: the server now transcribes speech via Groq Whisper and keeps a running conversation history
  (SQLite), so replies build on what was actually said and ask natural follow-up questions instead of reading
  like a template. The UI was rebuilt as a chat interface to match. **This round (conversation + chat UI) is
  built and compiles cleanly (`gradle assembleDebug` succeeds) but not yet re-verified on the physical
  phone** — do that next.
