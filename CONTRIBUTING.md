# Contributing to Scholo / TFP

Thank you for your interest in contributing to the TFP Foundation Protocol! This project exists to build a censorship-resistant, offline-first, globally-accessible knowledge commons. Every contribution — however small — helps that mission.

---

## Quick Start for Contributors

```bash
git clone https://github.com/Bittermun/TheFoundationProtocol.git
cd TheFoundationProtocol/tfp-foundation-protocol
pip install -r requirements.txt
TFP_DB_PATH=:memory: PYTHONPATH=. python -m pytest tests/ -q   # 749+ tests (protocol + root integration)
```

---

## Ways to Contribute

| Type | Where to Start |
|------|---------------|
| Bug reports | [Open an Issue](https://github.com/Bittermun/TheFoundationProtocol/issues) with reproduction steps |
| Feature requests | Open an Issue tagged `enhancement` |
| Code contributions | Fork → branch → PR (see below) |
| Documentation | Edit files in `docs/` or `tfp-foundation-protocol/docs/` |
| Definition of Done | Review [DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md) — every PR and release is measured against it |
| Translations | Voice guide scripts are in `tfp_ui/screens/screen_stubs.py` |
| Plugins | Follow the [Plugin Tutorial](docs/plugin_tutorial_30_min.md) |
| Hackathon projects | See [Hackathon Kit](docs/hackathon_kit.md) |

---

## Code Contribution Workflow

1. **Fork** the repo and create a feature branch: `git checkout -b feat/my-change`
2. **Write tests** — all new functionality needs a test in `tfp-foundation-protocol/tests/`
3. **Lint**: `ruff check .` from the repo root (must be clean)
4. **Test**: `cd tfp-foundation-protocol && TFP_DB_PATH=:memory: PYTHONPATH=. python -m pytest tests/ -q`
5. **Open a PR** against `main` with a clear description

### Code Style
- Python 3.11+ compatible
- `ruff check` and `ruff format` enforced by pre-commit hooks
- `bandit` for security scanning — `medium` severity and above must be addressed
- `mypy` for type checking — enforced by pre-commit hooks
- Type hints on all public functions
- Docstrings on all public classes and methods

### CI/CD Configuration
- The security workflow uses `safety check` for dependency vulnerability scanning
- For enhanced security reporting with `safety scan --full-report`, add a `SAFETY_API_KEY` secret to the repository
- Without the API key, the workflow falls back to basic `safety check` (non-blocking)
- All security jobs have a 10-minute timeout to prevent hung CI runs

---

## Contribution Areas (High Impact)

These are areas where contributions have the most leverage:

- **Nostr relay publishing** — extend `nostr_bridge.py` to support publishing to multiple relays simultaneously
- **Android/iOS PWA offline sync** — improve the service worker cache eviction strategy
- **Kiwix / ZIM integration** — seed offline Wikipedia content as TFP-addressable bundles
- **IPFS bridge** — CID ↔ TFP hash mapping (see `docs/integrations_playbook.md`)
- **Voice guide translations** — record or fund recordings for underserved languages
- **Performance** — the RaptorQ encoder throughput on low-power devices

---

## Security Issues

**Do not open public GitHub issues for security vulnerabilities.**

Email: `security@tfp-protocol.org`
Response time: 48 hours. See [SECURITY.md](tfp-foundation-protocol/docs/SECURITY.md) for the full disclosure policy.

---

## Governance

Decisions follow the BDFL model with community RFC input. Major changes go through an open RFC process in GitHub Discussions. See [GOVERNANCE_MANIFEST.json](GOVERNANCE_MANIFEST.json) for the full governance spec.

---

## License

By contributing you agree that your contribution is released under the [Apache-2.0 License](LICENSE).
