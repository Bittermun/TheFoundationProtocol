# Security Fixes Implementation Plan

## Critical Issues to Address

### 1. Replace `random` with `secrets` for Security Contexts
Files affected:
- `/workspace/tfp_core/compute/task_mesh.py` - line 15 (import)
- `/workspace/tfp_core/privacy/metadata_shield.py` - lines 108, 186
- `/workspace/tfp_core/security/mutualistic_defense.py` - line 291
- `/workspace/tfp_core/security/scanner.py` - line 340
- `/workspace/tfp_pilots/community_bootstrap.py` - lines 27, 36, 86

### 2. Add Input Validation for Subprocess Calls
Files affected:
- `/workspace/tfp_core/audit/validator.py` - Already has validation but can be improved

### 3. Fix SQLite Thread Safety
- `/workspace/tfp-foundation-protocol/tfp_demo/server.py` - Already uses WAL mode and threading.Lock

### 4. Improve Exception Handling
Files affected:
- `/workspace/tfp-foundation-protocol/tfp_demo/server.py` - Lines 809, 1008, 1071, 1450, 1459
- Already using specific exceptions in most cases

### 5. Add Rate Limiting Configuration
- Already implemented in server.py with _EARN_RATE_MAX, etc.

### 6. Fix Assertion Misuse
- `/workspace/tfp-foundation-protocol/tfp_client/lib/bridges/nostr_bridge.py` - Lines 116, 140, 145, 148

### 7. Complete TODO Items (Priority Security-Related)
- PUF enclave integration
- Broadcast detection
- Verification systems

## Implementation Strategy

1. Replace random with secrets in security-critical contexts
2. Add input sanitization for all external inputs
3. Enhance logging for security events
4. Fix assertion misuse in cryptographic code
5. Add request size limits
6. Document remaining architectural improvements needed
