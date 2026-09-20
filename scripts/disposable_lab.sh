#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors
# Runs The Foundation Protocol disposable verification lab inside an isolated Docker sandbox.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SCENARIO="${1:-all}"
EXTRA_ARGS="${@:2}"

echo "============================================================"
echo "  The Foundation Protocol: Disposable Verification Sandbox"
echo "============================================================"
echo "  Scenario : ${SCENARIO}"
echo "  Mounts   : Read-only code, tmpfs RAM database (/tmp)"
echo "============================================================"

cd "${REPO_ROOT}"
docker compose -f docker-compose.disposable.yml run --rm disposable-lab \
    python scripts/run_experiment.py --scenario "${SCENARIO}" ${EXTRA_ARGS}
