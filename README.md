# Asha: detecting hidden low mood in older adults

Older adults often answer "How are you?" with "I'm fine" even when they aren't. Asha is a voice
companion they can talk to about anything. Underneath, it compares **what someone says** (speech to
text, sentiment, reassurance phrases like "I'm fine") with **how they seem** (voice tone and facial
expression). Saying "I'm fine" while seeming low is flagged as *masked*, and a pattern of it over
several days alerts family on a dashboard.

Cognitive Robotics course project. The laptop version runs today; Raspberry Pi integration is next.

## What to install

| Software | Version | Notes |
|---|---|---|
| Python | 3.12, standard [python.org](https://www.python.org/downloads/) build | Not MSYS2/Cygwin Python (it can't install torch). Check with `py -0p`. |
| ffmpeg | any recent | Decodes the recorded audio. Windows: `winget install --id Gyan.FFmpeg -e`; macOS: `brew install ffmpeg`; Linux: `sudo apt install ffmpeg` |
| Git | any | To clone the repository |
| Chrome or Edge | current | For the talk page and dashboard (Firefox works too) |
| Groq API key | free | [console.groq.com](https://console.groq.com) → API Keys. Used for speech to text and replies. |

You also need a laptop with a webcam and microphone, an internet connection, and about 5 GB of free
disk space (Python packages plus model weights, which download automatically on the first start).
No GPU needed.

## Install (first time)

Windows PowerShell:

```powershell
git clone https://github.com/V4run05/elderly-emotion-detection.git
cd elderly-emotion-detection\server
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
notepad .env          # paste your key: GROQ_API_KEY=...
```

macOS / Linux:

```bash
git clone https://github.com/V4run05/elderly-emotion-detection.git
cd elderly-emotion-detection/server
python3.12 -m venv venv
venv/bin/python -m pip install -r requirements.txt
cp .env.example .env  # then edit .env and set GROQ_API_KEY
```

## Run

```powershell
cd server
.\venv\Scripts\python.exe run_server.py      # macOS/Linux: venv/bin/python run_server.py
```

| Page | Address |
|---|---|
| Talk page (the conversation) | http://localhost:8000 |
| Family dashboard | http://localhost:8000/dashboard |
| Profile setup | http://localhost:8000/setup |

The first start downloads the models (several minutes); later starts take 30 to 60 seconds, and the
page shows "Getting ready…" until then. Allow the camera and microphone when the browser asks. Stop
the server with `Ctrl+C`.

## First use

1. Create the profile: press **Get to know each other** on the talk page (Asha asks the questions out
   loud), or fill in the form at `/setup` and press **Save profile**.
2. Press **Start talking** and answer out loud, or type in the box. Asha replies by voice.
3. Press **End conversation** when done, then open `/dashboard` to see the family view.

To see the dashboard with two weeks of history, add the built-in demo data:

```powershell
.\venv\Scripts\python.exe scripts\seed_demo.py          # demo history (--clear removes it)
```

To use a phone as the device (same Wi-Fi), run `run_server.py --https` and open the
`https://<laptop-IP>:8443` address it prints.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest           # offline, a few seconds
node ..\clients\web\js\vad.test.mjs           # listening scenarios (needs Node.js)
```

## More

- Full setup, settings and troubleshooting: [docs/SETUP.md](docs/SETUP.md)
- What and why: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md)
- How it's built: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Test results on real data: [docs/EVALUATION.md](docs/EVALUATION.md)
- What changed: [docs/CHANGELOG.md](docs/CHANGELOG.md)
