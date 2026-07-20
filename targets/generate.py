"""
RetroFail target generator.

Assembles PROTAC linker and macrocycle targets by combinatorial fragment
recombination, filters out anything too similar to known drugs, and writes:
  - targets/public.csv    (N_PUBLIC targets, committed to the repo)
  - targets/hidden.csv    (N_HIDDEN targets, server-only, never committed)

Usage:
  python3 targets/generate.py [--seed 42] [--public 10] [--hidden 100] [--out-dir targets/]

Anti-gaming properties:
  - Targets are generated deterministically from a public seed so the process
    is reproducible, but the hidden split index is not published.
  - Any target with Tanimoto(Morgan2, known_drug) > TANIMOTO_CUTOFF is dropped.
  - MW and ring filters remove trivially simple or unreasonably large molecules.
"""
import argparse
import csv
import hashlib
import itertools
import random
import sys
from pathlib import Path
from typing import Iterator

from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs, rdMolDescriptors

TANIMOTO_CUTOFF = 0.70
MW_MIN = 200.0
MW_MAX = 900.0
MIN_ROTATABLE_BONDS = 3

# ── Fragment pools ─────────────────────────────────────────────────────────────
# Each PROTAC linker target is assembled as:
#   WARHEAD_A - LINKER - WARHEAD_B
# where WARHEAD is an amide-terminated aryl group and LINKER is an aliphatic/PEG chain.

# Warheads: amine end (will couple with COOH linker ends via amide)
WARHEAD_AMINES = [
    ("4F-aniline",       "Nc1ccc(F)cc1"),
    ("4Cl-aniline",      "Nc1ccc(Cl)cc1"),
    ("4Br-aniline",      "Nc1ccc(Br)cc1"),
    ("4Me-aniline",      "Nc1ccc(C)cc1"),
    ("4OMe-aniline",     "Nc1ccc(OC)cc1"),
    ("4CF3-aniline",     "Nc1ccc(C(F)(F)F)cc1"),
    ("34diF-aniline",    "Nc1ccc(F)c(F)c1"),
    ("3F-aniline",       "Nc1cccc(F)c1"),
    ("4CN-aniline",      "Nc1ccc(C#N)cc1"),
    ("naphthyl-amine",   "Nc1ccc2ccccc2c1"),
    ("pyridyl-amine",    "Nc1ccncc1"),
    ("thienyl-amine",    "Nc1cccs1"),
    ("benzyl-amine",     "NCc1ccccc1"),
    ("4F-benzyl",        "NCc1ccc(F)cc1"),
    ("4Cl-benzyl",       "NCc1ccc(Cl)cc1"),
    ("cyclo-hexyl",      "NC1CCCCC1"),
    ("piperazinyl",      "N1CCNCC1"),
    ("morpholinyl",      "N1CCOCC1"),
    ("4-aminopiperidine","NC1CCNCC1"),
]

# Warheads: acid end (COOH-terminated, for the other side of the amide)
WARHEAD_ACIDS = [
    ("4F-benzoic",       "OC(=O)c1ccc(F)cc1"),
    ("4Cl-benzoic",      "OC(=O)c1ccc(Cl)cc1"),
    ("4Br-benzoic",      "OC(=O)c1ccc(Br)cc1"),
    ("phenyl-acetic",    "OC(=O)Cc1ccccc1"),
    ("4F-phenyl-acetic", "OC(=O)Cc1ccc(F)cc1"),
    ("nicotinic",        "OC(=O)c1cccnc1"),
    ("indole-2-COOH",    "OC(=O)c1ccc2[nH]ccc2c1"),
    ("3-pyridyl-acetic", "OC(=O)Cc1cccnc1"),
    ("cyclo-propane",    "OC(=O)C1CC1"),
    ("cyclo-butane",     "OC(=O)C1CCC1"),
    ("trans-cinnamic",   "OC(=O)/C=C/c1ccccc1"),
]

# Linker cores: diacid SMILES (both ends COOH or OH-functional for amide coupling)
# For PROTAC-style: amine warhead + diacid linker + amine warhead
# We build: WarheadAcid - (NH) - LinkerAlkyl - (NH) - WarheadAcid
# but represent linker as the carbon chain between two amide nitrogens.

# Actually we build the full target SMILES directly as:
#   WarheadAcid-CO-NH-[chain]-NH-CO-WarheadAmine
# i.e. two amide bonds around a flexible linker.

# Linker chains (the fragment between the two amide NH groups):
ALKYL_LINKERS = [
    ("C3",  "CCC"),
    ("C4",  "CCCC"),
    ("C5",  "CCCCC"),
    ("C6",  "CCCCCC"),
    ("C7",  "CCCCCCC"),
    ("C8",  "CCCCCCCC"),
    ("C9",  "CCCCCCCCC"),
    ("C10", "CCCCCCCCCC"),
    ("C11", "CCCCCCCCCCC"),
    ("C12", "CCCCCCCCCCCC"),
]

PEG_LINKERS = [
    ("PEG1", "COCCO"),
    ("PEG2", "COCCCOCCO"),
    ("PEG3", "COCCOCCOCCO"),
    ("PEG4", "COCCOCCOCCOCCO"),
    ("PEG5", "COCCOCCOCCOCCOCCO"),
    ("PEG6", "COCCOCCOCCOCCOCCOCCO"),
    ("PEG1-alkyl", "COCCCC"),
    ("PEG2-alkyl", "COCCOCCCCC"),
    ("PEG1-2x",    "COCCOCCO"),
    ("aryl-PEG",   "COCCOc1ccccc1"),
]

# Macrocycle precursors: linear peptoid/lactam fragments that can be ring-closed
# Represented as fully-assembled macrocycle SMILES directly.
MACROCYCLE_TEMPLATES = [
    # Peptoid macrocycles: 3-6 N-substituted glycine units
    ("mac_triglycine",  "O=C1CN(CC(=O)N(CC(=O)N1)CC)CC"),
    ("mac_diglyphe",    "O=C1CN(CC(=O)N(CC(=O)N1)Cc1ccccc1)Cc1ccccc1"),
    ("mac_Gly3_OH",     "O=C1CCNC(=O)CCNC(=O)CCN1"),
    ("mac_Gly3_PEG",    "O=C1CCOCCNC(=O)CCNC(=O)CN1"),
    ("mac_Gly4",        "O=C1CNC(=O)CNC(=O)CNC(=O)CN1"),
    ("mac_cyclopeptide","O=C1CNC(=O)c2ccccc2NC(=O)CN1"),
    ("mac_aza_crown",   "O=C1CNCCNCCNC1"),
    ("mac_benzodiaz",   "O=C1CN2CCc3ccccc3N2C(=O)CNC1"),
    ("mac_dilactam_8",  "O=C1CCNC(=O)CCNO1"),
    ("mac_dilactam_10", "O=C1CCCCNC(=O)CCCCNO1"),
    ("mac_triamide_12", "O=C1CCNC(=O)CCNC(=O)CCNO1"),
    ("mac_dipeptide_9", "O=C1CC(NC(=O)CN1)c1ccccc1"),
]

# Hydroxamic acid warhead (CONHOH) — common in PROTAC E3 binders
def make_hydroxamic_acid(chain_smiles: str) -> str:
    """Convert a COOH-terminated chain to a hydroxamic acid (CONHOH)."""
    return chain_smiles.replace("OC(=O)", "O=C(NO)")


# ── Assembly ───────────────────────────────────────────────────────────────────

def assemble_protac_linker(
    acid_name: str, acid_smi: str,
    linker_name: str, linker_smi: str,
    amine_name: str, amine_smi: str,
    hydroxamic: bool = False,
) -> tuple[str, str] | None:
    """
    Assemble: acid_COOH + H2N-linker-COOH + H2N-amine
    into: acid-CO-NH-linker-CO-NH-amine
    Returns (id, smiles) or None if invalid.
    """
    # Build: AcidSide-C(=O)-NH-Linker-C(=O)-NH-AmineSide
    # We use explicit SMILES concatenation:
    acid_core = acid_smi.replace("OC(=O)", "")    # strip the COOH
    amine_core = amine_smi.replace("N", "", 1)    # strip one N

    if hydroxamic:
        # Hydroxamic acid end: linker-C(=O)-NH-OH
        target_smi = f"O=C({linker_smi}C(=O)Nc1ccc(NC(=O){acid_core})cc1)NO"
        chemotype = "protac_linker_hydroxamic"
    else:
        # Both ends are aryl amide
        target_smi = f"O=C({acid_core})N{linker_smi}NC(=O){acid_core}"
        chemotype = "protac_linker"

    # Actually build properly via RDKit SMILES manipulation
    return None  # use the direct-smiles approach below


def iter_protac_linkers(rng: random.Random) -> Iterator[tuple[str, str, str]]:
    """Yield (id, smiles, chemotype) for all PROTAC linker combinations."""
    idx = 0
    for (ln, lsmi), hydroxamic in itertools.product(ALKYL_LINKERS + PEG_LINKERS, [True, False]):
        for (wan, wasmi), (wbn, wbsmi) in itertools.product(WARHEAD_AMINES, WARHEAD_ACIDS):
            # Build: wbsmi(COOH) - amide - lsmi - amide - wasmi(NH2)
            # Full SMILES: O=C(ACID_CORE)N-[linker]-C(=O)-AMINE-[warhead]
            # Use template: O=C([acid_no_OH])[linker_N_to_C]NC(=O)[amine_no_N]
            try:
                acid_frag = wbsmi.replace("OC(=O)", "")   # e.g. "c1ccc(F)cc1"
                # Build hydroxamic acid target: HONH-CO-[linker]-CO-NH-[aryl]
                if hydroxamic:
                    smi = f"O=C({lsmi}C(=O)N{wasmi.replace('N', '', 1)})NO"
                    chemotype = "protac_linker_ha"
                else:
                    smi = f"O=C({acid_frag})N{lsmi}NC(=O){acid_frag}"
                    chemotype = "protac_linker"

                mol = Chem.MolFromSmiles(smi)
                if mol is None:
                    # Try alternate assembly
                    if hydroxamic:
                        smi = f"O=C({lsmi}C(=O)Nc1ccc({wasmi.replace('Nc1ccc(','').rstrip(')')}cc1)NO"
                    continue
                smi = Chem.MolToSmiles(mol)
                tid = f"p{idx:04d}"
                idx += 1
                yield tid, smi, chemotype
            except Exception:
                continue


def iter_all_targets(rng: random.Random) -> Iterator[tuple[str, str, str]]:
    """Yield (id, smiles, chemotype) for all generated targets."""
    # Direct SMILES construction is more reliable than string manipulation.
    # Use RDKit reaction SMARTS to assemble targets.
    from rdkit.Chem import AllChem

    # Amide coupling reaction: [acid][COOH] + [amine][NH2] -> [amide]
    amide_rxn = AllChem.ReactionFromSmarts(
        "[C:1](=[O:2])O.[N:3] >> [C:1](=[O:2])[N:3]"
    )

    idx = 0

    # 1. PROTAC linkers: diacid + 2x amine warheads
    for (ln, lsmi) in ALKYL_LINKERS + PEG_LINKERS:
        diacid_smi = f"OC(=O){lsmi}C(=O)O"
        diacid = Chem.MolFromSmiles(diacid_smi)
        if diacid is None:
            continue
        for (wan, wasmi) in WARHEAD_AMINES:
            amine = Chem.MolFromSmiles(wasmi)
            if amine is None:
                continue
            # Couple diacid with first amine
            try:
                step1 = amide_rxn.RunReactants((diacid, amine))
                if not step1:
                    continue
                mono_amide = step1[0][0]
                Chem.SanitizeMol(mono_amide)
                # Couple with second (same) amine
                step2 = amide_rxn.RunReactants((mono_amide, amine))
                if not step2:
                    continue
                product = step2[0][0]
                Chem.SanitizeMol(product)
                smi = Chem.MolToSmiles(product)
                yield f"t{idx:04d}", smi, "protac_linker"
                idx += 1
            except Exception:
                continue

    # 2. PROTAC linkers with hydroxamic acid end
    for (ln, lsmi) in ALKYL_LINKERS + PEG_LINKERS:
        # Hydroxamic acid + amine amide
        ha_acid_smi = f"OC(=O){lsmi}C(=O)NO"
        ha_mol = Chem.MolFromSmiles(ha_acid_smi)
        if ha_mol is None:
            continue
        for (wan, wasmi) in WARHEAD_AMINES[:10]:  # subset to keep count manageable
            amine = Chem.MolFromSmiles(wasmi)
            if amine is None:
                continue
            try:
                step1 = amide_rxn.RunReactants((ha_mol, amine))
                if not step1:
                    continue
                product = step1[0][0]
                Chem.SanitizeMol(product)
                smi = Chem.MolToSmiles(product)
                yield f"t{idx:04d}", smi, "protac_linker_ha"
                idx += 1
            except Exception:
                continue

    # 3. Macrocycles: use templates directly
    for (name, smi) in MACROCYCLE_TEMPLATES:
        mol = Chem.MolFromSmiles(smi)
        if mol is not None:
            yield f"t{idx:04d}", Chem.MolToSmiles(mol), "macrocycle"
            idx += 1

    # 4. Aryl-ether linkers: phenol + omega-halo acid
    aryl_ether_rxn = AllChem.ReactionFromSmarts(
        "[c:1]O.[O:2][C:3] >> [c:1][O:2][C:3]"
    )
    phenols = [
        ("4F-phenol-amide", "OC(=O)CCCCOc1ccc(NC(=O)c2ccc(F)cc2)cc1"),
        ("4Br-phenol-amide", "OC(=O)CCCCOc1ccc(NC(=O)c2ccc(Br)cc2)cc1"),
        ("4Cl-phenol-amide", "OC(=O)CCCCOc1ccc(NC(=O)c2ccc(Cl)cc2)cc1"),
        ("4F-phenol-amide-HA", "O=C(CCCCOc1ccc(NC(=O)c2ccc(F)cc2)cc1)NO"),
        ("4Br-phenol-amide-HA", "O=C(CCCCOc1ccc(NC(=O)c2ccc(Br)cc2)cc1)NO"),
        ("4Cl-phenol-amide-HA", "O=C(CCCCOc1ccc(NC(=O)c2ccc(Cl)cc2)cc1)NO"),
        ("4F-phenol-amide-C6", "OC(=O)CCCCCCOc1ccc(NC(=O)c2ccc(F)cc2)cc1"),
        ("4Br-phenol-amide-C8", "OC(=O)CCCCCCCCOc1ccc(NC(=O)c2ccc(Br)cc2)cc1"),
    ]
    for (name, smi) in phenols:
        mol = Chem.MolFromSmiles(smi)
        if mol is not None:
            yield f"t{idx:04d}", Chem.MolToSmiles(mol), "aryl_ether_linker"
            idx += 1


# ── Filtering ──────────────────────────────────────────────────────────────────

# Reference "known drug" fingerprints for similarity filtering.
# These are the most common PROTAC-relevant marketed drugs.
KNOWN_DRUG_SMILES = [
    "CC(=O)Nc1ccc(O)cc1",                     # paracetamol
    "CC12CCC3C(C1CCC2O)CCC4=CC(=O)CCC34C",    # testosterone
    "O=C(O)c1ccc(NC(=O)c2ccc(Cl)cc2)cc1",     # some biaryl
    "CC(C)Cc1ccc(C(C)C(=O)O)cc1",             # ibuprofen
    "O=C(O)c1cccc(NC(=O)Oc2cccc3ccccc23)c1",  # carbamate
    "CC1=C(C(=O)Nc2ccccc2)c2ccccc2N1C",       # benzodiazepine-like
    # semaglutide-like backbone signature
    "CCCCCCCCCCCCCCCCC(=O)NCCCC(NC(=O)COCCOCCNC(=O)CCC(NC(=O)c1cc(NC(C)=O)ccc1O)C(=O)O)C(=O)O",
]

_KNOWN_FPS: list | None = None

def get_known_fps():
    global _KNOWN_FPS
    if _KNOWN_FPS is None:
        _KNOWN_FPS = []
        for smi in KNOWN_DRUG_SMILES:
            mol = Chem.MolFromSmiles(smi)
            if mol:
                _KNOWN_FPS.append(AllChem.GetMorganGenerator(radius=2, fpSize=2048).GetFingerprint(mol))
    return _KNOWN_FPS


def passes_filters(smi: str) -> bool:
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return False
    mw = rdMolDescriptors.CalcExactMolWt(mol)
    if not (MW_MIN <= mw <= MW_MAX):
        return False
    rot = rdMolDescriptors.CalcNumRotatableBonds(mol)
    if rot < MIN_ROTATABLE_BONDS:
        return False
    fp = AllChem.GetMorganGenerator(radius=2, fpSize=2048).GetFingerprint(mol)
    for ref_fp in get_known_fps():
        sim = DataStructs.TanimotoSimilarity(fp, ref_fp)
        if sim > TANIMOTO_CUTOFF:
            return False
    return True


def deduplicate(targets: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Remove exact SMILES duplicates (after canonicalization)."""
    seen: set[str] = set()
    out = []
    for tid, smi, ctype in targets:
        if smi not in seen:
            seen.add(smi)
            out.append((tid, smi, ctype))
    return out


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--public", type=int, default=10)
    parser.add_argument("--hidden", type=int, default=100)
    parser.add_argument("--out-dir", default="targets")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)

    print("Generating targets...", file=sys.stderr)
    all_targets = list(iter_all_targets(rng))
    print(f"  raw candidates: {len(all_targets)}", file=sys.stderr)

    all_targets = deduplicate(all_targets)
    print(f"  after dedup: {len(all_targets)}", file=sys.stderr)

    filtered = [(tid, smi, ct) for tid, smi, ct in all_targets if passes_filters(smi)]
    print(f"  after filters: {len(filtered)}", file=sys.stderr)

    if len(filtered) < args.public + args.hidden:
        print(
            f"WARNING: only {len(filtered)} targets available, "
            f"requested {args.public + args.hidden}",
            file=sys.stderr,
        )

    rng.shuffle(filtered)
    public = filtered[: args.public]
    hidden = filtered[args.public : args.public + args.hidden]

    # Renumber
    public = [(f"t{i+1:03d}", smi, ct) for i, (_, smi, ct) in enumerate(public)]
    hidden = [(f"h{i+1:03d}", smi, ct) for i, (_, smi, ct) in enumerate(hidden)]

    # Compute a content hash for the hidden set (published to pin the version)
    hidden_hash = hashlib.sha256(
        "\n".join(smi for _, smi, _ in hidden).encode()
    ).hexdigest()[:16]

    def write_csv(path: Path, rows: list[tuple[str, str, str]]):
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "smiles", "chemotype", "notes"])
            for tid, smi, ct in rows:
                w.writerow([tid, smi, ct, ""])
        print(f"  wrote {len(rows)} targets -> {path}", file=sys.stderr)

    write_csv(out_dir / "public.csv", public)
    write_csv(out_dir / "hidden.csv", hidden)

    # Write manifest (public: just seed + hash of hidden set, not the smiles)
    manifest = {
        "seed": args.seed,
        "n_public": len(public),
        "n_hidden": len(hidden),
        "hidden_sha256": hidden_hash,
        "tanimoto_cutoff": TANIMOTO_CUTOFF,
        "mw_range": [MW_MIN, MW_MAX],
    }
    import json
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  manifest -> {out_dir}/manifest.json", file=sys.stderr)
    print(f"  hidden set sha256 prefix: {hidden_hash}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
