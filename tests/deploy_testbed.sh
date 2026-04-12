#!/usr/bin/env bash
set -e

echo "Deploying 10-node operational testbed..."

# Generate the compose file if it doesn't exist
if [ ! -f "docker-compose.testbed.yml" ]; then
    python3 tests/generate_testbed.py
fi

# Cleanup old containers
docker-compose -f docker-compose.testbed.yml down --remove-orphans

# Build and start
docker-compose -f docker-compose.testbed.yml up -d --build

echo "Testbed deployed successfully."
echo "Nodes: http://localhost:8001 through http://localhost:8010"
echo "IPFS API: http://localhost:5001"
