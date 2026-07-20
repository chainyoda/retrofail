"""
Example coding agent that competes on RetroFail.

Uses the Claude Agent SDK to run an iterative improvement loop:
  1. Read the verifier to understand what "valid" means
  2. Run the benchmark, find failing targets
  3. Analyze failures, patch solver/solve.py
  4. Re-run, repeat until score stops improving or budget is exhausted

Run from the root of a cloned retrofail repo:
  pip install anthropic
  ANTHROPIC_API_KEY=... python agent_example.py
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import anthropic

REPO_ROOT = Path(__file__).parent
MAX_ROUNDS = 8
MODEL = "claude-opus-4-8"


def run_benchmark() -> dict:
    """Run benchmark.sh and return parsed score.json."""
    result = subprocess.run(
        ["bash", "benchmark.sh"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    score_path = REPO_ROOT / "score.json"
    if score_path.exists():
        return json.loads(score_path.read_text())
    return {"score": 0.0, "metrics": {}, "error": result.stderr[-500:]}


def get_failures() -> list[dict]:
    """Return targets the current solver fails on, with debug info."""
    import csv
    import importlib.util

    # Load solver
    spec = importlib.util.spec_from_file_location(
        "solve", REPO_ROOT / "solver" / "solve.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Load verifier
    spec2 = importlib.util.spec_from_file_location(
        "verify", REPO_ROOT / "verifier" / "verify.py"
    )
    mod2 = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod2)
    catalog = mod2.load_catalog()

    failures = []
    with open(REPO_ROOT / "targets" / "public.csv") as f:
        for row in csv.DictReader(f):
            tid, smi = row["id"], row["smiles"]
            import time
            t0 = time.time()
            route = mod.solve(smi, deadline=t0 + 10)
            elapsed = time.time() - t0
            if route is None:
                failures.append({
                    "id": tid,
                    "smiles": smi,
                    "chemotype": row.get("chemotype", ""),
                    "result": "no_route",
                    "templates_fired": [
                        name for name, rxts in mod.apply_templates(smi)
                    ],
                })
            else:
                valid, reason = mod2.validate_route(route, smi, catalog)
                if not valid:
                    failures.append({
                        "id": tid,
                        "smiles": smi,
                        "chemotype": row.get("chemotype", ""),
                        "result": "invalid_route",
                        "reason": reason,
                        "route_steps": len(route.get("steps", [])),
                    })
    return failures


def read_solver() -> str:
    return (REPO_ROOT / "solver" / "solve.py").read_text()


def write_solver(code: str):
    (REPO_ROOT / "solver" / "solve.py").write_text(code)


def compete():
    client = anthropic.Anthropic()

    print("=== RetroFail Agent ===")
    print(f"Model: {MODEL}")
    print(f"Max rounds: {MAX_ROUNDS}")
    print()

    # Read the verifier once so the agent understands validity
    verifier_src = (REPO_ROOT / "verifier" / "verify.py").read_text()
    targets_csv = (REPO_ROOT / "targets" / "public.csv").read_text()

    best_score = -1.0
    round_num = 0

    # System prompt: give the agent its role and the full context
    system = textwrap.dedent(f"""
        You are a competitive chemistry AI agent solving the RetroFail benchmark.

        Your goal: maximize the score by improving solver/solve.py.
        The score is: solve_rate + 0.10*mean_route_efficiency - 0.01*mean_wall_clock

        The verifier (which you cannot modify) checks each route:
        1. Every SMILES must canonicalize under RDKit
        2. The last step's product must equal the target (canonical match)
        3. Every leaf reactant must be in the building block catalog
        4. Route depth <= 10 steps
        5. solve() must return within 60 seconds

        VERIFIER SOURCE:
        ```python
        {verifier_src}
        ```

        PUBLIC TARGETS:
        ```
        {targets_csv}
        ```

        Each round you will receive:
        - Current solver code
        - Current score and metrics
        - List of failing targets with debug info

        Respond with ONLY a JSON object:
        {{
            "reasoning": "brief analysis of what's failing and why",
            "new_solver_code": "complete replacement for solver/solve.py"
        }}

        Rules:
        - Only modify solver/solve.py (the solve() function and helpers)
        - Do not import anything unavailable in a standard rdkit+syntheseus environment
        - The solve() function signature must stay: solve(target_smiles, deadline=None) -> dict | None
        - Return None if no route found; route dict must have "steps" key
        """).strip()

    messages = []

    while round_num < MAX_ROUNDS:
        round_num += 1
        print(f"--- Round {round_num} ---")

        # Run benchmark
        score_data = run_benchmark()
        score = score_data.get("score", 0.0)
        metrics = score_data.get("metrics", {})
        print(f"Score: {score:.4f}  solve_rate={metrics.get('solve_rate', 0):.2f}  "
              f"solved={metrics.get('solved', 0)}/{metrics.get('total', '?')}")

        if score > best_score:
            best_score = score
            print(f"  New best: {best_score:.4f}")
        elif round_num > 1:
            print(f"  No improvement (best={best_score:.4f})")

        # Get failures
        failures = get_failures()
        print(f"  Failing targets: {len(failures)}")

        if not failures:
            print("  All targets solved!")
            break

        # Build the user message for this round
        solver_code = read_solver()
        user_msg = json.dumps({
            "round": round_num,
            "current_score": score,
            "metrics": metrics,
            "failing_targets": failures[:5],  # show up to 5
            "current_solver_code": solver_code,
        }, indent=2)

        messages.append({"role": "user", "content": user_msg})

        # Ask the model what to do
        print("  Asking agent for improvements...")
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=system,
            messages=messages,
        )

        raw = response.content[-1].text.strip()
        messages.append({"role": "assistant", "content": raw})

        # Parse the response
        try:
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            proposal = json.loads(raw)
        except json.JSONDecodeError:
            # Try extracting JSON from the response
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                proposal = json.loads(match.group())
            else:
                print("  Failed to parse agent response, stopping.")
                break

        print(f"  Reasoning: {proposal.get('reasoning', '')[:120]}...")

        new_code = proposal.get("new_solver_code", "")
        if not new_code:
            print("  No new code proposed, stopping.")
            break

        # Write the new solver
        write_solver(new_code)
        print("  Updated solver/solve.py")

    print()
    print(f"=== Done. Best score: {best_score:.4f} ===")
    return best_score


if __name__ == "__main__":
    compete()
