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

## Verified so far

- `preprocess.py` + `model.py`: ran standalone on a synthetic test clip, returned a valid
  `{label, confidence, probs}` result (Step 5 of the setup plan).
- Full `/checkin` endpoint: POSTed a test WAV via curl, got back a valid MP3 (verified by MPEG sync header
  bytes `FF F3`), and confirmed the SQLite mood log recorded the check-in (Step 2 of the setup plan).
- Not yet tested: real watch-recorded audio (only a synthetic sine-wave clip so far — do this as soon as
  physical device recording works, per the plan's Week 2 risk note), and the physical watch app itself (needs
  Tizen Studio + the device, see `docs/WATCH_SETUP_GUIDE.md`).
