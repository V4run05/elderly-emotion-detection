# Elderly Companion Watch

A closed loop: a Samsung Galaxy Watch Active2 (Tizen OS) records a short voice clip on a button tap, sends it
over WiFi to a local Python server, which detects the speaker's emotion from their voice, generates an
empathetic LLM response conditioned on that emotion, converts the response to speech, and sends the audio back
for the watch to play through its own speaker.

Heart rate, face detection, and multimodal fusion are deferred to a later phase and are out of scope for this
build.

## Repo layout

- `watch-app/` — Tizen Studio native C++ project (recorder, network client, player, UI)
- `server/` — Python FastAPI backend (voice emotion, dialogue/LLM, TTS, mood log)
- `docs/` — planning and setup docs

## Quick start (server)

```
cd server
pip install -r requirements.txt
python run_server.py
```

The server binds to `0.0.0.0:8000` so a watch on the same WiFi network can reach `POST /checkin`.

See `docs/` for the full plan, watch device setup guide, and integration order.
