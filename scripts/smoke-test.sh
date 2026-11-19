#!/usr/bin/env bash
set -euo pipefail
: "${GATEWAY_API_KEY:?Export GATEWAY_API_KEY before testing}"
BASE="${GATEWAY_BASE_URL:-http://127.0.0.1:8099}"
curl --fail --silent --show-error "${BASE}/healthz"
printf '\n'
curl --fail --silent --show-error \
  -H "X-Automation-Key: ${GATEWAY_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"parameters":{},"idempotency_key":"manual-nas-health-001"}' \
  "${BASE}/v1/jobs/nas-health"
printf '\n'
