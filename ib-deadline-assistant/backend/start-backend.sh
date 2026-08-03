#!/usr/bin/env bash
set -euo pipefail

backend_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$backend_dir"

if [[ -x "$backend_dir/venv/Scripts/python.exe" ]]; then
  python_bin="$backend_dir/venv/Scripts/python.exe"
elif [[ -x "$backend_dir/venv/bin/python" ]]; then
  python_bin="$backend_dir/venv/bin/python"
else
  echo "Backend virtual environment was not found in: $backend_dir/venv" >&2
  exit 1
fi

exec "$python_bin" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
