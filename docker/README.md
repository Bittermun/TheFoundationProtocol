# Multi-Node Docker Network Simulation Harness

This directory contains the autonomous multi-container simulation environment for **The Foundation Protocol (TFP v4.0)**.

## Architecture

```
                      172.28.0.0/16 [tfp-mesh-net]
+-----------------------------------------------------------------------+
|                                                                       |
|   +-----------------------+              +------------------------+   |
|   |      tfp-station      |              |       tfp-phone        |   |
|   |     (172.28.0.10)     |              |     (172.28.0.20)      |   |
|   |   - Transmitter       |   Fountain   |   - Receiver           |   |
|   |   - Visualizer Engine |  Droplets    |   - Gaussian Solver    |   |
|   |   - FastCDC Slicer    | -----------> |   - Media Player       |   |
|   |   - Port 8080 / 9999  |              |                        |   |
|   +-----------------------+              +------------------------+   |
|                                                      ^                |
|                                                      |                |
|                             Linux Traffic Control    |                |
|                             (tc netem 25% loss) -----+                |
+-----------------------------------------------------------------------+
```

## Quickstart

### 1. Launch Multi-Node Mesh
```bash
docker-compose -f docker/docker-compose.yml up --build -d
```

### 2. Verify Services Health
```bash
docker-compose -f docker/docker-compose.yml ps
curl -i http://localhost:8080/api/protocol-state
```

### 3. Inject Simulated Mobile / Acoustic Mesh Impairments
```bash
docker exec -it tfp-phone /bin/bash /app/docker/simulate_mesh_loss.sh eth0 30% 40ms 15ms
```

### 4. Transmit a Physical Media File
```bash
# Stream an emergency audio tune or custom file
curl -X POST http://localhost:8080/api/sample-short
curl -X POST http://localhost:8080/api/sample-audio
```

### 5. Inspect Reconstructed Media
```bash
curl -I http://localhost:8080/api/reconstructed-media
```
Or open `http://localhost:8080/visualizer.html` in your browser.
