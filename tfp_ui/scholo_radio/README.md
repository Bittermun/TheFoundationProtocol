# Scholo Radio (MVP Scaffold)

This folder scaffolds Priority 2 (first killer app): decentralized audio streaming over TFP.

## MVP flow

1. User taps **Listen**
2. App requests tagged audio via TFP hash
3. Playback starts from cache/mesh/broadcast
4. User taps **Earn** while charging to receive credits
5. User taps **Share** to publish local audio clips

## Current scaffold assets

- `/home/runner/work/Scholo/Scholo/tfp_ui/scholo_radio/open_audio_catalog.json`
- Protocol bridge already exists in:
  - `/home/runner/work/Scholo/Scholo/tfp_ui/core_bridge/protocol_adapter.py`

## Build target

- Flutter Android APK
- Offline-first playback
- Curated open-license audio catalog
