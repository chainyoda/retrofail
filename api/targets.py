from http.server import BaseHTTPRequestHandler
import csv
import json
import io


PUBLIC_TARGETS_CSV = """\
id,smiles,chemotype,human_synthesis
cocaine,COC(=O)[C@H]1[C@@H](OC(=O)c2ccccc2)C[C@@H]2CC[C@H]1N2C,natural_product,"Willstätter 1898, 2 steps"
penicillin_g,CC1(C)SC2C(NC(=O)Cc3ccccc3)C(=O)N2C1C(=O)O,natural_product,"Sheehan 1957, 9 steps"
longifolene,C=C1[C@H]2CC[C@@H]3[C@H]2C(C)(C)CCC[C@]13C,natural_product,"Corey 1961, 14 steps"
cortisone,C[C@]12CCC(=O)C=C1CC[C@@H]1[C@@H]2C(=O)C[C@@]2(C)[C@H]1CC[C@]2(O)C(=O)CO,natural_product,"Woodward 1951, 47 steps"
colchicine,COc1cc2c(c(OC)c1OC)-c1ccc(OC)c(=O)cc1[C@@H](NC(C)=O)CC2,natural_product,"Woodward 1963, 21 steps"
quinine,C=C[C@H]1CN2CC[C@H]1C[C@H]2[C@H](O)c1ccnc2ccc(OC)cc12,natural_product,"Woodward & Doering 1944, 17 steps"
artemisinin,C[C@@H]1CC[C@H]2[C@@H](C)C(=O)O[C@@H]3O[C@@]4(C)CC[C@@H]1[C@]32OO4,natural_product,"Schmid & Hofheinz 1983, 14 steps"
codeine,COc1ccc2c3c1O[C@H]1[C@@H](O)C=C[C@H]4[C@@H](C2)N(C)CC[C@@]341,natural_product,"Gates 1952 (morphine), 30 steps"
morphine,CN1CC[C@]23c4c5ccc(O)c4O[C@H]2[C@@H](O)C=C[C@H]3[C@H]1C5,natural_product,"Gates & Tschudi 1952, 30 steps"
camptothecin,CC[C@@]1(O)C(=O)OCc2c1cc1n(c2=O)Cc2cc3ccccc3nc2-1,natural_product,"Stork & Schultz 1971, 21 steps"
prostaglandin_f2a,CCCCC[C@H](O)/C=C/[C@H]1[C@H](O)CC(=O)[C@@H]1C/C=C\CCCC(=O)O,natural_product,"Corey 1969, 20 steps"
lysergic_acid,CN1C[C@H](C(=O)O)C=C2c3cccc4[nH]cc(c34)C[C@H]21,natural_product,"Woodward 1956, 22 steps"
reserpine,COC(=O)[C@H]1[C@H]2C[C@@H]3c4[nH]c5cc(OC)ccc5c4CCN3C[C@H]2C[C@@H](OC(=O)c2cc(OC)c(OC)c(OC)c2)[C@@H]1OC,natural_product,"Woodward 1956, 24 steps"
strychnine,O=C1C[C@@H]2OCC=C3CN4CC[C@]56c7ccccc7N1[C@H]5[C@H]2[C@H]3C[C@H]46,natural_product,"Woodward 1954, 29 steps"
erythromycin,CC[C@H]1OC(=O)[C@H](C)[C@@H](O[C@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@H](O[C@@H]2O[C@H](C)C[C@H](N(C)C)[C@H]2O)[C@](C)(O)C[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]1(C)O,natural_product,"Woodward ~1981, 50 steps"
epothilone_b,C/C(=C\c1csc(C)n1)[C@@H]1C[C@@H]2O[C@]2(C)CCC[C@H](C)[C@H](O)[C@@H](C)C(=O)C(C)(C)[C@@H](O)CC(=O)O1,natural_product,"Danishefsky 1996, 31 steps"
discodermolide,C=C/C=C\[C@H](C)[C@H](OC(N)=O)[C@@H](C)[C@H](O)[C@@H](C)C/C(C)=C\[C@H](C)[C@@H](O)[C@@H](C)/C=C\[C@@H](O)C[C@@H]1OC(=O)[C@H](C)[C@@H](O)[C@H]1C,natural_product,"Panek 2000, 39 steps"
taxol,CC(=O)O[C@H]1C(=O)[C@@]2(C)[C@H]([C@H](OC(=O)c3ccccc3)[C@]3(O)C[C@H](OC(=O)[C@H](O)[C@@H](NC(=O)c4ccccc4)c4ccccc4)C(C)=C1C3(C)C)[C@]1(OC(C)=O)CO[C@@H]1C[C@@H]2O,natural_product,"Holton 1994, 51 steps"
vinblastine,CC[C@]1(O)C[C@@H]2CN(CCc3c([nH]c4ccccc34)[C@@](C(=O)OC)(c3cc4c(cc3OC)N(C)[C@H]3[C@@](O)(C(=O)OC)[C@H](OC(C)=O)[C@]5(CC)C=CCN6CC[C@]43[C@@H]65)C2)C1,natural_product,"Potier/Kutney 1970s, 30 steps"
"""

MANIFEST = {
    "name": "Natural Products Total Synthesis Benchmark",
    "total": 19,
    "hidden_sha256": "cab603422f71b630",
    "note": "No AI system has published solve rates against this set.",
}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        reader = csv.DictReader(io.StringIO(PUBLIC_TARGETS_CSV))
        targets = list(reader)
        body = json.dumps({"targets": targets, "manifest": MANIFEST})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass
