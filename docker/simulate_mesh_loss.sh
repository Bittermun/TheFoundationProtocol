#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

# Simulates realistic rural / disaster wireless mesh impairments using Linux Traffic Control (tc netem).
# Injects 25% packet loss, 35ms +/- 10ms latency jitter, 2% packet duplication, and 0.5% packet corruption.

INTERFACE="${1:-eth0}"
LOSS_RATE="${2:-25%}"
DELAY_MS="${3:-35ms}"
JITTER_MS="${4:-10ms}"

echo "=========================================================="
echo " The Foundation Protocol (TFP v4.0) Network Impairment Tool"
echo " Target Interface: ${INTERFACE}"
echo " Loss Rate:        ${LOSS_RATE}"
echo " Latency / Jitter: ${DELAY_MS} +/- ${JITTER_MS}"
echo "=========================================================="

# Reset existing qdisc rules
tc qdisc del dev "${INTERFACE}" root 2>/dev/null || true

# Apply netem impairment queue
tc qdisc add dev "${INTERFACE}" root netem \
    loss "${LOSS_RATE}" \
    delay "${DELAY_MS}" "${JITTER_MS}" distribution normal \
    duplicate 2% \
    corrupt 0.5%

echo "[OK] Linux Traffic Control (netem) active on ${INTERFACE}:"
tc -s qdisc show dev "${INTERFACE}"
echo "=========================================================="
