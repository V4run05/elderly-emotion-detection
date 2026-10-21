# Setup & Run Guide

> **What this file is:** everything a team member needs to install, run, demo and
> troubleshoot the project. Commands are for **Windows PowerShell** unless marked.
> Update this file whenever a dependency, command, port or setup step changes.

---

## 1. What you need

| Thing | Notes |
|---|---|
| Windows 10/11 laptop with a webcam + microphone | macOS/Linux work too (adjust paths) |
| **Python 3.12, standard python.org build** | Not MSYS2/Cygwin Python: it can't install torch/numpy wheels. Check with `py -0p`. |
| **ffmpeg** on PATH | System program, not pip. Without it every conversation fails. |
| Groq API key (free) | https://console.groq.com → API Keys |
| Internet | Groq (speech-to-text + replies) and edge-tts (the companion's voice) are online services |
| ~5 GB free disk | Python packages (~3 GB) + model weights (~2 GB, downloaded on first start) |
| Chrome or Edge | For the conversation page (Firefox works; Safari/iOS untested) |

## 2. First-time setup

```powershell
# 1. ffmpeg (once per machine), then open a NEW terminal so PATH updates
winget install --id Gyan.FFmpeg -e
ffmpeg -version

# 2. Python environment (from the repo root)
cd server
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Secrets / settings
copy .env.example .env
notepad .env        # paste your GROQ_API_KEY; optionally change ELDER_NAME / COMPANION_NAME
```

> Tip: you can activate the venv with `.\venv\Scripts\Activate.ps1` and then just type
> `python ...`. If PowerShell blocks the script, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or keep using
> `.\venv\Scripts\python.exe` directly as shown here.

## 3. Run it

```powershell
cd server
.\venv\Scripts\python.exe run_server.py
```

- Talk page: **http://localhost:8000**
- Family dashboard: **http://localhost:8000/dashboard**
- Profile setup: **http://localhost:8000/setup**

**First time:** either press **Get to know each other** on the talk page (Asha asks the questions
out loud and fills in the profile, about 5 minutes), or open the setup page and fill in the profile together with the person (name, people
in their life, routine, interests, what cheers them up, medicines as reminders, companion name,
voice and personality). Press **Save profile**. The talk page offers this until a profile exists.

The first start downloads model weights (several minutes). Every start then takes ~30–60 s to
load models; the page shows "Getting ready…" until then. Allow camera and microphone when the
browser asks. Stop the server with `Ctrl+C`.

Options: `--port 9000`, `--reload` (auto-restart on code edits), `--https` (see §5).

## 4. Demo data

The dashboard needs days of history to show a trend. Seed clearly labelled synthetic data:

```powershell
.\venv\Scripts\python.exe scripts\seed_demo.py                 # masked scenario (default)
.\venv\Scripts\python.exe scripts\seed_demo.py --scenario healthy
.\venv\Scripts\python.exe scripts\seed_demo.py --scenario open  # openly low
.\venv\Scripts\python.exe scripts\seed_demo.py --clear          # remove demo data only
.\venv\Scripts\python.exe scripts\seed_demo.py --clear-all      # remove EVERYTHING (real conversations too)
```

Seeding leaves today empty so a live conversation shows up as today's point. If no profile exists yet,
it also creates a sample one (Lakshmi, granddaughter Priya, two reminders) and six demo memories.
In the masked scenario, yesterday is a full scripted conversation (`SHOWCASE` in the script): she says "I'm fine",
opens up, and Asha brings back good things (her roses, Priya's exams, tea with Kamala), checks her BP tablet and
suggests a plan. It's the top row of the dashboard's conversation table. For a clean demo run `--clear-all` first
(it also removes real test conversations and memories), then seed.
An existing profile is never overwritten. `--clear` removes demo conversations and demo memories. The demo script for
reviews is in [PROJECT_SPEC.md §11](PROJECT_SPEC.md#11-evaluation-and-demo-plan).

## 5. Use a phone as the device (camera, mic, speaker)

Phone browsers only allow the camera and mic on `https://` pages, so run:

```powershell
.\venv\Scripts\python.exe run_server.py --https
```

1. The terminal prints the phone URL, e.g. `https://192.168.1.4:8443`. Phone and laptop must
   be on the **same Wi-Fi** (a phone hotspot with the laptop connected also works).
2. Open it on the phone. You'll see a "not secure / not private" warning because the
   certificate is self-signed. Tap **Advanced → Proceed**. This is expected on a local network.
3. Allow camera and microphone.
4. If the page won't load: allow Python through **Windows Firewall** for private networks
   (Windows usually asks the first time), and check the IP with `ipconfig`.

The certificate is created automatically in `server/data/certs/` (one per laptop IP).

## 5b. Optional: Groq Orpheus voice

Orpheus is an expressive voice model on Groq (American English voices). It uses your existing key
but needs a one-time terms acceptance by the Groq org admin:

1. Open https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english and accept the terms.
2. In `server/.env` set `TTS_PROVIDER=orpheus` (optionally `TTS_ORPHEUS_VOICE=diana`).
3. Restart the server. If Orpheus fails, it automatically falls back to edge-tts.

## 6. Tests

```powershell
cd server
.\venv\Scripts\python.exe -m pytest                       # fast, offline, models stubbed
node ..\clients\web\js\vad.test.mjs                       # end-of-answer detection scenarios (needs Node.js)
.\venv\Scripts\python.exe scripts\evaluate_baseline.py    # personal baseline vs fixed line (simulation)
.\venv\Scripts\python.exe scripts\smoke_test.py           # needs the server running; real models + Groq
.\venv\Scripts\python.exe scripts\smoke_test.py --audio C:\path\to\my_answer.m4a --image C:\path\to\me.jpg
```

Evaluation on real data (datasets download, ~1 h total) is in [EVALUATION.md](EVALUATION.md) §10.

New settings since the evaluation (all optional, defaults in `server/.env.example`): `LLM_BACKUP_MODELS`,
`LLM_HEDGE_DELAY_S`, `SAFETY_SCREEN_MODEL`, `SAFETY_SCREEN_FALLBACKS`, `HELPLINE_NAME`, `HELPLINE_NUMBER`,
`BASELINE_COMBINE`, `MIN_READING_SECONDS`. The self-harm screen uses Groq's `openai/gpt-oss-safeguard-20b`
(same key; no extra setup).

The smoke test stores a real conversation; remove it with `seed_demo.py --clear-all` if needed.
The bundled `test_clip` is a synthetic tone, not speech (the server will say it heard nothing).
Record your own answer for a meaningful run.

## 7. Settings

Edit `server/.env` (restart the server afterwards). Common ones:

| Variable | Default | Meaning |
|---|---|---|
| `GROQ_API_KEY` | – | Required |
| `ELDER_NAME` / `COMPANION_NAME` | Lakshmi / Asha | Fallback names until the setup page is saved |
| `MAX_TURNS_PER_SESSION` | 3 | Answers per conversation |
| `TTS_PROVIDER` | edge | Voice engine: `edge` (natural, free), `orpheus` (Groq, see §5b), `gtts` (robotic) |
| `TTS_EDGE_VOICE` | en-IN-NeerjaNeural | Any edge-tts voice, e.g. `en-IN-NeerjaExpressiveNeural`, `en-IN-PrabhatNeural` (male), `en-US-AvaMultilingualNeural` |
| `TTS_EDGE_RATE` | +0% | Speaking speed, e.g. `+10%` faster, `-10%` slower |
| `TTS_ORPHEUS_VOICE` | hannah | Orpheus voice: autumn, diana, hannah (female); austin, daniel, troy (male) |
| `STT_MODEL` | whisper-large-v3 | Speech-to-text model (`whisper-large-v3-turbo` is faster but less accurate) |
| `KEEP_MEDIA` | false | `true` saves raw audio to `server/data/media/` (for building a test set) |
| `MAX_TURNS_PER_SESSION` | 0 | Message limit per conversation (0 = open-ended) |
| `LLM_MODEL` / `LLM_FAST_MODEL` | gpt-oss-120b / gpt-oss-20b | Reply models, asked at the same time |
| `LLM_PRIMARY_WAIT_S` | 3.0 | How long to wait for the better model before using the fast one |
| `MEMORY_MODEL` | openai/gpt-oss-120b | Model for the background memory step |
| `ONBOARDING_MODEL` | openai/gpt-oss-20b | Model that turns "get to know you" answers into profile fields |
| `BASELINE_ENABLED` | true | Personal baseline on/off |
| `BASELINE_SESSIONS` | 5 | Conversations used to learn the person's normal |
| `SAYS_OK_THRESHOLD`, `LOW_NONVERBAL_THRESHOLD`, `MASKING_GAP_THRESHOLD`, ... | see config | Detection thresholds: see PROJECT_SPEC §6 |

Everything tunable is listed in [server/app/config.py](../server/app/config.py).

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| Page stuck on "Getting ready…" | First run is downloading models; watch the server terminal. Later starts take ~30–60 s. |
| "ffmpeg is not installed or not on PATH" | Install ffmpeg (§2) and open a new terminal. Check with `ffmpeg -version`. |
| "GROQ_API_KEY is missing" | Put the key in `server/.env` (not `.env.example`) and restart. |
| "Speech recognition failed" | No internet, or the Groq key is invalid / rate-limited. |
| "Sorry, I didn't hear anything" every time | Wrong microphone selected in the browser (click the camera/mic icon in the address bar), or speaking too quietly. |
| No face reading ("no face found") | Sit facing the camera, well lit, face filling a reasonable part of the frame. |
| Reply text shows but no voice | All voice services failed (internet?); the page falls back to the browser's voice. Check the speaker volume and the server log (`TTS provider ... failed`). |
| Voice sounds robotic | edge-tts failed and it fell back to gTTS. Check the server log; run `pip install -r requirements.txt` (needs `edge-tts`). |
| Cut off while still talking | It stops after 2.6 s of silence. Press **I'm done** when finished, or raise `silenceMs` in `clients/web/js/vad.js`. |
| Often mishears words | Sit closer to the mic, reduce background noise, or use a headset or phone mic. Check the browser is using the right mic (address-bar mic icon). |
| Phone can't open the page | Same Wi-Fi? Firewall allowed? Using `https://` and port 8443? |
| `module 'cv2' has no attribute ...` | Two OpenCV packages installed. Run `pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless` then `pip install opencv-python-headless`. |
| pip fails building numpy/torch | You're using MSYS2/Cygwin Python. Recreate the venv with `py -3.12`. |
| Companion doesn't know the person | Fill in the setup page (`/setup`) and save. Names from `.env` are only fallbacks. |
| Nothing under "What the companion has learned" | Memories are added after a conversation *finishes* (all answers, or End conversation). Check the server log for `memory:` lines. |
| A memory is wrong or private | Remove it on the dashboard. |
| Everything feels ~2 s slow on `localhost` | Restart with the current `run_server.py` (it listens on IPv4 and IPv6). With `--reload` it's IPv4 only: use http://127.0.0.1:8000. |
| "Get to know you" missed something | Check or edit it on the setup page; run it again any time ("Set up by talking"), it skips what's already filled. |
| Want a clean slate | Stop the server, delete `server/data/companion.db`. |

## 9. Fresh clone checklist (teammates)

1. `git clone git@github.com:V4run05/elderly-emotion-detection.git`
2. Steps in §2 (ffmpeg, venv, `pip install`, `.env` with your own Groq key).
3. §3 to run, §4 to seed demo data.
4. `server/.env`, `server/venv/` and `server/data/` are gitignored: never commit them.
