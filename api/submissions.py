from http.server import BaseHTTPRequestHandler
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _db import get_submissions, get_users


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
        users = get_users()
        user = users.get(key)
        if not user:
            self._json(401, {"error": "unauthorized"})
            return

        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        show_all = qs.get("all", ["false"])[0].lower() == "true"

        subs = get_submissions()
        if not show_all:
            subs = [s for s in subs if s.get("user") == user["name"]]
        subs = sorted(subs, key=lambda s: s["score"], reverse=True)
        self._json(200, {"submissions": subs})

    def do_POST(self):
        # Submissions require a compute backend — not runnable in Vercel serverless.
        # Point to the self-hosted judge endpoint if configured.
        judge_url = os.environ.get("JUDGE_URL", "")
        if judge_url:
            self._json(307, {"redirect": judge_url + "/submit"})
        else:
            self._json(503, {
                "error": "Submission judging is not available on this deployment. "
                         "Run the server locally with: uvicorn server.main:app"
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
