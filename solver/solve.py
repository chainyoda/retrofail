"""
Baseline solver — trivially claims a one-step route for each target
using the target itself as both reactant and product.
This sets the floor that submissions must beat.

Replace the logic inside solve() to implement a real retrosynthesis algorithm.
"""
import csv
import json
import os
import sys
import time
from pathlib import Path

TARGETS_FILE = os.environ.get("TARGETS_FILE", "targets/public.csv")
WALL_CLOCK_BUDGET_S = 60.0


def solve(target_smiles: str) -> dict | None:
    """
    Given a target SMILES, return a Route dict or None if no route found.

    Route schema:
    {
      "steps": [
        {
          "product": "<SMILES>",
          "reactants": ["<SMILES>", ...],
          "reaction_name": "<string>"
        },
        ...
      ]
    }
    Steps ordered leaf-to-root (step 0 = first reaction, last step = target).
    """
    # Stub: always fail (score = 0). Replace with a real solver.
    return None


def main():
    targets = []
    with open(TARGETS_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            targets.append(row)

    results = []
    for row in targets:
        tid = row["id"]
        smiles = row["smiles"]
        t0 = time.time()
        route = solve(smiles)
        elapsed = time.time() - t0
        entry = {"target_id": tid, "wall_clock_s": round(elapsed, 3)}
        if route is not None:
            entry.update(route)
        results.append(entry)

    json.dump(results, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
