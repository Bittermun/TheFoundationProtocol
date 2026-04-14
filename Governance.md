# Governance Charter — The Foundation Protocol

> **Effective date**: April 2026 | **License**: Apache-2.0

## 1. Purpose

The Foundation Protocol (TFP) is an Apache-2.0 open-source project. This charter documents how
the project is governed, how decisions are made, and how community members can participate in
shaping its direction.

## 2. Stewardship Model

TFP operates under a **Benevolent Maintainer** model: a small group of active maintainers holds
merge rights and final decision authority, with broad community input for significant changes.

All governance activity happens in the open. Private communications are reserved only for
responsible security disclosures.

## 3. Decision Tiers

| Tier | Scope | Process | Timeline |
|------|-------|---------|----------|
| **T1 — Routine** | Bug fixes, docs, minor features | PR review + 1 maintainer approval | As fast as reviewed |
| **T2 — Significant** | New endpoints, protocol changes, deps | PR + RFC issue (label `rfc`) | 14-day comment window |
| **T3 — Major** | Breaking changes, governance amendments, license changes | RFC + 30-day comment + maintainer ratification | 30+ days |

## 4. Maintainer Path

1. Contribute 3+ merged PRs over 30+ days of active participation.
2. Be nominated by an existing maintainer or self-nominate via a GitHub issue.
3. Receive a LGTM from ≥ 2 current maintainers.

Maintainers are listed in `GOVERNANCE_MANIFEST.json`.

## 5. Founder Safeguards

The founding maintainer retains a veto on:
- Changes to the Apache-2.0 license
- Changes to this governance charter
- Security-critical architecture decisions

This veto lapses if the founding maintainer is inactive for > 12 months, at which point a
majority vote of active maintainers governs.

## 6. Amendment Rules

Changes to this document require:
- A T3 RFC open for 30 days
- No unresolved objections from maintainers
- A signed commit from the founding maintainer or a 2/3 majority of active maintainers

## 7. Code of Conduct Enforcement

Enforcement is handled as described in `CODE_OF_CONDUCT.md`. Reports go to
**governance@tfp-protocol.org**.

## 8. Security Disclosure

See `tfp-foundation-protocol/docs/SECURITY.md` for the responsible disclosure policy.

## 9. Fork Rights

The Apache-2.0 license guarantees perpetual fork rights. The project actively encourages
forks for regional deployments, protocol experiments, and derivative research. Attribution
to the original project is required per the license.

## 10. Contact

General governance questions: **governance@tfp-protocol.org**
Security disclosures: **security@tfp-protocol.org** (use PGP if possible — key in SECURITY.md)
