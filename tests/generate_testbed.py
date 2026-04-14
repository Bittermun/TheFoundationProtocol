#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import os

TEMPLATE = """version: '3.8'

services:
  # IPFS (Kubo) for content pinning and retrieval
  tfp-ipfs:
    image: ipfs/kubo:latest
    container_name: tfp-ipfs
    ports:
      - "5001:5001"
      - "8080:8080"
    volumes:
      - ipfs_data:/data/ipfs
    networks:
      - tfp-network
    deploy:
      resources:
        limits:
          memory: 512M

  # Redis for distributed rate limiting
  redis:
    image: redis:7-alpine
    container_name: tfp-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    networks:
      - tfp-network
    deploy:
      resources:
        limits:
          memory: 128M

  # Nostr Relay for cross-node discovery
  tfp-relay:
    image: scsibug/nostr-rs-relay:latest
    container_name: tfp-relay
    ports:
      - "8008:8080"
    networks:
      - tfp-network
    deploy:
      resources:
        limits:
          memory: 128M

{nodes}

volumes:
  ipfs_data:
  redis_data:
{node_volumes}

networks:
  tfp-network:
    driver: bridge
"""

NODE_TEMPLATE = """  tfp-node-{i}:
    build:
      context: ./tfp-foundation-protocol
      dockerfile: Dockerfile.demo
    container_name: tfp-node-{i}
    ports:
      - "{port}:8000"
    restart: unless-stopped
    volumes:
      - tfp_data_{i}:/data
    environment:
      - TFP_DB_PATH=/data/pib.db
      - TFP_IPFS_API_URL=http://tfp-ipfs:5001
      - TFP_REDIS_URL=redis://tfp-redis:6379/0
      - NOSTR_RELAY_URL=ws://tfp-relay:8080
    deploy:
      resources:
        limits:
          cpus: '0.2'
          memory: 256M
    depends_on:
      - tfp-ipfs
      - redis
      - tfp-relay
    networks:
      - tfp-network
"""


def generate_compose(num_nodes=10):
    nodes_str = ""
    volumes_str = ""
    base_port = 8000

    for i in range(1, num_nodes + 1):
        port = base_port + i
        nodes_str += NODE_TEMPLATE.format(i=i, port=port)
        volumes_str += f"  tfp_data_{i}:\n"

    output = TEMPLATE.format(nodes=nodes_str, node_volumes=volumes_str)

    output_path = "docker-compose.testbed.yml"
    with open(output_path, "w") as f:
        f.write(output)
    print(f"Generated {output_path} successfully with {num_nodes} nodes.")


if __name__ == "__main__":
    generate_compose(10)
