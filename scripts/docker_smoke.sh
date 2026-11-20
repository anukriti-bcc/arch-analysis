#!/usr/bin/env bash
# Smoke test for the Docker setup. Run AFTER:   docker compose up -d --build
# Checks: the API is healthy and uses PostgreSQL; an analysis can be created; it survives a restart of the backend container.
# Usage:  bash scripts/docker_smoke.sh            (needs docker, curl and python3 on the host)
set -u
API="${API:-http://localhost:8000}"
UI="${UI:-http://localhost:5173}"
pass=0; fail=0
ok()   { echo "PASS  $1"; pass=$((pass+1)); }
bad()  { echo "FAIL  $1"; fail=$((fail+1)); }
json() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

echo "Waiting for the API (up to 90 s) ..."
for i in $(seq 1 45); do curl -fs "$API/health" >/dev/null 2>&1 && break; sleep 2; done

health=$(curl -fs "$API/health") || { bad "API not reachable at $API (run: docker compose logs backend)"; echo "$pass passed, $fail failed"; exit 1; }
[ "$(echo "$health" | json "d['storage']['backend']")" = "postgresql" ] && ok "backend uses PostgreSQL" || bad "backend is not on PostgreSQL: $health"
[ "$(echo "$health" | json "d['storage']['ok']")" = "True" ] && ok "database answers" || bad "database does not answer: $health"

body=$(curl -fs -X POST "$API/repositories/analyze" -H 'Content-Type: application/json' \
  -d '{"repository_path":"../datasets/sample-ecommerce","architecture_file":"../datasets/sample-ecommerce/architecture/rules.yaml"}') || body=""
aid=$(echo "$body" | json "d['analysis_id']")
[ -n "$aid" ] && ok "analysis created ($aid)" || bad "analysis failed (is ./datasets mounted? docker compose logs backend)"
n_before=$(curl -fs "$API/analysis" | json "len(d)")

echo "Restarting the backend container ..."
docker compose restart backend >/dev/null 2>&1
for i in $(seq 1 45); do curl -fs "$API/health" >/dev/null 2>&1 && break; sleep 2; done
n_after=$(curl -fs "$API/analysis" | json "len(d)")
[ -n "$aid" ] && [ "$n_after" = "$n_before" ] && [ "${n_after:-0}" -ge 1 ] && ok "analysis list survived the restart ($n_after run(s))" || bad "runs were lost on restart (before=$n_before after=$n_after)"
curl -fs "$API/analysis/$aid" >/dev/null 2>&1 && ok "the stored run can be read back" || bad "the stored run cannot be read back"

curl -fs "$UI" | grep -qi "<div id=\"root\"" && ok "UI served at $UI" || bad "UI not served at $UI (docker compose logs frontend)"
echo; echo "$pass passed, $fail failed"; [ "$fail" -eq 0 ]
