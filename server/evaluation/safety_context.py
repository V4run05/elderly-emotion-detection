"""Quick re-check of the self-harm screen after a prompt change: the context cases, plus the
indirect and harmless held-out sentences (no context), with the production screen.

    python evaluation/safety_context.py
"""

import json

from common import RESULTS, pct

from app.analysis import safety
from verbal_safety import CONTEXT_CASES, SAFETY, SAFETY_HOLDOUT, llm_screen


def main():
    out = {"context": [], "holdout_indirect": [], "holdout_benign": [], "indirect": [], "benign": []}
    for earlier, last, risk in CONTEXT_CASES:
        m = llm_screen(last, earlier)
        out["context"].append(m == risk)
        print(f"  context expected={risk} got={m}: {last}", flush=True)
    for key, items in (("holdout_indirect", SAFETY_HOLDOUT["indirect"]), ("holdout_benign", SAFETY_HOLDOUT["benign"]),
                       ("indirect", SAFETY["indirect"]), ("benign", SAFETY["benign"])):
        for s in items:
            m = llm_screen(s) or safety.keyword_flag(s)
            out[key].append(m)
        print(f"  {key}: flagged {pct(sum(out[key]) / len(out[key]))}", flush=True)
    summary = {"context_correct": sum(out["context"]) / len(out["context"]),
               **{f"{k}_flagged": sum(v) / len(v) for k, v in out.items() if k != "context"}}
    (RESULTS / "safety_context.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
