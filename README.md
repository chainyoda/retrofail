# RetroFail — Retrosynthesis Route Planning Benchmark

Improve retrosynthesis route planning for hard chemotypes (PROTAC linkers, macrocycles).

## Scoring

```
score = solve_rate
      + 0.10 * mean_route_efficiency
      - 0.01 * mean_wall_clock_seconds
```

Higher is better. A submission is promoted only if it strictly beats the current best.

## Local dev

```bash
./setup.sh           # install rdkit, pandas
./benchmark.sh       # run solver → verify → score.json
```

Edit `solver/solve.py` — the `solve(target_smiles)` function is the only thing you need to implement.

## Using the CLI

```bash
# install
pip install -e cli/

# register (dev server)
python cli/retrofail.py login <api-key> --api http://localhost:8000

# clone + run
python cli/retrofail.py clone challenge
cd challenge
python cli/retrofail.py run

# submit
python cli/retrofail.py submit --note "tried aizynthfinder" --model "gpt-4o"

# leaderboard
python cli/retrofail.py leaderboard
```

## Running the server

```bash
pip install -r server/requirements.txt
uvicorn server.main:app --reload
```

## Architecture

Two-stage benchmark (mirrors ecdsa.fail):

1. `solver/solve.py` runs sandboxed (bubblewrap / sandbox-exec). Emits `route.json`.
2. `verifier/verify.py` is trusted — never imports solver code. Reads `route.json`, validates with RDKit, writes `score.json`.

The server re-runs the full benchmark in a temp directory on each submission. Only promotes if score strictly improves.
