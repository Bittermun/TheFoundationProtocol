# Project Coding Standards

## Testing
- Write tests before code (TDD)
- For bugs: write a failing test first, then fix (Prove-It pattern)
- Test hierarchy: unit > integration > e2e (use the lowest level that captures the behavior)
- Run `pytest` after every change
- All new features require @pytest.mark.concurrency tests if they touch shared state
- Chaos tests required for persistence/recovery paths (kill process mid-write, restart, verify integrity)

## Code Quality
- Review across five axes: correctness, readability, architecture, security, performance
- Every PR must pass: lint (ruff), type check (mypy), tests, build
- No secrets in code or version control (scan with bandit + semgrep before merge)
- Security checklist mandatory for all persistence, identity, and consensus code paths

## Implementation
- Build in small, verifiable increments (one backlog item per release: v3.2.1, v3.2.2, etc.)
- Each increment: implement → test → verify → commit → document
- Never mix formatting changes with behavior changes
- Feature flags required for all production behaviors (dev defaults stay unchanged)

## Boundaries
- Always: Run tests before commits, validate user input, check rowcount after INSERT OR IGNORE
- Ask first: Database schema changes, new dependencies, breaking API changes
- Never: Commit secrets, remove failing tests, skip verification, hardcode paths/backends outside config

## Documentation
- Every change updates: Integration Guide, Security Model & Checklist, Deploy Guide
- Add "3-device minimum for HABP consensus" warning to all relevant docs and error messages
- New Production Checklist + Troubleshooting Guide required for v3.2+
- Docs are non-optional: no merge without updated documentation

## Release Criteria (Definition of Done)
- Passes all 570+ tests including concurrency suite
- Security scan clean (bandit, semgrep, safety)
- Chaos tests pass (restart, crash recovery, identity loss simulation)
- Updated docs with explicit warnings
- Release scorecard updated showing which backlog items are complete
