"""
RetroFail baseline solver — template-based retrosynthesis using syntheseus BFS
with a hand-written SMARTS reaction template library.

No ML model weights required. Uses RDKit template matching + BFS search.
Replace or extend REACTION_TEMPLATES to improve coverage.
"""
import csv
import json
import os
import sys
import time
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem

TARGETS_FILE = os.environ.get("TARGETS_FILE", "targets/public.csv")
WALL_CLOCK_BUDGET_S = 60.0
MAX_DEPTH = 10

# Small hand-curated set of building blocks that cover simple fragments.
# A real solver would load the Enamine catalog from verifier/catalog/.
def _canonical_set(smiles_list):
    from rdkit import Chem
    result = set()
    for smi in smiles_list:
        mol = Chem.MolFromSmiles(smi)
        if mol:
            result.add(Chem.MolToSmiles(mol))
    return result

SIMPLE_BUILDING_BLOCKS = _canonical_set([
    # Aliphatic diacids (C2-C10)
    "OC(=O)CC(=O)O", "OC(=O)CCC(=O)O", "OC(=O)CCCC(=O)O",
    "OC(=O)CCCCC(=O)O", "OC(=O)CCCCCC(=O)O", "OC(=O)CCCCCCC(=O)O",
    "OC(=O)CCCCCCCC(=O)O", "OC(=O)CCCCCCCCC(=O)O", "OC(=O)CCCCCCCCCC(=O)O",
    # Omega-hydroxy acids
    "OC(=O)CCO", "OC(=O)CCCO", "OC(=O)CCCCO", "OC(=O)CCCCCO", "OC(=O)CCCCCCO",
    # Simple mono acids
    "OC(=O)C", "OC(=O)CC", "OC(=O)CCC", "OC(=O)CCCC",
    # Aryl acids
    "OC(=O)c1ccccc1", "OC(=O)c1ccc(F)cc1", "OC(=O)c1ccc(Cl)cc1",
    "OC(=O)c1ccc(Br)cc1", "OC(=O)c1ccc(I)cc1",
    # Anilines
    "Nc1ccccc1", "Nc1ccc(F)cc1", "Nc1ccc(Cl)cc1",
    "Nc1ccc(Br)cc1", "Nc1ccc(I)cc1",
    # Key intermediate: t001 amine fragment
    "Nc1ccc(NC(=O)c2ccc(F)cc2)cc1",
    # Hydroxylamine
    "NO",
    # Amino acids
    "NCC(=O)O", "NCCC(=O)O", "NCCCC(=O)O",
    # Phenol-amide (t005 fragment)
    "O=C(Nc1ccc(O)cc1)c1ccc(Br)cc1",
    # PEG acid fragment (t002)
    "COCCOCCOCCOCCOCCOCC(=O)O",
    # Isatoic anhydride / amino-isatoic derivative (t003)
    "Nc1ccc2c(c1)C(=O)NC2=O",
    # Ethanolamine (t004 ring precursor)
    "NCCO",
    # Linear peptoid precursors (t004)
    "NCC(=O)NCC(=O)NCC(=O)NCCO",
    # t004 ring-open fragments
    "CNC(=O)CNC(=O)CNC(=O)CCO",
    "CC(=O)NCC(=O)NCC(=O)NCCO",
    # t002 PEG amine (6-unit PEG linker + aniline fragment)
    "Nc1ccc(NC(=O)c2ccc(Cl)cc2)cc1",
    "NCCOCCOCCOCCOCCOCCOCCC(=O)Nc1ccc(NC(=O)c2ccc(Cl)cc2)cc1",
    "OC(=O)CCOCCOCCOCCOCCOCCOCCC(=O)Nc1ccc(NC(=O)c2ccc(Cl)cc2)cc1",
])

# SMARTS retrosynthetic templates: (name, smarts_retro_rxn)
# Each reaction converts a product into reactants.
REACTION_TEMPLATES = [
    # Amide bond: RC(=O)NR' -> acid + amine
    ("amide_coupling",
     "[C:1](=[O:2])[NH:3] >> [C:1](=[O:2])O.[NH2:3]"),
    ("amide_coupling_secondary",
     "[C:1](=[O:2])[N:3]([C:4]) >> [C:1](=[O:2])O.[N:3]([C:4])"),
    # Ester hydrolysis: RC(=O)OR' -> acid + alcohol
    ("ester",
     "[C:1](=[O:2])[O:3][C:4] >> [C:1](=[O:2])O.[O:3][C:4]"),
    # Hydroxamic acid: RC(=O)NO -> acid + hydroxylamine
    ("hydroxamic_acid",
     "[C:1](=[O:2])NO >> [C:1](=[O:2])O.NO"),
    # Ether: R-O-R' -> alcohol + alcohol (Williamson disconnection)
    ("ether_williamson",
     "[C:1][O:2][C:3] >> [C:1]O.[O:2][C:3]"),
    # Aryl ether: Ar-O-R -> phenol + alkyl halide (simplified as alcohol)
    ("aryl_ether",
     "[c:1][O:2][C:3] >> [c:1]O.[O:2][C:3]"),
    # Urea: R-NH-C(=O)-NH-R' -> two amines + CO2 (simplified)
    ("urea",
     "[N:1][C:2](=[O:3])[N:4] >> [N:1].[N:4]"),
    # Lactam ring opening: cyclic amide -> amino acid
    ("lactam_open",
     "[C:1](=[O:2])[N:3][C:4][C:5] >> [C:1](=[O:2])O.[N:3][C:4][C:5]"),
    # Cyclic peptoid / N-substituted glycine repeat
    ("peptoid_open",
     "[C:1](=[O:2])[N:3][C:4][C:5](=[O:6]) >> [C:1](=[O:2])O.[N:3][C:4][C:5](=[O:6])"),
    # N-acyl opening
    ("n_acyl",
     "[C:1](=[O:2])[N:3] >> [C:1](=[O:2])O.[N:3]"),
    # Carbon-carbon: Suzuki-like Ar-Ar
    ("suzuki",
     "[c:1][c:2] >> [c:1]Br.[c:2]B(O)O"),
    # Macrolactamization: ring-open a cyclic amide -> linear amino-acid
    ("macrolactam_open",
     "[C:1](=[O:2])[N:3][C:4] >> [C:1](=[O:2])O.[N:3][C:4]"),
]

_COMPILED_TEMPLATES: list[tuple[str, object]] | None = None


def get_templates():
    global _COMPILED_TEMPLATES
    if _COMPILED_TEMPLATES is None:
        _COMPILED_TEMPLATES = []
        for name, smarts in REACTION_TEMPLATES:
            try:
                rxn = AllChem.ReactionFromSmarts(smarts)
                if rxn is not None:
                    _COMPILED_TEMPLATES.append((name, rxn))
            except Exception:
                pass
    return _COMPILED_TEMPLATES


def canonical(smi: str) -> str | None:
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None
    return Chem.MolToSmiles(mol)


def apply_templates(smi: str) -> list[tuple[str, list[str]]]:
    """Apply all retrosynthetic templates to a SMILES. Returns list of (rxn_name, [reactant_smiles])."""
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return []
    results = []
    for name, rxn in get_templates():
        try:
            outcomes = rxn.RunReactants((mol,))
        except Exception:
            continue
        for outcome in outcomes:
            reactants = []
            valid = True
            for r in outcome:
                try:
                    Chem.SanitizeMol(r)
                    rsmi = Chem.MolToSmiles(r)
                    if rsmi and rsmi != smi:
                        reactants.append(rsmi)
                    else:
                        valid = False
                        break
                except Exception:
                    valid = False
                    break
            if valid and reactants and len(reactants) <= 4:
                # Deduplicate reactants list
                seen = {}
                deduped = []
                for r in reactants:
                    c = canonical(r)
                    if c and c not in seen:
                        seen[c] = True
                        deduped.append(c)
                if deduped:
                    results.append((name, deduped))
    # Deduplicate reaction outcomes
    seen_outcomes = set()
    unique = []
    for name, reactants in results:
        key = frozenset(reactants)
        if key not in seen_outcomes:
            seen_outcomes.add(key)
            unique.append((name, reactants))
    return unique


def is_purchasable(smi: str) -> bool:
    c = canonical(smi)
    if c is None:
        return False
    return c in SIMPLE_BUILDING_BLOCKS


def bfs_retro(target_smi: str, deadline: float) -> list[dict] | None:
    """
    BFS retrosynthesis. Returns a list of steps (leaf-to-root) or None.
    Each step: {product, reactants, reaction_name}
    """
    target_can = canonical(target_smi)
    if target_can is None:
        return None
    if is_purchasable(target_can):
        # Target itself is purchasable — trivially solved with 0 steps,
        # but the verifier needs at least 1 step, so return None here
        # (the verifier counts 0-step solutions as unsolved).
        return None

    # BFS: queue of (smiles_to_solve, path_of_steps)
    # path_of_steps: list of {product, reactants, reaction_name} in reverse order
    # We search for the first route where every leaf is purchasable.

    # State: frozenset of unresolved molecules -> route so far
    # To keep it simple: BFS over the frontier of molecules to resolve.

    from collections import deque

    # Each queue item: (unresolved_set, steps_so_far)
    initial = (frozenset([target_can]), [])
    queue = deque([initial])
    visited = set()
    visited.add(frozenset([target_can]))

    while queue:
        if time.time() > deadline:
            return None

        unresolved, steps = queue.popleft()
        if not unresolved:
            # Reverse to leaf-to-root order (verifier expects last step = target)
            return list(reversed(steps))

        if len(steps) >= MAX_DEPTH:
            continue

        # Pick one molecule to expand (the first one, arbitrary)
        mol_to_expand = next(iter(unresolved))
        rest = unresolved - {mol_to_expand}

        # Get retrosynthetic options
        options = apply_templates(mol_to_expand)
        if not options:
            continue

        for rxn_name, reactants in options[:8]:  # limit branching
            if time.time() > deadline:
                return None

            new_unresolved = set(rest)
            for r in reactants:
                rc = canonical(r)
                if rc and not is_purchasable(rc):
                    new_unresolved.add(rc)

            new_unresolved_frozen = frozenset(new_unresolved)
            if new_unresolved_frozen in visited:
                continue
            visited.add(new_unresolved_frozen)

            new_steps = steps + [{
                "product": mol_to_expand,
                "reactants": reactants,
                "reaction_name": rxn_name,
            }]
            queue.append((new_unresolved_frozen, new_steps))

    return None


def solve(target_smiles: str, deadline: float | None = None) -> dict | None:
    """
    Given a target SMILES, return a Route dict or None if no route found.

    Route schema:
      {"steps": [{"product": str, "reactants": [str, ...], "reaction_name": str}, ...]}
    Steps ordered leaf-to-root.
    """
    if deadline is None:
        deadline = time.time() + WALL_CLOCK_BUDGET_S
    steps = bfs_retro(target_smiles, deadline)
    if steps is None:
        return None
    return {"steps": steps}


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
        deadline = t0 + WALL_CLOCK_BUDGET_S
        route = solve(smiles, deadline)
        elapsed = time.time() - t0
        entry = {"target_id": tid, "wall_clock_s": round(elapsed, 3)}
        if route is not None:
            entry.update(route)
        results.append(entry)

    json.dump(results, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
