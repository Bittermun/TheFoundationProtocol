# Integrations Playbook

## 1) IPFS Gateway Bridge

### Scope
- CID ↔ TFP hash mapping
- Import IPFS content into TFP publish path
- Pin TFP content into IPFS gateway

### MVP milestones
1. Resolve CID and fetch bytes
2. Publish bytes through `/api/publish`
3. Store mapping table (`cid`, `root_hash`)
4. Add one-click import command in CLI

## 2) Nostr Integration

### Scope
- Post TFP hashes as Nostr events
- Discover content by relays + tags

### MVP milestones
1. Event format for `root_hash`, tags, title
2. Relay publish command
3. Relay read command + fetch via TFP

## 3) Wikipedia / Kiwix plugin

### Scope
- Seed `.zim` index metadata as TFP tags
- Enable local lookup and retrieval

### MVP milestones
1. Parse ZIM metadata
2. Publish chunked payload manifests
3. Add `education` and `health` discovery tags
