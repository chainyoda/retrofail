from http.server import BaseHTTPRequestHandler
import json
import os


def _get_submissions():
    raw = os.environ.get("RETROFAIL_SUBMISSIONS", "")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        subs = _get_submissions()
        promoted = sorted(
            [s for s in subs if s.get("promoted")],
            key=lambda s: s["score"],
            reverse=True,
        )
        body = json.dumps({"leaderboard": promoted, "best": promoted[0] if promoted else None})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass
