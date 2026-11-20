#!/usr/bin/env bash
set -euo pipefail
compose=(docker compose -f compose.yaml -f compose.ci.yaml --profile worker)
cleanup() {
  if [ "${E2E_FAILED:-false}" = true ]; then
    "${compose[@]}" logs --no-color --tail 100 prefect-ci worker gateway || true
  fi
  "${compose[@]}" down --volumes || true
}
trap 'E2E_FAILED=true' ERR
trap cleanup EXIT
"${compose[@]}" config --quiet
"${compose[@]}" build gateway worker prefect-ci
"${compose[@]}" up -d --wait prefect-ci
"${compose[@]}" run --rm --no-deps worker prefect work-pool create nas-local --type process
"${compose[@]}" run --rm --no-deps worker prefect deploy --all
"${compose[@]}" up -d worker gateway
ready=false
for attempt in $(seq 1 40); do
  if curl --fail --silent --max-time 4 http://127.0.0.1:8099/readyz; then
    ready=true
    break
  fi
  sleep 2
done
if [ "$ready" != true ]; then echo "Gateway not ready"; exit 1; fi
run_id=$(curl --fail --silent --show-error \
  -X POST http://127.0.0.1:8099/v1/jobs/nas-health \
  -H "X-Automation-Key: $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"parameters\":{},\"idempotency_key\":\"ci-health-${GITHUB_RUN_ID:-local}\"}" \
  | jq -r '.flow_run_id')
if [ -z "$run_id" ] || [ "$run_id" = "null" ]; then echo "No Flow Run ID"; exit 1; fi
"${compose[@]}" run --rm --no-deps worker python scripts/check_flow_run.py "$run_id" \
  --api-url http://prefect-ci:4200/api --timeout 120 --interval 3
echo "PASS: real Docker Prefect Server, Gateway, Process Worker and completed Flow Run"
