#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
mkdir -p cache data/inputs data/outputs
docker compose up --build -d
echo "Boltz-2 is starting at http://127.0.0.1:${BOLTZ_PORT:-8000}"
echo "Follow logs with: docker compose logs -f"

