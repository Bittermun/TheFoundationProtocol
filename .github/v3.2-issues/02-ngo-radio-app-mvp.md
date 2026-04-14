# [v3.2.0-beta] NGO Radio App MVP — Offline-First Audio Distribution

## Goal
Build installable PWA that plays audio content (podcasts, educational material, music) distributed via TFP, with full offline capability for low-connectivity regions.

## Target Users
- NGOs distributing educational content in disconnected areas
- Community radio stations archiving broadcasts
- Emergency information dissemination (offline-first critical)

## Technical Scope

### Phase 1: Audio Content Type (Complexity: Low)
**Files:**
- `tfp_demo/server.py` — add `audio/*` MIME type support
- `tfp_client/lib/metadata/tag_index.py` — add `audio`, `podcast`, `music` tags

Add to `ContentType` enum:
```python
AUDIO_MPEG = "audio/mpeg"      # MP3
AUDIO_OGG = "audio/ogg"        # Ogg Vorbis
AUDIO_WAV = "audio/wav"        # WAV (uncompressed, archival)
```

### Phase 2: PWA Audio Player (Complexity: Medium)
**Files:**
- `tfp_ui/static/player.js` (new)
- `tfp_ui/templates/radio.html` (new)

Features:
- [ ] Playlist view (content tagged `audio` or `podcast`)
- [ ] Play/pause, seek, volume controls
- [ ] Download for offline (store in IndexedDB)
- [ ] Background audio (service worker keeps playing when app backgrounded)
- [ ] Playback resume on restart

UI mockup:
```
┌─────────────────────────────┐
│  🎧 TFP Radio               │
│                             │
│  [=========>        ] 3:24  │
│  Educational Podcast #12    │
│                             │
│  [⏸️]  [⏮️]  [⏭️]         │
│                             │
│  📥 Offline (12 episodes)   │
│  📡 Online (48 episodes)    │
└─────────────────────────────┘
```

### Phase 3: Offline Sync Strategy (Complexity: High)
**File:** `tfp_ui/static/sw-audio.js` — extend service worker

Implement:
```javascript
// Service Worker audio sync
const AUDIO_CACHE = 'tfp-audio-v1';

self.addEventListener('sync', event => {
  if (event.tag === 'sync-audio') {
    event.waitUntil(syncNewEpisodes());
  }
});

async function syncNewEpisodes() {
  // 1. Query /api/discovery?tag=podcast&since=last_sync
  // 2. Download new content hashes
  // 3. Fetch via /api/get/{hash} with ?stream=true
  // 4. Store in IndexedDB (audio chunks)
  // 5. Update playlist UI
}
```

Sync strategies:
- **WiFi only** — don't use expensive mobile data
- **Night sync** — download during off-peak hours
- **Priority queue** — user can star episodes for immediate download

### Phase 4: Playlist Curation (Complexity: Medium)
**Files:**
- Server: Add `playlist` concept to TagOverlayIndex
- UI: Drag-drop playlist builder

Allow users to:
- Create named playlists (`Emergency Info 2026`, `Farming Techniques`)
- Share playlists as Nostr events (kind 30024 — structured data)
- Subscribe to NGO-curated playlists

## Acceptance Criteria
- [ ] Can upload MP3 via `/api/publish` (multipart already works)
- [ ] Audio appears in discovery with `type=audio/mpeg`
- [ ] PWA player plays audio without leaving page
- [ ] Downloaded audio plays offline (airplane mode test)
- [ ] Background playback works on Android Chrome
- [ ] 10 audio files (100MB total) sync in < 5 min on WiFi
- [ ] Playlist can be shared and subscribed via Nostr

## API Additions
```
GET /api/content?type=audio/mpeg&tag=podcast
GET /api/playlist/{id}           # Get curated list
POST /api/playlist               # Create new playlist
```

## Database Schema
```sql
CREATE TABLE playlists (
    playlist_id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    curator_pubkey TEXT,  -- Nostr pubkey of creator
    created_at REAL,
    nostr_event_id TEXT   -- Reference to Nostr kind 30024
);

CREATE TABLE playlist_items (
    playlist_id TEXT,
    content_hash TEXT,
    position INTEGER,
    added_at REAL,
    PRIMARY KEY (playlist_id, content_hash)
);
```

## Good First Sub-Issues
1. **Add audio MIME types** — Simple enum addition, test file upload
2. **Basic HTML5 audio player** — Just `<audio controls>` with playlist
3. **IndexedDB storage wrapper** — Generic blob storage utility
4. **Service worker sync trigger** — Wire up `sync` event listener

## Estimated Effort
- Audio specialist contributor: 2 weeks
- Generalist with PWA experience: 3 weeks

## Priority
**P1** — Key differentiator for NGO adoption, not blocking core protocol

## Success Metrics
- Can play 1 hour audio without network
- Sync resumes correctly after connectivity loss
- Memory usage < 200MB for 50 cached episodes

---

## Open Questions

**Q: What audio formats to prioritize?**
A: MP3 for compatibility, Ogg for efficiency, WAV only for archival. Start with MP3.

**Q: How to handle large audio files (1 hour = 50MB)?**
A: Use existing streaming download with 64KB chunks. RaptorQ for resilience if needed.

**Q: Copyright considerations?**
A: TFP is content-agnostic. NGOs must license appropriately. Add `license` field to metadata (CC-BY, CC-0, proprietary).
