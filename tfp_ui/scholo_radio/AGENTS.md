# Scholo Radio UI Rules (`tfp_ui/scholo_radio/`)

When modifying `tfp_ui/scholo_radio/` (`index.html`, `server.py`, `open_audio_catalog.json`):

1. **Design Tokens & Typography**:
   - Preserve the glassmorphic dark audio player variables in `index.html` (`--bg-gradient`, `--glass-bg`, `--glass-border`, `--text-primary: #f5f3fa`, `--text-secondary: #a9a4b8`, `--primary: #8257ff`, `--accent: #ff4081`, `--success: #00e676`, `--warning: #ffb300`) and `Outfit` / `Inter` typography.
2. **Protocol Bridge Boundary**:
   - Keep UI mockup/catalog state in `tfp_ui/` cleanly separated from core protocol cryptography and transport modules in `tfp-foundation-protocol/`.
