#!/usr/bin/env bash
set -euo pipefail
compose=(docker compose -f compose.yaml)
cleanup() {
  if [ "${E2E_FAILED:-false}" = true ]; then
    "${compose[@]}" logs --no-color --tail 100 n8n n8n-db || true
  fi
  "${compose[@]}" down --volumes || true
}
trap 'E2E_FAILED=true' ERR
trap cleanup EXIT

"${compose[@]}" config --quiet
"${compose[@]}" up -d n8n
ready=false
for attempt in $(seq 1 60); do
  if curl --fail --silent --max-time 4 http://127.0.0.1:5678/healthz; then
    ready=true
    break
  fi
  sleep 3
done
if [ "$ready" != true ]; then echo "n8n did not become healthy"; exit 1; fi
"${compose[@]}" cp n8n/workflows/github-digest.json n8n:/tmp/github-digest.json
"${compose[@]}" exec -T n8n n8n import:workflow --input=/tmp/github-digest.json
"${compose[@]}" exec -T n8n n8n export:workflow --all --output=/tmp/exported-workflows.json
"${compose[@]}" cp n8n:/tmp/exported-workflows.json /tmp/ci-n8n-exported.json
grep -q 'Daily GitHub project digest' /tmp/ci-n8n-exported.json

"${compose[@]}" exec -T n8n-db pg_dump --no-owner --no-privileges -U n8n -d n8n > /tmp/ci-n8n-backup.sql
test -s /tmp/ci-n8n-backup.sql
"${compose[@]}" exec -T n8n-db createdb -U n8n n8n_restore_test
"${compose[@]}" exec -T n8n-db psql -v ON_ERROR_STOP=1 -U n8n -d n8n_restore_test < /tmp/ci-n8n-backup.sql
original_tables=$("${compose[@]}" exec -T n8n-db psql -U n8n -d n8n -Atc "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
restored_tables=$("${compose[@]}" exec -T n8n-db psql -U n8n -d n8n_restore_test -Atc "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
test "$original_tables" -gt 0
test "$original_tables" = "$restored_tables"
echo "PASS: n8n startup, workflow import/export, PostgreSQL logical dump/restore"
