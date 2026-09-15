# Elderly Companion

A closed loop: recording a short voice clip (and, on the Android client, a face photo) sends it over WiFi to
a local Python server, which detects the speaker's emotion from their voice and face (confidence-weighted
fusion of both, when a face reading is available), keeps a running conversation so replies build on what was
actually said instead of reading like a template, converts the reply to speech, and sends the audio back for
the client to play.

Heart rate is still deferred to a later phase and out of scope. Face detection + confidence-weighted fusion
were originally deferred too (the watch has no camera) but have since been implemented now that the active
client is a phone — see the platform note below and `docs/IMPLEMENTATION_NOTES.md` point 11.

**Client platform note (2026-09):** Samsung discontinued the Samsung wearable-certificate creation flow in
Tizen Studio, which blocks sideloading any custom-built app onto the physical watch. For the current course
review, the same closed loop is implemented as an Android phone app instead (`android-app/`) — no certificate
required, just USB debugging. `watch-app/` (the original Tizen native C++ client) is kept as-is for if/when a
watch deployment path reopens. The server is unchanged and shared by both clients.

## Repo layout

- `android-app/` — Android (Kotlin) client: record → POST to server → play response. Current active client.
- `watch-app/` — Tizen Studio native C++ project (recorder, network client, player, UI). On hold — see note
  above.
- `server/` — Python FastAPI backend (voice emotion, dialogue/LLM, TTS, mood log)
- `docs/` — planning and setup docs

## Quick start (server)

```
cd server
pip install -r requirements.txt
python run_server.py
```

`ffmpeg` must also be installed as a **system** dependency and on PATH (not pip-installable) — it's required
to decode the AAC/M4A audio the clients record. See `server/requirements.txt` for install commands per OS.

The server binds to `0.0.0.0:8000` so a phone/watch on the same WiFi network can reach `POST /checkin`.

## Quick start (Android client)

See `android-app/README.md` — open in Android Studio, set `SERVER_URL` to your machine's LAN IP, run on a
phone via USB debugging.

See `docs/` for the full plan, watch device setup guide, integration order, and `docs/IMPLEMENTATION_NOTES.md`
for gotchas found while building (read before touching the emotion model, LLM client, or audio preprocessing).
