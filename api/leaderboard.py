from http.server import BaseHTTPRequestHandler
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from _db import get_submissions


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        subs = get_submissions()
        promoted = [s for s in subs if s.get("promoted")]
        promoted = sorted(promoted, key=lambda s: s["score"], reverse=True)
        body = json.dumps({"leaderboard": promoted, "best": promoted[0] if promoted else None})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass
