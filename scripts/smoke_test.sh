#!/usr/bin/env bash
# Whole-stack smoke test in Docker. Needs: docker + curl + python3. Cleans up after itself.
#   ./scripts/smoke_test.sh            # build, start, assert, tear down
#   KEEP=1 ./scripts/smoke_test.sh     # leave the stack running afterwards
set -uo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f infra/docker-compose.smoke.yml)
API=http://127.0.0.1:8300; UI=http://127.0.0.1:3300
Q="start_date=2026-03-01&end_date=2026-03-03&attribution_model=M1&lookback_days=7"
FAILS=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILS=$((FAILS+1)); }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
expect_code() { local want=$1 label=$2; shift 2; local got; got=$(code "$@"); [ "$got" = "$want" ] && ok "$label ($got)" || bad "$label (wanted $want, got $got)"; }
cleanup() { [ "${KEEP:-0}" = "1" ] || "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1; }
trap cleanup EXIT

echo "== build & start (warehouse -> fixtures+dbt -> api -> dashboard)"
"${COMPOSE[@]}" up -d --build --wait --wait-timeout 300 || { "${COMPOSE[@]}" logs --tail 60; echo "stack failed to become healthy"; exit 1; }

echo "== API"
expect_code 200 "health is public" "$API/health"
expect_code 401 "API requires credentials" "$API/api/v1/overview?$Q"
expect_code 401 "wrong password rejected" -u smoke:wrong "$API/api/v1/overview?$Q"
expect_code 200 "valid credentials accepted" -u smoke:smoke-api-password "$API/api/v1/overview?$Q"
expect_code 404 "docs disabled outside local" "$API/docs"
expect_code 400 "sort-column injection rejected" -u smoke:smoke-api-password "$API/api/v1/products?$Q&sort=spend;drop%20table%20x"
expect_code 400 "unknown host header rejected" -H 'Host: evil.example.com' "$API/health"
OV=$(curl -s -u smoke:smoke-api-password "$API/api/v1/overview?$Q")
python3 - "$OV" <<'PY' && ok "overview reads the dbt-built mart: source=redshift, spend=650, revenue=230, ROAS=230/650" || bad "overview content wrong"
import json, sys
d = json.loads(sys.argv[1]); k = d["kpis"]
assert d["meta"]["data_source"] == "redshift" and d["meta"]["env"] == "staging", d["meta"]
assert abs(k["spend"]["value"] - 650) < 1e-6 and abs(k["revenue"]["value"] - 230) < 1e-6
assert abs(k["roas"]["value"] - 230 / 650) < 1e-9 and abs(d["unallocated_spend"] - 9) < 1e-6
PY
PR=$(curl -s -u smoke:smoke-api-password "$API/api/v1/products?$Q&sort=spend&order=desc")
python3 - "$PR" <<'PY' && ok "products: 4 SKUs, SKU-A first (spend 310)" || bad "products content wrong"
import json, sys
d = json.loads(sys.argv[1]); assert d["total"] == 4 and d["data"][0]["retailer_id"] == "SKU-A" and abs(d["data"][0]["spend"] - 310) < 1e-6
PY

echo "== fail-closed configuration"
if "${COMPOSE[@]}" run --rm --no-deps -e APP_AUTH_METHOD=none backend python -c "from backend.main import create_app; create_app()" >/dev/null 2>&1; then
  bad "backend started with auth disabled in ENV=staging"; else ok "backend REFUSES to start with APP_AUTH_METHOD=none outside local"; fi
if "${COMPOSE[@]}" run --rm --no-deps -e DATA_SOURCE=demo backend python -c "from backend.main import create_app; create_app()" >/dev/null 2>&1; then
  bad "backend started with demo data in ENV=staging"; else ok "backend REFUSES demo data outside local"; fi

echo "== dashboard"
expect_code 200 "liveness probe is public" "$UI/healthz"
expect_code 401 "dashboard requires login" "$UI/overview"
expect_code 401 "proxy requires login" "$UI/api/proxy/api/v1/overview?$Q"
expect_code 200 "dashboard loads with valid login" -u smoke:smoke-ui-password "$UI/overview"
expect_code 200 "proxied API call works (server holds the API credentials)" -u smoke:smoke-ui-password "$UI/api/proxy/api/v1/overview?$Q"
expect_code 404 "proxy blocks non-allow-listed backend paths" -u smoke:smoke-ui-password "$UI/api/proxy/docs"
expect_code 405 "proxy is GET-only" -u smoke:smoke-ui-password -X POST "$UI/api/proxy/api/v1/overview"
HDR=$(curl -s -D - -o /dev/null -u smoke:smoke-ui-password "$UI/overview")
echo "$HDR" | grep -qi '^x-frame-options: DENY' && ok "security headers on pages" || bad "security headers missing"
LEAK=$(curl -s -u smoke:smoke-ui-password "$UI/overview" "$UI/api/proxy/api/v1/overview?$Q" | grep -c 'smoke-api-password' || true)
[ "$LEAK" = "0" ] && ok "API credentials never reach the browser" || bad "API password leaked into a response"

echo
if [ "$FAILS" = "0" ]; then echo "SMOKE TEST PASSED"; else echo "SMOKE TEST FAILED ($FAILS)"; "${COMPOSE[@]}" logs --tail 40 backend frontend; exit 1; fi
