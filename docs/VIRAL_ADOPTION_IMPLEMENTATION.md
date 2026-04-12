# Viral Growth & Adoption Implementation

This document turns the adoption roadmap into concrete repository assets.

## Delivered in this implementation

### Priority 1 — Deployable Demo

- `docker-compose.yml` at repo root for one-command demo startup
- `tfp-foundation-protocol/Dockerfile.demo`
- `tfp-foundation-protocol/tfp_demo/server.py` (FastAPI demo node)
- `tfp-foundation-protocol/demo/index.html` (public web demo UI)
- `tfp-foundation-protocol/tfp_cli/main.py` (`tfp` CLI)

### Priority 3d — Browser Extension Fast-Track

- `tfp_plugin_sdk/docs/browser_extension_starter/manifest.json`
- `tfp_plugin_sdk/docs/browser_extension_starter/background.js`
- `tfp_plugin_sdk/docs/browser_extension_starter/README.md`

### Priority 4 — Developer Virality Starter Assets

- `docs/plugin_tutorial_30_min.md`
- `docs/hackathon_kit.md`
- `docs/awesome_tfp_seed.md`

### Priority 3 integrations + Priority 5 partnerships + Priority 6 narrative

- `docs/integrations_playbook.md`
- `docs/partnerships_outreach_pack.md`
- `docs/narrative_positioning_pack.md`

## Run locally

```bash
cd TheFoundationProtocol
docker compose up --build
```

Then open:

- Web demo: `http://localhost:8000/`
- API docs: `http://localhost:8000/docs`

CLI usage:

```bash
cd tfp-foundation-protocol
pip install -e .
tfp earn --task-id demo-task-1
tfp publish --title "Hello" --text "From CLI" --tags demo,cli
tfp search
```
