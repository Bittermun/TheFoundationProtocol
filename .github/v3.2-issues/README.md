# v3.2 Issue Tracker

Technical issues for The Foundation Protocol v3.2 development.

## Roadmap Overview

| Phase | Issue | Goal | Complexity | Priority |
|-------|-------|------|------------|----------|
| **v3.2.0-alpha** | #01 | Distributed matrix multiply (pooled compute) | High | P0 |
| **v3.2.0-beta** | #02 | NGO radio app MVP (offline audio) | Medium | P1 |
| **v3.2.0** | #03 | Large file & media archives (100MB-10GB) | High | P1 |
| **v3.2.1** | #04 | Nostr bridge stability (retry/fallback) | Medium | P2 |

## Quick Links

- [01-distributed-matrix-multiply.md](01-distributed-matrix-multiply.md) — Core pooled compute functionality
- [02-ngo-radio-app-mvp.md](02-ngo-radio-app-mvp.md) — Audio distribution for NGOs
- [03-large-file-media-archives.md](03-large-file-media-archives.md) — Movies, music, datasets
- [04-nostr-retry-fallback.md](04-nostr-retry-fallback.md) — Relay resilience

## How to Use These Issues

1. Copy issue content to GitHub Issues
2. Label appropriately: `v3.2`, `help wanted`, complexity (`easy`, `medium`, `hard`)
3. Link sub-issues as separate tickets for parallel work
4. Update this tracker as issues are claimed/completed

## Dependency Graph

```
#01 (Matrix Multiply)
  ├─ #02 (Radio App) — uses task distribution patterns
  └─ #04 (Nostr Retry) — needs reliable gossip for coordination

#03 (Large Files)
  └─ #01 — may use distributed computation for encoding
```

## Good First Entry Points

New contributors should start with:
1. Sub-issues in #01 (matrix splitting, shard tracker)
2. Sub-issues in #02 (MIME types, basic audio player)
3. Sub-issues in #04 (exponential backoff, health checker)

Avoid starting with #03 (large files) — requires deep protocol knowledge.

---

*Last updated: 2026-04-13*
