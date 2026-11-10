#!/usr/bin/env bash
# Build a clean zip for sharing: no secrets, caches, venvs, node_modules, build output, test artefacts or dbt artefacts.
#   ./scripts/package_for_review.sh [output.zip]
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-../roi-hunter-review.zip}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
[ -f .env ] && { echo "REFUSING: .env exists in repo root — remove/rename it first"; exit 1; }
[ -f frontend/.env.local ] && { echo "REFUSING: frontend/.env.local exists — remove/rename it first"; exit 1; }
rm -f "$OUT"
zip -qr "$OUT" . \
  -x ".venv/*" "*/node_modules/*" "node_modules/*" "frontend/.next/*" "frontend/.next-e2e/*" "frontend/test-results/*" \
     "frontend/playwright-report/*" "*/__pycache__/*" "__pycache__/*" ".pytest_cache/*" ".ruff_cache/*" ".mypy_cache/*" \
     ".coverage" ".coverage.*" "htmlcov/*" "transform/target/*" "transform/dbt_packages/*" "transform/logs/*" \
     "transform/profiles.yml" "*.DS_Store" ".env" ".env.local" "frontend/.env.local" "frontend/tsconfig.tsbuildinfo" "*.zip"
echo "Wrote $OUT"
unzip -l "$OUT" | tail -1
# sanity: nothing sensitive or bulky slipped in
if unzip -l "$OUT" | grep -E "node_modules|\.venv/|\.next/|__pycache__|[ /]\.env$|[ /]\.env\.local$|[ /]profiles\.yml$"; then
  echo "ERROR: unwanted files in archive"; exit 1
fi
