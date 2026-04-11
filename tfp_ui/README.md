# TFP UI - Zero-Config First-Time User Interface

## 🎯 Design Philosophy
**Interface > Protocol.** For first-time/no-internet users, the UI *is* the product.
Technical complexity (hashes, credits, NDN, RaptorQ) is completely abstracted behind
human metaphors: "Listen", "Share", "Earn Thanks".

## 📱 Target Demographics
- **First-time smartphone users**: Radio-like simplicity, no prior digital literacy assumed
- **Low-literacy users**: Icon-first navigation, voice guidance, minimal text
- **Trust-deficient communities**: Transparent value prop, no hidden mechanics
- **Offline-first environments**: Works without internet, auto-discovers broadcast/mesh

## 🏗️ Architecture

```
tfp_ui/
├── screens/
│   ├── discover_screen.py      # 📡 Listen: Browse & play content
│   ├── share_screen.py         # 📤 Share: Record & publish
│   ├── earn_screen.py          # 🔄 Earn: Toggle charge-mode
│   └── onboarding_screen.py    # 30-sec voice guide
├── core_bridge/
│   └── protocol_adapter.py     # UI → TFP Core mapping layer
├── assets/
│   ├── icons/                  # Literacy-agnostic symbols
│   └── voice_guides/           # Local language audio prompts
├── config/
│   └── zero_config.yaml        # Auto-join, no login, no settings
└── test/
    └── ui_test_flow.py         # Tap → Protocol → UI validation
```

## 🔑 Hard Rules

1. **Zero Technical Jargon**
   - ❌ "Credits" → ✅ "Thanks"
   - ❌ "Hashes" → ✅ "Stories/Files"
   - ❌ "NDN Interest" → ✅ "Requesting from neighbors"
   - ❌ "RaptorQ Decode" → ✅ "Downloading pieces"

2. **No Authentication Barriers**
   - No logins, passwords, or key imports
   - Identity auto-generated via PUF/TEE on first launch
   - No "Connect Wallet" or seed phrases

3. **Offline-First**
   - All screens functional without network
   - Shows "Waiting for signal..." only after 5min absence
   - Cached content playable immediately

4. **Accessibility Defaults**
   - Large tap targets (min 48x48dp)
   - Voice-first navigation
   - RTL support, high-contrast modes
   - 50+ language packs included

5. **Credit Abstraction**
   - Never show numeric balances (prevents hoarding anxiety)
   - Show contribution metrics: "Stories shared", "Neighbors helped"
   - Decay/staking handled invisibly in background

## 🚀 Onboarding Flow (30 seconds)

1. **Launch** → Auto-detects ATSC/FM broadcast + local mesh
2. **Voice Greeting** (local language): "Welcome! This is your community radio."
3. **Three Buttons Appear**:
   - 📡 **Listen**: "Tap to hear stories from nearby"
   - 📤 **Share**: "Tap to record your voice or photo"
   - 🔄 **Earn**: "Tap while charging to help neighbors"
4. **First Interaction**: User taps "Listen" → Content plays in <3s
5. **Done**: No settings, no accounts, no configuration

## 🌍 Fallback Tiers

| Device Tier | Interface | Why |
|-------------|-----------|-----|
| Smartphone (Android 8+/iOS 14+) | Full Flutter app | Best UX, full protocol |
| Feature Phone (2G) | USSD + Voice IVR (`*123#`) | Works on $10 phones |
| SDR / IoT Box | Headless daemon + LED/status tones | Community routers, schools |
| Browser | Phase 3+ only | Assumes existing internet/literacy |

## 📊 Performance Targets

- **Install Size**: <200MB (all assets offline)
- **RAM Usage**: <50MB during operation
- **Cold Start**: <2s to first interactive screen
- **Content Playback**: <3s from tap to audio (with cache hits)
- **Battery Impact**: <5%/hour in "Earn" mode (idle compute)

## 🔌 Protocol Mapping

| UI Action | User Sees | Protocol Behind Scenes |
|-----------|-----------|------------------------|
| Tap "Listen" | Audio plays, "Downloaded from neighbors" | NDN Interest → RaptorQ decode → Chunk cache → Semantic reconstruct |
| Tap "Share" → Record | "Shared to 12 nearby devices. Earned 3 thanks." | Voice → Chunk ID + AI delta → RaptorQ encode → NDN Announce → Broadcast scheduler |
| Toggle "Earn" | "Helping while charging. 15 thanks earned today." | Device checks battery/temp → claims micro-task → HABP verify → Credit mint |
| Tap "Thanks" icon | "You have 42 thanks. Pin your favorite story?" | Local ledger → decay-adjusted balance → staking/pinning UI |

## 🛠️ Tech Stack Recommendations

### Primary: Flutter (Recommended)
- **Why**: Single codebase for Android/iOS, excellent offline support, strong i18n
- **Dependencies**: `flutter_localizations`, `audioplayers`, `image_picker`, `workmanager`
- **Build Size**: ~40MB base + 150MB assets (voice packs, icons)

### Alternative: React Native
- **Why**: Larger JS dev ecosystem, easier web fallback later
- **Dependencies**: `react-native-i18n`, `react-native-sound`, `react-native-image-picker`
- **Caveat**: Larger runtime overhead, trickier offline-first

### USSD Fallback: Python + GSM Modem
- **Why**: Works on any phone with cellular signal
- **Stack**: `python-gsmmodem`, Twilio API (optional), Asterisk IVR
- **Flow**: `*123#` → Menu tree → Voice prompts → Action execution

## 📝 Next Steps

1. **Implement Screen Stubs**: 4 core screens with mock data
2. **Build Protocol Adapter**: Map UI taps to TFP core calls
3. **Create Icon Set**: 20 universal symbols (literacy-agnostic)
4. **Record Voice Guides**: 50+ languages, 30-second onboarding
5. **Write Test Flow**: Validate tap → protocol → UI cycle
6. **Performance Profiling**: Ensure <50MB RAM, <200MB install

## ⚠️ Anti-Patterns to Avoid

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| URL bar / tabs | Overwhelms first-timers | Hide entirely; use icon grid |
| "Connect Wallet" | Kills trust, assumes crypto literacy | Auto-generate PUF identity |
| Numeric credit balances | Causes hoarding anxiety | Show "Thanks earned", not numbers |
| Settings-heavy setup | 80% abandon before first use | Zero-config; progressive disclosure |
| English-first UI | Excludes 70% of target demographic | Icon-first + 50+ language packs |

---

**Version**: v2.2 Scaffold
**Status**: Ready for implementation
**Total LOC Target**: <3,000 (UI layer only)
