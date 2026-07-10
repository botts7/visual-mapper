#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_CMD=(python3.11)
elif command -v py >/dev/null 2>&1; then
  PYTHON_CMD=(py -3.11)
else
  echo "Python 3.11 not found. Install it or set PYTHON_CMD manually." >&2
  exit 1
fi

"${PYTHON_CMD[@]}" -m pip install -r backend/requirements.txt -c backend/constraints-3.11.txt
"${PYTHON_CMD[@]}" -m pytest tests/test_api.py tests/test_beta3_fixes.py tests/test_auth.py
