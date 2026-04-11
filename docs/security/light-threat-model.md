# Light Threat Model - TFP v3.1

**Date**: April 2026
**Scope**: High-risk components before public Nostr launch.

## In-Scope Components

- HABP Consensus & Credit Minting
- Shard Verification
- PUF Key Derivation & Device Identity
- Distributed Rate Limiter
- Transport / Authentication Layer

## STRIDE Analysis

| Component | Spoofing | Tampering | Repudiation | Info Disclosure | DoS | Elevation of Privilege |
|-----------|----------|-----------|-------------|-----------------|-----|------------------------|
| **HABP Consensus** | Fake PUF identity | Vote manipulation | Unlogged votes | Vote pattern analysis | Consensus stall | Fake validator enrollment |
| **Credit Minting** | Fake task claims | Credit tampering | Missing audit trails | Balance exposure | Minting DoS | Admin credit grants |
| **PUF Keys** | PUF prediction | Key tampering | Missing usage logs | Key leakage | PUF DoS | Key escalation |
| **Rate Limiter** | Sybil via ID rotation | Token manipulation | Missing logs | Request patterns | Bypass floods | Admin bypass |
| **Nostr Bridge** | Signature forgery | Event tampering | Missing event audit | Metadata leakage | Relay flooding | Privilege escalation |

## Simple Data Flow

```
[Device] → (PUF Identity) → [HABP Validator] → (Signed Votes) → [Consensus]
                                                      ↓
[Client] → (Request) → [Rate Limiter] → [Transport] → [Compute Shard]
                                                      ↓
                                              [Credit Ledger] → [Minting]
                                                      ↓
                                              [Nostr Bridge] → [Relay Network]
```

## Trust Assumptions

- Redis runs on trusted internal network
- Devices have secure PUF hardware
- SQLite files only accessed by TFP process
- Nostr relays are honest-but-curious
- Python runtime is not compromised

## Out of Scope

- Physical device tampering
- OS-level compromise
- Network attacks below TLS
- Social engineering
- Supply chain compromises

## Top Risks & Mitigations

### 1. Credit Inflation Attack
**Risk**: Malicious actors mint credits beyond 21M cap
**Mitigation**: Hardcoded supply cap, HABP 3/5 consensus, Prometheus audits

### 2. Rate Limiter Bypass
**Risk**: Sybil attacks via client ID rotation
**Mitigation**: Atomic Lua scripts, IP-based fallback, behavioral anomaly detection

### 3. PUF Identity Spoofing
**Risk**: Fake device identities joining consensus
**Mitigation**: Hardware-bound PUF challenges, validator reputation tracking

### 4. Nostr Replay Attacks
**Risk**: Re-submission of valid events
**Mitigation**: Strict `created_at` ordering, event ID uniqueness tracking

### 5. SQLite Concurrency Issues
**Risk**: Data corruption under high load
**Mitigation**: WAL mode, connection pooling, timeout/retry logic

## Security Monitoring Requirements

- All credit minting events logged with full context
- Rate limit triggers tracked per client/IP
- Failed authentication attempts alerting
- Consensus vote anomalies detection
- Nostr event validation failures logged

## Incident Response Triggers

- Credit supply exceeds expected minting rate
- Rate limiter bypass patterns detected
- Multiple failed PUF challenges from same source
- Consensus stall exceeding threshold
- Nostr event flood from single relay
