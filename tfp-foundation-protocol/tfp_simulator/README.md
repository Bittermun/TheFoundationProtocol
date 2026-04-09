# TFP v2.2 Simulation — Build & Run Guide (Ubuntu 22.04)

## Quick Start (Python only — no ns-3 required)

```bash
cd tfp-foundation-protocol
pip install -r requirements.txt
python tfp_simulator/attack_inject.py --seed 42 --requests 500
```

## Full ns-3 + Mini-NDN Setup (Ubuntu 22.04)

### 1. Install prerequisites
```bash
sudo apt-get update && sudo apt-get install -y \
    build-essential cmake python3-dev python3-pip \
    git libboost-all-dev libssl-dev libsqlite3-dev pkg-config
```

### 2. Install ns-3
```bash
git clone https://gitlab.com/nsnam/ns-3-dev.git ~/ns-3-dev
cd ~/ns-3-dev && git checkout ns-3.42
./ns3 configure --enable-examples --enable-tests && ./ns3 build
```

### 3. Install ndnSIM
```bash
mkdir -p ~/ns-3-dev/contrib
git clone https://github.com/named-data-ndnSIM/ndnSIM.git ~/ns-3-dev/contrib/ndnSIM
cd ~/ns-3-dev && ./ns3 configure --with-python --enable-examples && ./ns3 build
```

### 4. Run simulation
```bash
bash tfp_simulator/run_sim.sh
```

## Expected Output

```
[SCENARIO] Shard Poisoning + Semantic Drift Attack
  Success rate : 95.2%  → PASS ≥92%

[SCENARIO] Sybil Farm + PUF Identity Spoof
  Sybil nodes blocked : 200/200 | Sybil minted : 0  → PASS

[SCENARIO] Popularity Persistence + Asymmetric Uplink Under Congestion
  Cache stability : 96.1%  → PASS ≥95%
```

## Attack Scenarios

| # | Attack | Key Metric | Pass Threshold |
|---|--------|------------|----------------|
| 1 | 20% shard poisoning + semantic drift | Legit reconstruction rate | ≥92% |
| 2 | 200 Sybil nodes with fake PUF entropy | Credit minting rate for Sybils | =0% |
| 3 | 30% drop rate + congestion | High-popularity cache stability | ≥95% |
