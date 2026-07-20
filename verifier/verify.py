"""
Trusted verifier — never imports solver code.
Reads route.json, validates each route against the target set, computes score.
"""
import argparse
import json
import sys
import time
from pathlib import Path

try:
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors
except ImportError:
    print("rdkit not installed; run ./setup.sh", file=sys.stderr)
    sys.exit(1)

CATALOG_FILE = Path(__file__).parent / "catalog" / "building_blocks.smi"
TEMPLATES_FILE = Path(__file__).parent / "templates" / "reactions.json"
MAX_ROUTE_DEPTH = 10
WALL_CLOCK_BUDGET_S = 60.0


def canonical(smi: str) -> str | None:
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None
    return Chem.MolToSmiles(mol)


def load_catalog() -> set[str]:
    if not CATALOG_FILE.exists():
        return set()
    catalog = set()
    for line in CATALOG_FILE.read_text().splitlines():
        line = line.strip().split()[0] if line.strip() else ""
        if line:
            c = canonical(line)
            if c:
                catalog.add(c)
    return catalog


def load_targets(targets_file: str) -> dict[str, dict]:
    import csv
    targets = {}
    with open(targets_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            targets[row["id"]] = row
    return targets


def validate_route(route: dict, target_smiles: str, catalog: set[str]) -> tuple[bool, str]:
    """Returns (valid, reason)."""
    steps = route.get("steps", [])
    if not steps:
        return False, "empty route"
    if len(steps) > MAX_ROUTE_DEPTH:
        return False, f"route depth {len(steps)} exceeds max {MAX_ROUTE_DEPTH}"

    # Root product must match target
    root_product = steps[-1].get("product", "")
    root_can = canonical(root_product)
    target_can = canonical(target_smiles)
    if root_can is None:
        return False, "root product invalid SMILES"
    if root_can != target_can:
        return False, f"root product {root_can!r} != target {target_can!r}"

    # Collect leaves (reactants that don't appear as a product of any step)
    all_products = {canonical(s.get("product", "")) for s in steps}
    for step in steps:
        for reactant in step.get("reactants", []):
            r_can = canonical(reactant)
            if r_can is None:
                return False, f"invalid reactant SMILES: {reactant!r}"
            if r_can not in all_products:
                # It's a leaf — must be in catalog (or catalog is empty in dev mode)
                if catalog and r_can not in catalog:
                    return False, f"leaf {r_can!r} not in building block catalog"

    return True, "ok"


def score_routes(routes: list[dict], targets: dict, catalog: set[str]) -> dict:
    solved = 0
    total = len(targets)
    route_lengths = []
    wall_clocks = []

    for tid, trow in targets.items():
        target_smi = trow["smiles"]
        # Find the route for this target
        route = next((r for r in routes if r.get("target_id") == tid), None)

        wall_clock = float(route.get("wall_clock_s", WALL_CLOCK_BUDGET_S)) if route else WALL_CLOCK_BUDGET_S
        wall_clocks.append(min(wall_clock, WALL_CLOCK_BUDGET_S))

        if route is None:
            continue
        if wall_clock > WALL_CLOCK_BUDGET_S:
            continue  # over budget, doesn't count

        valid, reason = validate_route(route, target_smi, catalog)
        if valid:
            solved += 1
            n_steps = len(route.get("steps", []))
            route_lengths.append(n_steps)

    solve_rate = solved / total if total > 0 else 0.0
    mean_efficiency = (
        sum(1.0 / l for l in route_lengths) / len(route_lengths)
        if route_lengths else 0.0
    )
    mean_wall_clock = sum(wall_clocks) / len(wall_clocks) if wall_clocks else 0.0

    composite = (
        solve_rate
        + 0.10 * mean_efficiency
        - 0.01 * mean_wall_clock
    )

    return {
        "score": round(composite, 6),
        "metrics": {
            "solve_rate": round(solve_rate, 4),
            "solved": solved,
            "total": total,
            "mean_route_efficiency": round(mean_efficiency, 4),
            "mean_wall_clock_s": round(mean_wall_clock, 2),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--routes", required=True)
    parser.add_argument("--targets", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    catalog = load_catalog()
    if not catalog:
        print("warning: building block catalog is empty; leaf-availability check skipped", file=sys.stderr)

    targets = load_targets(args.targets)
    routes_data = json.loads(Path(args.routes).read_text())
    routes = routes_data if isinstance(routes_data, list) else routes_data.get("routes", [])

    result = score_routes(routes, targets, catalog)
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result), file=sys.stderr)


if __name__ == "__main__":
    main()
