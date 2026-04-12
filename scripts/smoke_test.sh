#!/usr/bin/env bash
# scripts/smoke_test.sh
#
# Operability smoke test for TFP Demo Node.
#
# Usage:
#   ./scripts/smoke_test.sh [BASE_URL]
#
# Defaults to http://localhost:8000.
# Exits 0 when all checks pass, 1 on the first failure.
#
# The script can be used in two modes:
#   1. Against a running node (start uvicorn separately):
#        uvicorn tfp_demo.server:app --port 8000 &
#        ./scripts/smoke_test.sh
#   2. Self-contained (starts its own server):
#        cd tfp-foundation-protocol && ./scripts/smoke_test.sh
#
# The --ops-only flag skips the E2E lifecycle check and only validates
# the operational surface (health, metrics, admin, status, docs, tasks,
# devices).

set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
OPS_ONLY="${SMOKE_OPS_ONLY:-0}"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { printf "${GREEN}  ✓${NC} %s\n" "$*"; }
fail() { printf "${RED}  ✗${NC} %s\n" "$*"; exit 1; }
info() { printf "${YELLOW}  →${NC} %s\n" "$*"; }

# ── Dependency check ─────────────────────────────────────────────────────────
if ! command -v curl &>/dev/null; then
  fail "curl is required but not installed"
fi
if ! command -v python3 &>/dev/null; then
  fail "python3 is required but not installed"
fi

# ── Helpers ───────────────────────────────────────────────────────────────────

check_status() {
  local label="$1" url="$2" expected="${3:-200}"
  local actual
  actual=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  if [ "$actual" = "$expected" ]; then
    pass "$label → HTTP $actual"
  else
    fail "$label → expected HTTP $expected, got $actual ($url)"
  fi
}

get_json() {
  curl -s "$1"
}

post_json() {
  local url="$1" body="$2"
  shift 2
  curl -s -X POST "$url" -H "Content-Type: application/json" "$@" -d "$body"
}

hmac_sha256() {
  # hmac_sha256 <hex_key> <message>  → hex digest
  python3 - "$1" "$2" <<'EOF'
import sys, hmac, hashlib
key = bytes.fromhex(sys.argv[1])
msg = sys.argv[2].encode()
print(hmac.new(key, msg, hashlib.sha256).hexdigest())
EOF
}

# ── Operational surface checks ────────────────────────────────────────────────

echo ""
info "=== Operational surface checks against $BASE_URL ==="

check_status "GET /health"      "$BASE_URL/health"
check_status "GET /api/status"  "$BASE_URL/api/status"
check_status "GET /metrics"     "$BASE_URL/metrics"
check_status "GET /admin"       "$BASE_URL/admin"
check_status "GET /docs"        "$BASE_URL/docs"
check_status "GET /api/tasks"   "$BASE_URL/api/tasks"
check_status "GET /api/devices" "$BASE_URL/api/devices"
check_status "GET /api/content" "$BASE_URL/api/content"

# health must contain {"status":"ok"}
HEALTH=$(get_json "$BASE_URL/health")
echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='ok', d" \
  && pass "/health status field is 'ok'" \
  || fail "/health status field is not 'ok': $HEALTH"

# /metrics must include at least the 12 counters
METRICS=$(curl -s "$BASE_URL/metrics")
COUNTER_COUNT=$(echo "$METRICS" | grep -c "^tfp_" || true)
if [ "$COUNTER_COUNT" -ge 12 ]; then
  pass "/metrics exposes $COUNTER_COUNT counters (≥12 required)"
else
  fail "/metrics exposes only $COUNTER_COUNT counters (need ≥12)"
fi

# /api/status must have version and supply_cap
STATUS=$(get_json "$BASE_URL/api/status")
echo "$STATUS" | python3 -c "
import sys,json
d=json.load(sys.stdin)
assert 'version' in d, 'missing version'
assert 'supply_cap' in d, 'missing supply_cap'
assert d['supply_cap'] == 21000000, f'wrong supply_cap: {d[\"supply_cap\"]}'
" && pass "/api/status has version + supply_cap=21000000" \
  || fail "/api/status malformed: $STATUS"

if [ "$OPS_ONLY" = "1" ]; then
  echo ""
  info "=== --ops-only mode: skipping E2E lifecycle ==="
  echo ""
  pass "All operational surface checks passed ✓"
  exit 0
fi

# ── E2E lifecycle smoke test ──────────────────────────────────────────────────

echo ""
info "=== E2E lifecycle smoke test ==="

# Generate random PUF entropy
PUF_HEX=$(python3 -c "import os; print(os.urandom(32).hex())")
DEVICE_ID="smoke-device-$(python3 -c 'import random,string; print("".join(random.choices(string.ascii_lowercase,k=6)))')"
info "Using device_id: $DEVICE_ID"

# Enroll
ENROLL=$(post_json "$BASE_URL/api/enroll" \
  "{\"device_id\":\"$DEVICE_ID\",\"puf_entropy_hex\":\"$PUF_HEX\"}")
echo "$ENROLL" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['enrolled']==True" \
  && pass "Enroll device" \
  || fail "Enroll failed: $ENROLL"

# Publish content
TITLE="Smoke Test $(date +%s)"
PUB_SIG=$(hmac_sha256 "$PUF_HEX" "${DEVICE_ID}:${TITLE}")
PUBLISH=$(post_json "$BASE_URL/api/publish" \
  "{\"title\":\"$TITLE\",\"text\":\"Smoke test content body.\",\"tags\":[\"smoke\"],\"device_id\":\"$DEVICE_ID\"}" \
  -H "X-Device-Sig: $PUB_SIG")
ROOT_HASH=$(echo "$PUBLISH" | python3 -c "import sys,json; print(json.load(sys.stdin)['root_hash'])" 2>/dev/null || echo "")
if [ ${#ROOT_HASH} -eq 64 ]; then
  pass "Publish content → root_hash=$ROOT_HASH"
else
  fail "Publish failed: $PUBLISH"
fi

# Earn credits
TASK_ID="smoke-task-$(date +%s)"
EARN_SIG=$(hmac_sha256 "$PUF_HEX" "${DEVICE_ID}:${TASK_ID}")
EARN=$(post_json "$BASE_URL/api/earn" \
  "{\"device_id\":\"$DEVICE_ID\",\"task_id\":\"$TASK_ID\"}" \
  -H "X-Device-Sig: $EARN_SIG")
CREDITS=$(echo "$EARN" | python3 -c "import sys,json; print(json.load(sys.stdin).get('credits_earned',0))" 2>/dev/null || echo "0")
if [ "$CREDITS" -gt 0 ] 2>/dev/null; then
  pass "Earn credits → credits_earned=$CREDITS"
else
  fail "Earn failed: $EARN"
fi

# Retrieve content
GET=$(curl -s "$BASE_URL/api/get/$ROOT_HASH?device_id=$DEVICE_ID")
echo "$GET" | python3 -c "
import sys,json
d=json.load(sys.stdin)
assert 'text' in d, f'no text field: {d}'
assert d['root_hash'] == '$ROOT_HASH', f'wrong hash: {d}'
" && pass "Retrieve content → text returned" \
  || fail "Retrieve failed: $GET"

# Task lifecycle — create a task
CREATE_TASK=$(post_json "$BASE_URL/api/task" \
  '{"task_type":"content_verify","difficulty":1,"seed_hex":""}')
TASK_ID2=$(echo "$CREATE_TASK" | python3 -c "import sys,json; print(json.load(sys.stdin)['task_id'])" 2>/dev/null || echo "")
if [ -n "$TASK_ID2" ]; then
  pass "Create task → task_id=$TASK_ID2"
else
  fail "Create task failed: $CREATE_TASK"
fi

# Verify task appears in open pool
TASKS=$(get_json "$BASE_URL/api/tasks")
echo "$TASKS" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ids=[t['task_id'] for t in d.get('tasks',[])]
assert '$TASK_ID2' in ids, f'task $TASK_ID2 not in open pool: {ids}'
" && pass "Task $TASK_ID2 visible in open pool" \
  || fail "Task not in pool: $TASKS"

# Verify device appears in leaderboard
DEVICES=$(get_json "$BASE_URL/api/devices")
echo "$DEVICES" | python3 -c "
import sys,json
d=json.load(sys.stdin)
assert d['total_enrolled'] >= 1
" && pass "Device leaderboard has ≥1 enrolled device" \
  || fail "Leaderboard empty: $DEVICES"

echo ""
pass "=== All smoke tests passed ✓ ==="
