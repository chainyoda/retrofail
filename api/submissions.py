from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlparse, parse_qs


def _get_submissions():
    raw = os.environ.get("RETROFAIL_SUBMISSIONS", "")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


def _get_users():
    raw = os.environ.get("RETROFAIL_USERS", "")
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _cors(h):
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        _cors(self)
        self.end_headers()

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        key = auth.removeprefix("Bearer ").strip()
        users = _get_users()
        user = users.get(key)
        if not user:
            self._json(401, {"error": "unauthorized"})
            return
        qs = parse_qs(urlparse(self.path).query)
        show_all = qs.get("all", ["false"])[0].lower() == "true"
        subs = _get_submissions()
        if not show_all:
            subs = [s for s in subs if s.get("user") == user["name"]]
        subs = sorted(subs, key=lambda s: s["score"], reverse=True)
        self._json(200, {"submissions": subs})

    def do_POST(self):
        judge_url = os.environ.get("JUDGE_URL", "")
        if judge_url:
            self._json(307, {"redirect": judge_url + "/submit"})
        else:
            self._json(503, {
                "error": "Submission judging requires a compute backend. "
                         "Run locally: uvicorn server.main:app"
            })

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        _cors(self)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
