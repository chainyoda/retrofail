#!/usr/bin/env bash
# Two-stage benchmark: untrusted build then trusted eval (mirrors ecdsa.fail pattern).
# Stage 1: run solver (UNTRUSTED) in a sandbox, emit route.json
# Stage 2: run verifier (TRUSTED) against route.json, emit score.json
set -euo pipefail

rm -f route.json score.json

SOLVER_DIR="$(pwd)/solver"
# Allow server to override with hidden targets via env var
TARGETS_FILE="${TARGETS_FILE:-$(pwd)/targets/public.csv}"
SCRATCH="$(mktemp -d)"

cleanup() { rm -rf "${SCRATCH}"; }
trap cleanup EXIT

# Stage 1 — run solver (sandboxed on Linux, fallback on macOS/dev)
solver_bin="python3 ${SOLVER_DIR}/solve.py"

if command -v bwrap &>/dev/null; then
  bwrap \
    --ro-bind / / --dev /dev \
    --bind "${SCRATCH}" "${SCRATCH}" --chdir "${SCRATCH}" \
    --setenv TMPDIR "${SCRATCH}" \
    --setenv TARGETS_FILE "${TARGETS_FILE}" \
    --setenv SOLVER_DIR "${SOLVER_DIR}" \
    --unshare-net --unshare-ipc \
    --cap-drop ALL --new-session \
    -- python3 "${SOLVER_DIR}/solve.py" \
    > "${SCRATCH}/route.json"
elif [[ "$(uname -s)" == "Darwin" ]] && command -v sandbox-exec &>/dev/null; then
  profile="(version 1)(allow default)(deny file-write*)(allow file-write* (subpath \"${SCRATCH}\"))(deny network*)"
  sandbox-exec -p "${profile}" \
    /bin/bash -c "cd \"${SCRATCH}\" && TARGETS_FILE=\"${TARGETS_FILE}\" SOLVER_DIR=\"${SOLVER_DIR}\" python3 \"${SOLVER_DIR}/solve.py\"" \
    > "${SCRATCH}/route.json"
else
  echo "!! no sandbox available; running solver UNCONFINED (dev only)" >&2
  TARGETS_FILE="${TARGETS_FILE}" SOLVER_DIR="${SOLVER_DIR}" \
    python3 "${SOLVER_DIR}/solve.py" > "${SCRATCH}/route.json"
fi

if [[ ! -s "${SCRATCH}/route.json" ]]; then
  echo "!! solver produced no output" >&2; exit 1
fi

cp "${SCRATCH}/route.json" ./route.json

# Stage 2 — trusted verifier (never imports solver code)
python3 verifier/verify.py --routes route.json --targets "${TARGETS_FILE}" --output score.json

cat score.json
