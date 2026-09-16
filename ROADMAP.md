# TFP Roadmap

Current planning entry point: [Foundation execution megaplan](docs/FOUNDATION_MEGAPLAN.md), with its [implementation board](docs/planning/execution-board.json). It preserves the wider compute/lexicon/video/federation mission and ties progress to evidence. The dated milestone estimates below are historical planning context, not current commitments or completed capabilities.

## v3.2 (Planned)

| Milestone | Target | Deliverable | Good First Issue |
|-----------|--------|-------------|------------------|
| **v3.2.0-alpha** | 4 weeks | Pooled compute tasks execute (matrix multiply, hash preimage, content verify) | Add `--version` flag to CLI |
| **v3.2.0-beta** | 6 weeks | Offline audio player MVP (audio player, offline sync, playlist curation) | Improve service worker cache strategy |
| **v3.2.0** | 8 weeks | Media archive support (large file optimization, RaptorQ tuning for video) | Test large file (100MB+) upload/download |
| **v3.2.1** | 10 weeks | Integration hardening (IPFS bridge stability, Nostr relay fallback) | Add retry logic to Nostr bridge |

Detailed tracking: [GitHub Milestones](https://github.com/Bittermun/TheFoundationProtocol/milestones)
