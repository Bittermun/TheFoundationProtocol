# TFP Open Source Readiness Plan

> **Version:** 1.0 (April 2026)
> **Scope:** Production-grade open source release
> **Timeline:** 4-phase rollout over 6-8 weeks

---

## Executive Summary

This plan defines the complete path from current state (v3.1, functional but with rough edges) to production-grade open source project with:
- **Zero critical security issues**
- **Complete documentation** (developer, operator, contributor)
- **Robust CI/CD** (fails safely, reports clearly)
- **Clear governance** (BDFL + community RFC)
- **Easy onboarding** (5-min contribution setup)

---

## Phase 1: Security Hardening (Week 1-2)

### 1.1 Critical Fixes (Completed ✓)

| Issue | Location | Fix Applied | Verification |
|-------|----------|-------------|--------------|
| Supply gossip manipulation | `server.py:1856-1870` | MAX_SUPPLY check + plausible value validation | `test_supply_gossip_validation.py` |
| EarnLog exception masking | `server.py:625-640` | Narrowed to `sqlite3.IntegrityError` | `test_earnlog_exceptions.py` |
| Duplicate timestamp check | `nostr_subscriber.py:217-226` | Removed, rely on server `_check_replay_window` | `test_nostr_timestamp_handling.py` |
| Configurable gossip buffer | `server.py:903` | `TFP_SUPPLY_GOSSIP_BUFFER` env var | Integration test |

### 1.2 Remaining Security Tasks

| Task | Priority | Complexity | Cascading Changes |
|------|----------|------------|-------------------|
| **Add gossip reputation system** | P1 | High | `server.py`, `config_validation.py`, new `reputation.py` |
| **Implement supply gossip anomaly detection** | P1 | Medium | `server.py:1856+` - flag sudden jumps > 1000 credits |
| **Add HABP rebuild fallback schema** | P2 | Medium | `server.py:845-852` - versioned spec parsing |
| **Document FK constraint test behavior** | P2 | Low | `server.py:598-623` + `docs/TESTING.md` |
| **PostgreSQL store refactoring** | P3 | High | All `*Store` classes - replace SQLite-specific SQL |

### 1.3 Security Standards

```yaml
Standards:
  - OWASP_ASVS_L1: true  # Application Security Verification Standard
  - SLSA_L1: true         # Supply chain integrity

Required_Gates:
  - bandit: zero medium/high severity
  - safety: zero known CVEs in dependencies
  - semgrep: zero ERROR severity rules triggered
  - secret_scan: zero matches (gitleaks/trufflehog)
```

---

## Phase 2: Documentation Completeness (Week 2-3)

### 2.1 Missing Critical Documentation

| Document | Status | Owner | Reviewer |
|----------|--------|-------|----------|
| `docs/OPERATOR_RUNBOOK.md` | ❌ Missing | TBD | Core maintainer |
| `docs/API_CHANGELOG.md` | ❌ Missing | TBD | API reviewer |
| `docs/TROUBLESHOOTING.md` | ❌ Missing | TBD | Support team |
| `docs/ARCHITECTURE_DECISION_RECORDS.md` | ❌ Missing | TBD | Architect |
| `docs/MIGRATION_GUIDE_v3.0_to_v3.1.md` | ❌ Missing | TBD | Release manager |

### 2.2 Documentation Standards

```yaml
Every_Public_Module_Must_Have:
  - Module-level docstring: purpose, example usage
  - All public functions: args, returns, raises
  - Type hints: all public signatures
  - Example: at least one doctest or code block

Every_Document_Must_Have:
  - Frontmatter: version, last_updated, status
  - Table of contents (if > 2 screens)
  - Cross-references: absolute paths to related docs
  - "Edit this page" link to GitHub
```

### 2.3 README Badge Accuracy Chain

```
README.md badge (749 tests)
    ↓ must match
pytest --collect-only count
    ↓ validated by
.github/workflows/ci.yml "Docs freshness" step
    ↓ failure blocks
merge to main
```

**Cascading fix:** If test count changes, update:
1. `README.md` badge
2. `tfp-foundation-protocol/docs/v3.0-integration-guide.md` Section 16
3. `CONTRIBUTING.md` quick start command

---

## Phase 3: CI/CD Robustness (Week 3-4)

### 3.1 Current CI Issues & Fixes

| Workflow | Issue | Fix | Priority |
|----------|-------|-----|----------|
| `ci.yml` | Tests pass but coverage not enforced | Add `pytest --cov=80` gate | P1 |
| `ci.yml` | Docs freshness step is fragile (grep) | Use `pytest --collect-only --json` | P2 |
| `security.yml` | Safety scan `|| true` masks failures | Remove `|| true`, fail on CVE | P1 |
| `security.yml` | Concurrency tests don't run on PRs | Add `pull_request` trigger | P2 |
| `scorecard.yml` | Python scorecard skipped silently | Fix import or remove | P2 |
| `license-check.yml` | Non-blocking - why? | Either enforce or remove | P2 |

### 3.2 Required New Workflows

```yaml
# .github/workflows/pr_validation.yml
name: PR Validation
on:
  pull_request:
    branches: [main]
jobs:
  full_matrix:
    # Test all supported Python versions + OS matrix
    matrix:
      python: ["3.11", "3.12", "3.13"]
      os: [ubuntu-latest, macos-latest, windows-latest]
      db: [":memory:", "postgresql"]  # When PG support ready
```

```yaml
# .github/workflows/nightly_stress.yml
name: Nightly Stress Tests
on:
  schedule:
    - cron: "0 2 * * *"  # 2 AM UTC
jobs:
  stress:
    # 10-node testbed, 1000 concurrent devices, 1 hour runtime
    - Run docker-compose.testbed.yml
    - Execute chaos scenarios (crash, latency, malicious)
    - Verify supply cap never exceeded
```

### 3.3 Release Automation Chain

```
Tag pushed (v3.1.0)
    ↓ triggers
.github/workflows/release.yml
    ↓ steps:
    1. Run full test matrix
    2. Build wheel + sdist
    3. Generate SBOM (cyclonedx)
    4. Sign artifacts (sigstore/cosign)
    5. Create GitHub release with notes
    6. Push to PyPI (trusted publishing)
    7. Update Docker Hub image
    8. Notify security.txt subscribers
```

---

## Phase 4: Community Readiness (Week 4-6)

### 4.1 Issue Templates (Complete ✓)

| Template | Status | Location |
|----------|--------|----------|
| Bug report | ✅ | `.github/ISSUE_TEMPLATE/bug_report.yml` |
| Feature request | ✅ | `.github/ISSUE_TEMPLATE/feature_request.yml` |
| Security vulnerability | ✅ | Security tab config |
| Good first issue | ✅ | Label + template |

### 4.2 Contribution Experience

```yaml
5_Minute_Contribution_Test:
  1. Fork repo: < 1 min
  2. Clone + install: < 2 min
  3. Run tests: < 1 min
  4. Make change + test: < 1 min
  5. Push + open PR: < 1 min

Current_Gaps:
  - Windows dev experience: untested
  - Dev container: not provided
  - Pre-commit hooks: not enforced locally
```

### 4.3 Governance Clarity

```yaml
BDFL_Model:
  - Current_BDFL: Bittermun
  - Succession_Plan: Documented in GOVERNANCE_MANIFEST.json
  - RFC_Process: GitHub Discussions with template
  - Decision_Log: ADR directory (missing - Phase 2)

Community_Roles:
  - Maintainer: Merge rights, release cuts
  - Committer: Direct push to non-main branches
  - Contributor: PRs from forks
  - Triager: Issue/PR labeling and routing
```

---

## Phase 5: Integration Hardening (Week 5-6)

### 5.1 External Dependency Chains

| Integration | Current State | Target State | Risk |
|-------------|---------------|--------------|------|
| **Nostr relays** | Single relay, no fallback | Multi-relay with health checks | High - gossip critical |
| **IPFS** | CID mapping exists, pinning weak | Full DHT integration | Medium |
| **PostgreSQL** | Connection layer ready | Full store support | Medium - migration path needed |
| **Redis** | Rate limiting adapter | Session cache, pub/sub | Low |
| **Prometheus** | 12 counters | Full node exporter | Low |

### 5.2 Cascading Fix: Nostr Multi-Relay

```
Add NostrConnectionManager (new file)
    ↓ requires
Update NostrBridge to use manager
    ↓ requires
Add relay health metrics
    ↓ requires
Update server.py config parsing (NOSTR_RELAYS comma-separated)
    ↓ requires
Update docker-compose.testbed.yml (3 relay services)
    ↓ requires
Add chaos tests for relay failures
    ↓ requires
Update docs/NOSTR_INTEGRATION.md
```

**Timeline:** 1 week (see `.github/v3.2-issues/04-nostr-retry-fallback.md`)

### 5.3 PostgreSQL Store Migration

```
Audit all SQLite-specific SQL:
  - sqlite_master queries (EarnLog._init_schema)
  - PRAGMA statements
  - INSERT OR REPLACE (SQLite-specific)
  - rowid usage

Migration path:
  1. Abstract Store base class with dialect detection
  2. Implement PostgreSQL dialect adapter
  3. Add integration tests against real PostgreSQL
  4. Document migration from SQLite
  5. Add CI job testing PostgreSQL backend
```

---

## Phase 6: Pre-Launch Validation (Week 6-8)

### 6.1 Launch Readiness Checklist

```yaml
Week_6:
  - [ ] All Phase 1-2 tasks complete
  - [ ] CI green for 7 consecutive days
  - [ ] Security audit by external reviewer (if budget)
  - [ ] Performance benchmark: 1000 devices, 1000 tasks, < 5 min

Week_7:
  - [ ] Documentation complete (all Phase 2 gaps)
  - [ ] All integration tests pass (PostgreSQL, Redis, IPFS)
  - [ ] Release candidate tagged (v3.1.0-rc1)
  - [ ] Community announcement drafted

Week_8:
  - [ ] Final release tag (v3.1.0)
  - [ ] PyPI published
  - [ ] Docker images published
  - [ ] Hacker News / Reddit announcement
  - [ ] Email security.txt subscribers
```

### 6.2 Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Supply gossip exploited in wild | Medium | Critical | Monitor for large jumps, add alerts |
| PostgreSQL migration breaks SQLite | Medium | High | Maintain SQLite as default, PG opt-in |
| Test flakiness in CI | Medium | Medium | Retry logic, better isolation |
| Contributor confusion (BDFL) | Low | Medium | Clear governance docs, responsive maintainer |
| Dependency CVE post-launch | Medium | Medium | Automated Dependabot, rapid patch process |

### 6.3 Success Metrics

```yaml
30_Days_Post_Launch:
  - GitHub_stars: > 100
  - Active_contributors: > 3 (non-BDFL)
  - Open_issues: < 20 (excluding feature requests)
  - Average_issue_response_time: < 48 hours
  - Security_disclosures: 0 critical, < 3 total
  - CI_failure_rate: < 5%
  - PyPI_downloads: > 100
```

---

## Appendix A: File-Level Change Tracking

### High-Churn Files (Monitor Carefully)

| File | Change Frequency | Last Modified | Notes |
|------|------------------|---------------|-------|
| `tfp_demo/server.py` | Very High | Today | Core logic, frequent security fixes |
| `tfp_client/lib/bridges/nostr_bridge.py` | High | Recent | Nostr integration evolving |
| `tfp_client/lib/credit/ledger.py` | Medium | Recent | Supply cap critical path |
| `.github/workflows/*.yml` | Medium | Recent | CI hardening ongoing |

### Standards Compliance by File

```yaml
Python_Source:
  SPDX_License: Required on all files
  Type_Hints: Required on public functions
  Docstrings: Required on public classes/functions
  Bandit_Clean: Required (no medium/high)

Documentation:
  Markdown: All docs
  TOCs: Required if > 2 screens
  Cross_Refs: Absolute paths preferred
  Last_Updated: Date stamp
```

---

## Appendix B: Integration Dependency Graph

```
NostrBridge
    ├── NostrConnectionManager (NEW - Phase 5)
    │       └── relay health, retry logic
    ├── NostrSubscriber
    │       └── event delivery
    └── _on_nostr_event (server.py)
            ├── _handle_supply_gossip_event
            ├── _handle_hlt_gossip_event
            └── _handle_search_index_event

TaskStore
    ├── SQLite (current)
    └── PostgreSQL (Phase 5 - future)
        └── requires Store dialect abstraction

CreditLedger
    └── TaskStore.get_total_minted()
        └── depends on Nostr gossip in multi-node
            └── reliability depends on NostrBridge health
```

---

## Appendix C: Tooling & Environment Matrix

| Tool | Version | Purpose | CI Gate |
|------|---------|---------|---------|
| Python | 3.11, 3.12, 3.13 | Runtime | Matrix test |
| pytest | 7.x+ | Testing | Required |
| ruff | 0.1.x+ | Lint/format | Blocking |
| mypy | 1.x+ | Type check | Warning (not blocking) |
| bandit | 1.7.x+ | Security scan | Blocking |
| safety | 2.x+ | CVE check | Blocking |
| semgrep | 1.x+ | Static analysis | Blocking |
| pre-commit | 3.x+ | Local quality | Optional |

---

**End of Plan**

*Last updated: April 15, 2026*
*Next review: Upon Phase 1 completion*
