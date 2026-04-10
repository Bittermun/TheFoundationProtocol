# Viral Growth & Adoption Implementation

This document turns the adoption roadmap into concrete repository assets.

## Delivered in this implementation

### Priority 1 — Deployable Demo

- `docker-compose.yml` at repo root for one-command demo startup
- `/home/runner/work/Scholo/Scholo/tfp-foundation-protocol/Dockerfile.demo`
- `/home/runner/work/Scholo/Scholo/tfp-foundation-protocol/tfp_demo/server.py` (FastAPI demo node)
- `/home/runner/work/Scholo/Scholo/tfp-foundation-protocol/demo/index.html` (public web demo UI)
- `/home/runner/work/Scholo/Scholo/tfp-foundation-protocol/tfp_cli/main.py` (`tfp` CLI)

### Priority 3d — Browser Extension Fast-Track

- `/home/runner/work/Scholo/Scholo/tfp_plugin_sdk/docs/browser_extension_starter/manifest.json`
- `/home/runner/work/Scholo/Scholo/tfp_plugin_sdk/docs/browser_extension_starter/background.js`
- `/home/runner/work/Scholo/Scholo/tfp_plugin_sdk/docs/browser_extension_starter/README.md`

### Priority 4 — Developer Virality Starter Assets

- `/home/runner/work/Scholo/Scholo/docs/plugin_tutorial_30_min.md`
- `/home/runner/work/Scholo/Scholo/docs/hackathon_kit.md`
- `/home/runner/work/Scholo/Scholo/docs/awesome_tfp_seed.md`

### Priority 3 integrations + Priority 5 partnerships + Priority 6 narrative

- `/home/runner/work/Scholo/Scholo/docs/integrations_playbook.md`
- `/home/runner/work/Scholo/Scholo/docs/partnerships_outreach_pack.md`
- `/home/runner/work/Scholo/Scholo/docs/narrative_positioning_pack.md`

## Run locally

```bash
cd /home/runner/work/Scholo/Scholo
docker compose up --build
```

Then open:

- Web demo: `http://localhost:8000/`
- API docs: `http://localhost:8000/docs`

CLI usage:

```bash
cd /home/runner/work/Scholo/Scholo/tfp-foundation-protocol
pip install -e .
tfp earn --task-id demo-task-1
tfp publish --title "Hello" --text "From CLI" --tags demo,cli
tfp search
```
