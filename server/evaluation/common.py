"""Shared helpers for the evaluation scripts (paths, CSV, simple stats)."""

import csv
import math
import random
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
SERVER_DIR = EVAL_DIR.parent
DATASETS = EVAL_DIR / "datasets"
RAW = EVAL_DIR / "results" / "raw"        # per-item outputs (gitignored)
RESULTS = EVAL_DIR / "results"            # summary JSON/markdown (committed)
RAW.mkdir(parents=True, exist_ok=True)

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def read_csv(path: Path) -> list:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_csv(path: Path, row: dict, fields: list) -> None:
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def bootstrap_ci(values, stat=mean, n=2000, seed=0, alpha=0.05):
    """Percentile bootstrap CI for a statistic of a list of values."""
    values = list(values)
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    stats = sorted(stat([rng.choice(values) for _ in values]) for _ in range(n))
    return stats[int(n * alpha / 2)], stats[int(n * (1 - alpha / 2)) - 1]


def wilson(k: int, n: int, z: float = 1.96):
    """Wilson score interval for a proportion k/n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - r) / d, (c + r) / d


def groq_chat(model: str, messages: list, json_mode: bool = False, max_tokens: int = 1200,
              temperature: float | None = None, retries: int = 8) -> str:
    """Groq call for evaluation (persona, judge, screens) with waits on rate limits (429)."""
    import os
    import re
    import time

    from groq import Groq, RateLimitError

    from app import config
    client = Groq(api_key=config.GROQ_API_KEY or os.environ.get("GROQ_API_KEY"))
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    for attempt in range(retries):
        try:
            r = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens, **kwargs)
            content = (r.choices[0].message.content or "").strip()
            if content:
                return content
        except RateLimitError as exc:
            m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(exc))
            wait = (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else 10
            if wait > 300:
                raise
            time.sleep(wait + 0.5)
        except Exception:  # noqa: BLE001
            time.sleep(2 + 2 * attempt)
    raise RuntimeError(f"{model}: no response after {retries} attempts")


def groq_json(model: str, system: str, user: str, **kw) -> dict:
    import json
    raw = groq_chat(model, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    json_mode=True, **kw)
    return json.loads(raw[raw.find("{"): raw.rfind("}") + 1])


def pct(x: float) -> str:
    return "n/a" if x != x else f"{100 * x:.0f}%"
