"""
RetroFail server - thin prototype.
Handles: auth, clone (repo zip), submit (run judge, enforce promotion), leaderboard.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

import csv

from fastapi import FastAPI, Header, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="RetroFail API")

DB_PATH = Path(os.environ.get("RETROFAIL_DATA", "/tmp/retrofail-data"))
DB_PATH.mkdir(exist_ok=True)
REPO_ROOT = Path(__file__).parent.parent
SUBMISSIONS_FILE = DB_PATH / "submissions.json"
USERS_FILE = DB_PATH / "users.json"
BEST_SCORE_FILE = DB_PATH / "best_score.json"


def load_json(p: Path, default):
    if p.exists():
        return json.loads(p.read_text())
    return default


def save_json(p: Path, data):
    p.write_text(json.dumps(data, indent=2))


def get_user(api_key: str) -> dict | None:
    users = load_json(USERS_FILE, {})
    return users.get(api_key)


def require_user(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    key = authorization.removeprefix("Bearer ").strip()
    user = get_user(key)
    if not user:
        raise HTTPException(401, "invalid api key")
    return user


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    api_key: str

@app.post("/auth/login")
def login(req: LoginRequest):
    user = get_user(req.api_key)
    if not user:
        raise HTTPException(401, "invalid api key")
    return {"user": user["name"], "ok": True}


@app.get("/auth/register")
def register(name: str):
    """Dev-only: create a user and return their API key."""
    api_key = "rf_" + uuid.uuid4().hex
    users = load_json(USERS_FILE, {})
    users[api_key] = {"name": name, "id": uuid.uuid4().hex}
    save_json(USERS_FILE, users)
    return {"api_key": api_key, "name": name}


# ── Benchmark ─────────────────────────────────────────────────────────────────

@app.get("/benchmark")
def get_benchmark():
    manifest = json.loads((REPO_ROOT / "benchmark.json").read_text())
    return manifest


@app.get("/clone")
def clone_zip(authorization: str = Header(None)):
    require_user(authorization)
    buf = io.BytesIO()
    editable_paths = ["solver"]
    harness_paths = ["verifier", "targets", "benchmark.sh", "setup.sh", "benchmark.json"]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in harness_paths:
            full = REPO_ROOT / rel
            if full.is_file():
                zf.write(full, rel)
            elif full.is_dir():
                for f in full.rglob("*"):
                    if f.is_file():
                        zf.write(f, str(f.relative_to(REPO_ROOT)))
        for rel in editable_paths:
            full = REPO_ROOT / rel
            if full.is_dir():
                for f in full.rglob("*"):
                    if f.is_file():
                        zf.write(f, str(f.relative_to(REPO_ROOT)))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                              headers={"Content-Disposition": "attachment; filename=retrofail.zip"})


# ── Submit ────────────────────────────────────────────────────────────────────

@app.post("/submit")
async def submit(
    solver_zip: UploadFile = File(...),
    note: str = "",
    model: str = "",
    authorization: str = Header(None),
):
    user = require_user(authorization)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Copy the full repo into tmp
        for item in REPO_ROOT.iterdir():
            if item.name in (".git", "__pycache__", "server"):
                continue
            dst = tmp / item.name
            if item.is_dir():
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)

        # Overwrite solver with the submitted zip
        solver_dir = tmp / "solver"
        shutil.rmtree(solver_dir, ignore_errors=True)
        solver_dir.mkdir()
        raw = await solver_zip.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            zf.extractall(solver_dir)

        # Use hidden targets on the server if available, public otherwise
        hidden_targets = REPO_ROOT / "targets" / "hidden.csv"
        if hidden_targets.exists():
            shutil.copy2(hidden_targets, tmp / "targets" / "hidden.csv")
            targets_arg = str(tmp / "targets" / "hidden.csv")
        else:
            targets_arg = str(tmp / "targets" / "public.csv")

        # Run the benchmark against the appropriate target set
        t0 = time.time()
        result = subprocess.run(
            ["bash", "-c",
             f"TARGETS_FILE={targets_arg} bash benchmark.sh"],
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=300,
        )
        elapsed = time.time() - t0

        if result.returncode != 0:
            return JSONResponse({"ok": False, "error": result.stderr[-2000:]}, status_code=422)

        score_json = json.loads((tmp / "score.json").read_text())
        new_score = score_json["score"]

        best = load_json(BEST_SCORE_FILE, {"score": -1e9, "submission_id": None})
        promoted = new_score > best["score"]

        sub_id = uuid.uuid4().hex[:12]
        submission = {
            "id": sub_id,
            "user": user["name"],
            "score": new_score,
            "metrics": score_json.get("metrics", {}),
            "note": note,
            "model": model,
            "promoted": promoted,
            "timestamp": int(time.time()),
            "elapsed_s": round(elapsed, 1),
        }

        subs = load_json(SUBMISSIONS_FILE, [])
        subs.append(submission)
        save_json(SUBMISSIONS_FILE, subs)

        if promoted:
            save_json(BEST_SCORE_FILE, {"score": new_score, "submission_id": sub_id})

        return {"ok": True, "promoted": promoted, "score": new_score, "id": sub_id,
                "metrics": score_json.get("metrics", {})}


# ── Leaderboard ───────────────────────────────────────────────────────────────

@app.get("/submissions")
def submissions(all: bool = False, authorization: str = Header(None)):
    user = require_user(authorization)
    subs = load_json(SUBMISSIONS_FILE, [])
    if not all:
        subs = [s for s in subs if s["user"] == user["name"]]
    # Sort by score desc
    subs = sorted(subs, key=lambda s: s["score"], reverse=True)
    return {"submissions": subs}


@app.get("/leaderboard")
def leaderboard():
    subs = load_json(SUBMISSIONS_FILE, [])
    promoted = [s for s in subs if s.get("promoted")]
    promoted = sorted(promoted, key=lambda s: s["score"], reverse=True)
    # Include public submission history (score + timestamp only, no user PII) for the chart
    history = sorted(
        [{"score": s["score"], "timestamp": s["timestamp"], "promoted": s.get("promoted", False)}
         for s in subs],
        key=lambda s: s["timestamp"]
    )
    return {"leaderboard": promoted, "best": promoted[0] if promoted else None, "history": history}


@app.get("/health")
def health():
    return {"ok": True}


# ── Public targets + manifest ─────────────────────────────────────────────────

@app.get("/targets/public")
def get_public_targets():
    targets_file = REPO_ROOT / "targets" / "public.csv"
    manifest_file = REPO_ROOT / "targets" / "manifest.json"
    targets = []
    if targets_file.exists():
        with open(targets_file) as f:
            for row in csv.DictReader(f):
                targets.append(row)
    manifest = {}
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text())
    return {"targets": targets, "manifest": manifest}


# ── CORS (allow Vercel frontend to call this API) ─────────────────────────────

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://retrofail.vercel.app", "http://localhost:8000", "http://localhost:3000", "https://retrofail-judge-production.up.railway.app"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Static frontend (local dev only — disabled in production) ─────────────────

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists() and not os.environ.get("STATIC_DISABLED"):
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
