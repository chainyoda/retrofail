#!/usr/bin/env python3
"""
retrofail CLI — thin prototype
Commands: login, clone, run, submit, submissions, sync
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "retrofail" / "config.json"
DEFAULT_API = os.environ.get("RETROFAIL_API_URL", "http://localhost:8000")


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def api_url() -> str:
    return load_config().get("api_url", DEFAULT_API)


def auth_header() -> dict:
    cfg = load_config()
    key = cfg.get("api_key", "")
    if not key:
        print("not logged in — run: retrofail login <api-key>")
        sys.exit(1)
    return {"Authorization": f"Bearer {key}"}


def get(path: str, **kwargs):
    import urllib.request
    import urllib.error
    url = api_url() + path
    req = urllib.request.Request(url, headers=kwargs.get("headers", {}))
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}")
        sys.exit(1)


def post_json(path: str, data: dict, headers: dict = {}):
    import urllib.request
    import urllib.error
    url = api_url() + path
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}")
        sys.exit(1)


def post_multipart(path: str, fields: dict, files: dict, headers: dict = {}):
    """Minimal multipart/form-data POST without external deps."""
    import urllib.request
    import urllib.error
    boundary = "retrofailboundary1234567890"
    body_parts = []
    for name, value in fields.items():
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    for name, (filename, data) in files.items():
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
            + data + b"\r\n"
        )
    body_parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(body_parts)
    url = api_url() + path
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}")
        sys.exit(1)


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_login(args):
    cfg = load_config()
    cfg["api_key"] = args.api_key
    cfg["api_url"] = args.api or DEFAULT_API
    save_config(cfg)
    result = post_json("/auth/login", {"api_key": args.api_key})
    print(f"logged in as {result['user']}")


def cmd_clone(args):
    dest = Path(args.dest or "challenge")
    if dest.exists():
        print(f"{dest} already exists")
        sys.exit(1)

    import urllib.request
    url = api_url() + "/clone"
    req = urllib.request.Request(url, headers=auth_header())
    with urllib.request.urlopen(req) as r:
        data = r.read()

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest)

    print(f"cloned to {dest}/")
    print("next: edit solver/solve.py, then run: retrofail run")


def cmd_run(args):
    repo = Path(args.repo or ".")
    if not (repo / "benchmark.sh").exists():
        print("not in a retrofail repo (benchmark.sh not found)")
        sys.exit(1)
    result = subprocess.run(["bash", "benchmark.sh"], cwd=repo)
    sys.exit(result.returncode)


def cmd_submit(args):
    repo = Path(args.repo or ".")
    solver_dir = repo / "solver"
    if not solver_dir.exists():
        print("solver/ directory not found")
        sys.exit(1)

    # Zip the solver directory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in solver_dir.rglob("*"):
            if f.is_file() and "__pycache__" not in str(f):
                zf.write(f, f.relative_to(solver_dir))
    solver_zip = buf.getvalue()

    print("submitting...")
    from urllib.parse import quote
    result = post_multipart(
        f"/submit?note={quote(args.note or '')}&model={quote(args.model or '')}",
        fields={},
        files={"solver_zip": ("solver.zip", solver_zip)},
        headers=auth_header(),
    )
    if result.get("promoted"):
        print(f"PROMOTED — new best score: {result['score']}")
    else:
        print(f"not promoted (score: {result['score']})")
    metrics = result.get("metrics", {})
    print(f"  solve_rate: {metrics.get('solve_rate')}  solved: {metrics.get('solved')}/{metrics.get('total')}")
    print(f"  submission id: {result.get('id')}")


def cmd_submissions(args):
    all_flag = "?all=true" if args.all else ""
    result = get(f"/submissions{all_flag}", headers=auth_header())
    subs = result.get("submissions", [])
    if not subs:
        print("no submissions")
        return
    print(f"{'id':<14} {'score':>8} {'solve_rate':>10} {'user':<16} {'promoted'}")
    for s in subs[:20]:
        m = s.get("metrics", {})
        print(f"{s['id']:<14} {s['score']:>8.4f} {m.get('solve_rate', 0):>10.4f} {s['user']:<16} {'*' if s.get('promoted') else ''}")


def cmd_leaderboard(args):
    result = get("/leaderboard")
    board = result.get("leaderboard", [])
    if not board:
        print("no promoted submissions yet")
        return
    print(f"{'rank':<5} {'score':>8} {'solve_rate':>10} {'user':<16}")
    for i, s in enumerate(board, 1):
        m = s.get("metrics", {})
        print(f"{i:<5} {s['score']:>8.4f} {m.get('solve_rate', 0):>10.4f} {s['user']:<16}")


def main():
    p = argparse.ArgumentParser(prog="retrofail")
    sub = p.add_subparsers(dest="cmd")

    lo = sub.add_parser("login")
    lo.add_argument("api_key")
    lo.add_argument("--api", default=None)

    cl = sub.add_parser("clone")
    cl.add_argument("dest", nargs="?")

    ru = sub.add_parser("run")
    ru.add_argument("--repo", default=None)

    su = sub.add_parser("submit")
    su.add_argument("--note", default="")
    su.add_argument("--model", default="")
    su.add_argument("--repo", default=None)

    sm = sub.add_parser("submissions")
    sm.add_argument("--all", action="store_true")

    sub.add_parser("leaderboard")

    args = p.parse_args()
    dispatch = {
        "login": cmd_login,
        "clone": cmd_clone,
        "run": cmd_run,
        "submit": cmd_submit,
        "submissions": cmd_submissions,
        "leaderboard": cmd_leaderboard,
    }
    if args.cmd not in dispatch:
        p.print_help()
        sys.exit(1)
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
