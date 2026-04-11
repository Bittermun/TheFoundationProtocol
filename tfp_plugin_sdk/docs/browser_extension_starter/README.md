# TFP Browser Extension Starter

This starter fast-tracks Priority 3d with a minimal MV3 extension that intercepts `tfp://` links and forwards them to a TFP demo node.

## Files

- `manifest.json` — extension manifest
- `background.js` — protocol handling and redirect logic

## Quick start

1. Update `TFP_NODE_BASE` in `background.js` to your deployed node.
2. Open Chrome: `chrome://extensions`
3. Enable **Developer mode**
4. Click **Load unpacked**
5. Select this folder
6. Open a page containing a `tfp://` link, e.g.:
   - `tfp://tag/demo/welcome`
   - `tfp://<root_hash>`

The extension redirects root-hash URLs to:

`<TFP_NODE_BASE>/api/get/<root_hash>?device_id=browser-extension`

Tag queries redirect to:

`<TFP_NODE_BASE>/api/content?tag=<tag>`
