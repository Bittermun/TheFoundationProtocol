#!/usr/bin/env bash
# TFP v2.2 Simulation Runner — see README.md for prerequisites
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "═══════════════════════════════════════════════════"
echo " TFP v2.2 Simulation Runner"
echo "═══════════════════════════════════════════════════"

echo ""
echo "▶ Running Python attack injection simulator..."
cd "$PROJECT_ROOT"
python tfp_simulator/attack_inject.py --seed 42 --requests 500
PYTHON_EXIT=$?

if command -v ns3 &>/dev/null; then
    echo ""
    echo "▶ Running ns-3 simulation..."
    NS3_DIR="${NS3_DIR:-$HOME/ns-3-dev}"
    cp "$SCRIPT_DIR/ns3_tfp_sim.cc" "$NS3_DIR/scratch/tfp_sim.cc"
    cd "$NS3_DIR"
    ./ns3 build scratch/tfp_sim && ./ns3 run scratch/tfp_sim
else
    echo ""
    echo "⚠  ns3 not found in PATH — skipping C++ simulation."
    echo "   Install ns-3 + ndnSIM per README.md to enable."
fi

exit $PYTHON_EXIT
