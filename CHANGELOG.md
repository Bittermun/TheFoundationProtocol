# Changelog

All notable changes to The Foundation Protocol (TFP) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Root-level test suite now included in CI
- Issue templates for bug reports, features, and good first issues
- Pull request template with comprehensive checklist
- Dependabot configuration for automated dependency updates
- Security.txt for vulnerability disclosure coordination

### Changed
- OpenSSF Scorecard now publishes results publicly

### Fixed
- Dependabot configuration now properly targets pip ecosystem

## [3.1.1] - 2026-04-13

### Added
- Production-ready core (25k+ LOC, 154 Python files)
- 749 passing tests with automated CI verification
- HABP consensus with cryptographic proof-of-work
- NDN + Nostr + IPFS integration for decentralized content
- Device authentication with HMAC-SHA-256 signing
- 21M credit supply cap with hard enforcement
- Prometheus metrics with 12+ counters
- Admin dashboard with live HTML interface
- CLI tools: `tfp join`, `tfp tasks`, `tfp leaderboard`
- PWA installable on Android/iOS
- Rate limiting on earn and result endpoints
- Security model with 8 verified properties
- OpenSSF Scorecard integration
- Security scanning with Bandit, Semgrep, Safety

### Security
- Verified properties: device auth, credit replay protection, supply cap enforcement
- Rate limiting on sensitive endpoints
- Input validation with Pydantic models
- Nostr event signature verification (BIP-340)

## [3.1.0] - 2026-03-XX

### Added
- Initial public codebase preparation
- Governance framework with BDFL model
- Apache-2.0 license
- Contributing guidelines

[Unreleased]: https://github.com/Bittermun/TheFoundationProtocol/compare/v3.1.1...HEAD
[3.1.1]: https://github.com/Bittermun/TheFoundationProtocol/releases/tag/v3.1.1
[3.1.0]: https://github.com/Bittermun/TheFoundationProtocol/releases/tag/v3.1.0
