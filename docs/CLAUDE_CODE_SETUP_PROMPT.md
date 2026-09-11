See `docs/VOICE_LOOP_PLAN.md`, `docs/TEAMMATE_HANDOFF.md`, and `docs/WATCH_SETUP_GUIDE.md` for the full project
brief. Build order followed by this repo:

1. Scaffold repo structure (done).
2. Build and test the server standalone (voice_emotion → dialogue → tts → storage → main.py → run_server.py),
   verified with curl before touching the watch app.
3. Write the watch app native C++ sources (audio_capture, network_client, audio_playback, main) per the API
   spec in `docs/VOICE_LOOP_PLAN.md` §3 — these require Tizen Studio + a physical device to actually build and
   deploy.
4. Physical device setup per `docs/WATCH_SETUP_GUIDE.md`.
5. Verify the pretrained voice emotion model standalone before wiring into `/checkin`.
6. Integration order: server alone → watch connected (sdb) → recording-only → playback-only → dumb end-to-end
   plumbing (fixed test MP3) → real pipeline wired in last.

Constraints: no training step for the voice model (pretrained
`autrainer/msp-podcast-emo-class-big4-w2v2-l-emo` only), TTS is gTTS, server binds `0.0.0.0`, no heart
rate/face/fusion in this build.
