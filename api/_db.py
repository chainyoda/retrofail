"""
Thin persistence layer — reads from env vars (Vercel KV or JSON env).
For the prototype, data is stored in RETROFAIL_SUBMISSIONS_JSON and
RETROFAIL_USERS_JSON environment variables (set in Vercel dashboard).
Production would swap this for Vercel KV or Supabase.
"""
import json
import os


def _load(var: str, default) -> dict | list:
    raw = os.environ.get(var, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def get_submissions() -> list[dict]:
    return _load("RETROFAIL_SUBMISSIONS", [])


def get_users() -> dict:
    return _load("RETROFAIL_USERS", {})


def get_best() -> dict:
    return _load("RETROFAIL_BEST", {"score": -1e9, "submission_id": None})
