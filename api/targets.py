from http.server import BaseHTTPRequestHandler
import csv
import json
import os
from pathlib import Path


# Public targets are embedded here so the function has no filesystem dependency.
# Regenerate by running: python3 targets/generate.py
PUBLIC_TARGETS_CSV = """\
id,smiles,chemotype,notes
t001,O=C(CCCCCCCCCCC(=O)Nc1ccncc1)Nc1ccncc1,protac_linker,
t002,N#Cc1ccc(NC(=O)COCCCCC(=O)NO)cc1,protac_linker_ha,
t003,O=C(CCCCCCCCCCCCC(=O)Nc1cccc(F)c1)NO,protac_linker_ha,
t004,O=C(CCCCCCCCCCCC(=O)Nc1ccc(Br)cc1)Nc1ccc(Br)cc1,protac_linker,
t005,O=C(COCCOCCOCCOCCOCCOCCOC(=O)NO)Nc1ccc(Br)cc1,protac_linker_ha,
t006,O=C(CCCCCCCCCCCC(=O)Nc1ccc2ccccc2c1)NO,protac_linker_ha,
t007,Cc1ccc(NC(=O)CCCCCC(=O)Nc2ccc(C)cc2)cc1,protac_linker,
t008,O=C1CN(Cc2ccccc2)CC(=O)N(Cc2ccccc2)CC(=O)N1,macrocycle,
t009,O=C(CCCCCC(=O)Nc1ccc(Br)cc1)NO,protac_linker_ha,
t010,N#Cc1ccc(NC(=O)COCCCOCCOC(=O)NO)cc1,protac_linker_ha,
"""

MANIFEST = {
    "seed": 42,
    "n_public": 10,
    "n_hidden": 100,
    "hidden_sha256": "30e5c4956f3b20c3",
    "tanimoto_cutoff": 0.7,
    "mw_range": [200.0, 900.0],
}


def parse_targets():
    import io
    reader = csv.DictReader(io.StringIO(PUBLIC_TARGETS_CSV))
    return list(reader)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"targets": parse_targets(), "manifest": MANIFEST})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass
