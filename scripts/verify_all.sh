#!/usr/bin/env bash
# One command to reproduce every automated check.   ./scripts/verify_all.sh [--with-docker]
# Needs: Python 3.11+ venv with `pip install -e ".[dev]"`, Node 22, a Postgres reachable at TEST_PG_DSN
# (default: local roi_hunter_ci — see README), Google Chrome for the e2e step. Integration tests skip if no Postgres.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PY="${PYTHON:-.venv/bin/python}"; FAIL=0
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; shift; if "$@"; then printf '\033[32mOK\033[0m\n'; else printf '\033[31mFAILED\033[0m\n'; FAIL=1; fi; }

step "python compile"            "$PY" -m compileall -q backend ingestion pipeline scripts
step "ruff"                      "$PY" -m ruff check .
step "bandit (medium+)"          bash -c "$PY -m bandit -q -r backend ingestion pipeline scripts -ll -c pyproject.toml 2>/dev/null"
step "mypy (typed defs)"         "$PY" -m mypy backend pipeline ingestion --exclude tests
step "pytest + coverage >= 85%"  "$PY" -m pytest -q -W ignore --cov --cov-fail-under=85
step "dbt build (models, tests, attribution unit tests) on fixtures" bash -c "$PY -m ingestion.testing.fixtures >/dev/null && cd transform && mkdir -p /tmp/dbtprof_v && cp profiles.ci.yml /tmp/dbtprof_v/profiles.yml && ../.venv/bin/dbt deps --profiles-dir /tmp/dbtprof_v >/dev/null 2>&1; ../.venv/bin/dbt build --full-refresh --profiles-dir /tmp/dbtprof_v --vars '{min_spend_for_classification: 50, target_roas: 0.4, high_spend_percentile: 0.5}' 2>&1 | tail -3"
(
  cd frontend || exit 1
  step "frontend: regenerate API types" env PYTHON="$ROOT/$PY" npm run gen:api
  step "frontend: typecheck"     npm run typecheck
  step "frontend: lint"          npm run lint
  step "frontend: unit tests"    npm test
  step "frontend: production build" npm run build
  step "frontend: e2e (Chrome, real API + dashboard)" env PYTHON="$ROOT/$PY" npx playwright test
  exit "$FAIL"
) || FAIL=1
if [ "${1:-}" = "--with-docker" ]; then step "docker smoke (whole stack)" ./scripts/smoke_test.sh; fi
echo; [ "$FAIL" = "0" ] && echo "ALL CHECKS PASSED" || { echo "SOME CHECKS FAILED"; exit 1; }
