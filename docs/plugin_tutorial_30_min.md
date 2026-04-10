# Build a TFP Plugin in 30 Minutes

## Goal

Ship one working plugin quickly so contributors can copy the pattern.

## 30-minute flow

1. Clone and install:
   - `cd /home/runner/work/Scholo/Scholo/tfp-foundation-protocol`
   - `pip install -r requirements.txt`
2. Start demo node:
   - `cd /home/runner/work/Scholo/Scholo`
   - `docker compose up --build`
3. Use `WebBridge` as protocol adapter from:
   - `/home/runner/work/Scholo/Scholo/tfp_plugin_sdk/adapters/web_bridge.py`
4. Register a content handler (audio/image/text).
5. Test with `tfp://` URLs and verify interception stats.
6. Publish sample plugin docs + screenshots in PR.

## Required outputs for tutorial video

- 1 plugin repo folder
- 1 runnable command
- 1 `tfp://` URL demo
- 1 short README with install + usage
