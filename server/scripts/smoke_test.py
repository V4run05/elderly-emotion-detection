"""End-to-end check against a RUNNING server, with real models and real Groq calls.

    python scripts/smoke_test.py                      # uses tests/fixtures clip + face photo
    python scripts/smoke_test.py --audio my.m4a --image me.jpg
    python scripts/smoke_test.py --url https://192.168.1.5:8443

It is also the smallest possible "device client": the exact HTTP calls a Raspberry Pi client
would make (start session -> post audio + frames -> read reply), using only the standard
library. The run is recorded like a real check-in, so it shows up on the dashboard.
"""

import argparse
import json
import mimetypes
import ssl
import sys
import time
import urllib.request
import uuid
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def request(url: str, data: bytes | None = None, headers: dict | None = None) -> dict:
    ctx = ssl._create_unverified_context()  # self-signed dev cert
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"HTTP {exc.code} from {url}: {exc.read().decode(errors='replace')}")


def multipart(files: list) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = b""
    for field, path in files:
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
                 f"filename=\"{path.name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
        body += path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--audio", type=Path, default=FIXTURES / "test_clip.m4a")
    p.add_argument("--image", type=Path, default=FIXTURES / "face_astronaut.jpg")
    p.add_argument("--no-image", action="store_true")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    print("Waiting for models to load", end="", flush=True)
    while not (h := request(f"{args.url}/api/health"))["ready"]:
        if "error" in h["models"].values():
            sys.exit(f"\nmodel failed to load: {h['errors']}")
        print(".", end="", flush=True)
        time.sleep(2)
    print(" ready.")

    s = request(f"{args.url}/api/sessions", data=b"")
    print(f"\nCompanion: {s['greeting_text']}")
    files = [("audio", args.audio)] + ([] if args.no_image else [("images", args.image)])
    body, ctype = multipart(files)
    t = time.perf_counter()
    r = request(f"{args.url}/api/sessions/{s['session_id']}/turns", data=body,
                headers={"Content-Type": ctype})
    elapsed = time.perf_counter() - t
    if not r["heard"]:
        sys.exit("Server heard no speech in the clip.")

    a = r["analysis"]
    ch = a["nonverbal"]["channels"]
    print(f"You said:  {r['transcript']}")
    print(f"Companion: {r['reply_text']}")
    print(f"\n  words      {a['verbal']['valence']:+.2f}  reassurance={a['verbal']['reassurance']}")
    print(f"  voice      {ch['voice']['label'] if ch['voice'] else '-'}")
    print(f"  face       {ch['face']['label'] if ch['face'] else '-'}")
    print(f"  seemed     {a['nonverbal']['valence']:+.2f}")
    print(f"  status     {a['status']} (masking score {a['masking_score']:.2f})")
    print(f"  reply mp3  {r['reply_audio_url']}")
    print(f"  time       {elapsed:.1f} s  {r['timings_s']}")
    request(f"{args.url}/api/sessions/{s['session_id']}/end", data=b"")
    print("\nOK")


if __name__ == "__main__":
    main()
