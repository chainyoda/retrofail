#!/usr/bin/env bash
set -euo pipefail

echo "Setting up RetroFail..."

if ! command -v python3 &>/dev/null; then
  echo "!! python3 not found" >&2; exit 1
fi

pip install rdkit pandas 2>/dev/null || pip install rdkit-pypi pandas 2>/dev/null

echo "Setup complete."
