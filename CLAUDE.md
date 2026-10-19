# CLAUDE.md: start here

Context for every new Claude Code session on this repo. Read this, then the doc that matches the task.

## What this project is

**"I'm Fine"**, a Cognitive Robotics course project. A voice companion for older adults living
alone: an open conversation about anything, any time, personalised from a profile and memory.
Underneath, it compares **what they say** (speech → text → sentiment + reassurance phrases) with
**how they seem** (voice-emotion + face-emotion models); once a day it asks "how are you feeling?".
Saying "I'm fine" while seeming low is flagged as **masked**; a pattern over days alerts family
on a dashboard. Hardware requirement: a **Raspberry Pi** (integration is the next phase).

**Current state (2026-10-19):** laptop version complete and verified end to end:
- talk page: open conversation by voice or typing, words shown as they're spoken, "Let me talk"
  interrupt, camera preview hidden by default
- companion: profile from the setup page or a spoken "get to know you", memory, reminders, support
  only when needed, the daily "how are you feeling?" once a day
- analysis: masking check, personal baseline per channel (voice decides), family dashboard with alerts
- safety: keyword + LLM self-harm screen with fixed safe replies; LLM fallback chain with an honest message
- demo data and tests (76 pytest + 7 VAD scenarios)
- evaluation on real data (CREMA-D voices, UTKFace faces, simulated conversations) and the fixes it led to,
  re-tested: see [docs/EVALUATION.md](docs/EVALUATION.md) §0 and §11

Next: re-run the conversation simulation on the production models when the Groq budget allows, test with
real voices and faces (no older adults available yet), try a phone as the device, then the
Raspberry Pi integration. Check the top of [docs/CHANGELOG.md](docs/CHANGELOG.md) for the latest.

## Where to look

| You need… | Read |
|---|---|
| The problem, method, thresholds, alert rules, hardware plan, open questions | [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) |
| Code structure, data flow, API, DB schema, models, Pi integration path, **gotchas** | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| How to install, run, demo, test, troubleshoot | [docs/SETUP.md](docs/SETUP.md) |
| What changed recently / how to restore old code | [docs/CHANGELOG.md](docs/CHANGELOG.md) |
| Test results on real data, what works, what to fix | [docs/EVALUATION.md](docs/EVALUATION.md) |

## Repo map (short)

```
server/app/config.py            every setting and threshold
server/app/services/conversation.py  the pipeline (device-agnostic)
server/app/models/              voice / face / text models (loaded once, background warm-up)
server/app/analysis/            fusion, masking rule, personal baseline, trends + alerts, safety (pure functions)
server/app/companion/           profile (setup), onboarding (spoken setup), memory, reminders, support + hints (plan.py)
server/app/dialogue/            Groq Whisper, Groq LLM, edge-tts voice (with fallbacks)
server/app/main.py              FastAPI API + serves clients/web
clients/web/                    talk page, family dashboard, setup page (plain HTML/JS, no build)
server/scripts/                 seed_demo.py, smoke_test.py (reference device client), evaluate_baseline.py
server/tests/                   pytest (models stubbed)
server/evaluation/              evaluation scripts + results (datasets gitignored), see docs/EVALUATION.md
```

## Commands (Windows, from `server/`)

```powershell
.\venv\Scripts\python.exe run_server.py            # http://localhost:8000  (+ /dashboard)
.\venv\Scripts\python.exe run_server.py --https    # phone access, https://<LAN-IP>:8443
.\venv\Scripts\python.exe -m pytest                # fast, offline
node ..\clients\web\js\vad.test.mjs                # listening/VAD scenarios
.\venv\Scripts\python.exe scripts\smoke_test.py    # real models; server must be running
.\venv\Scripts\python.exe scripts\seed_demo.py     # demo history (--clear / --clear-all)
```

## Rules for working here

1. **Keep the 4 docs current** (plus EVALUATION.md when tests are re-run). After any significant change, update them in the same session:
   - **CHANGELOG.md**: every change, newest first (Added/Changed/Removed/Fixed + commit hash).
   - **ARCHITECTURE.md**: files moved/added, API or schema changed, a technical decision or gotcha found.
   - **PROJECT_SPEC.md**: scope, method, thresholds, alert rules, hardware plan or open questions changed.
   - **SETUP.md**: dependencies, commands, ports, env vars or setup steps changed.
   - **This file**: the "Current state" line, and the repo map if the layout changed.
2. **Keep it Pi-ready.** Analysis stays on the server (`services/`, `analysis/`). Clients only call
   the API. Don't rename or remove API fields (add new ones instead). Device-specific code goes in `clients/<device>/`.
3. **Thresholds and settings live only in `config.py`** (env-overridable), documented in PROJECT_SPEC §6.
4. **Don't relitigate settled choices without new evidence** (reasons in ARCHITECTURE §10):
   autrainer voice model run in-process; RoBERTa *sentiment* (not 7-class emotion) for words;
   YuNet face detection; quality×confidence fusion with no salience boost; Groq gpt-oss-120b
   hedged with 20b (20b only asked after 1.5 s, 120b preferred up to 3 s), then backup qwen3.8-27b, models on
   cooldown while rate-limited, an honest "having trouble" reply if none answers; `max_tokens=400`,
   `reasoning_effort=low`, `tool_use_failed` retry; Whisper large-v3 with
   **no prompt** (a prompt made it invent text); edge-tts Neerja voice (gTTS fallback); ffmpeg decoding;
   end-of-answer detection in `clients/web/js/vad.js` (tested by `vad.test.mjs`); personal baseline
   per channel with the voice deciding, 7 calibration conversations, fixed line −0.55 before that, readings
   need ≥ 0.4 s of speech (all measured, EVALUATION.md); self-harm screen = keywords + gpt-oss-safeguard-20b
   with a fixed safety reply (never LLM-improvised); sensitive-topic names hidden from the LLM until the
   person brings them up; memory extraction with gpt-oss-120b + strict JSON; the
   server (not the LLM) picks the greeting hook; replies forced to English; emotional support only
   when `plan.support` says so (never from single-message readings); `llm.tidy()` strips dashes/markdown.
5. **Run `pytest` after changes**; run `smoke_test.py` when touching models, dialogue or the pipeline.
6. **Never commit** `server/.env`, `server/venv/`, `server/data/`, or `archive/`.
7. **Ethics:** the system says "seemed low", never diagnoses; no raw media stored by default.
8. **Frontend style is deliberate** (minimal, monochrome, hairlines, Geist, status = dot + word).
   Follow ARCHITECTURE §12; the user rejected the earlier generic "AI-looking" UI.

## Environment notes (this machine)

- Windows 11; use **PowerShell or Git Bash**. Python = `server\venv` built from the standard
  Windows Python 3.12 (`C:\Users\varun\AppData\Local\Programs\Python\Python312`). MSYS2 Python is not compatible.
- ffmpeg is on PATH. Model weights are cached in `%USERPROFILE%\.cache` (torch hub + Hugging Face).
- `gh` CLI is not installed. Git remote: `git@github.com:V4run05/elderly-emotion-detection.git` (branch `main`).
- Teammate: Sandhyaa Sriram also commits to this repo. Check `git log` before large edits.
- Pre-restart prototype (Tizen watch, Android app, Wokwi/WESAD physio) is tagged `v0-legacy`.
