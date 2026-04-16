# Deploy the TFP Demo Node

## Local (recommended first)

```bash
cd TheFoundationProtocol
docker compose up --build
```

The node starts on port 8000. Open:
- `http://localhost:8000` — PWA (installable on Android / iOS)
- `http://localhost:8000/admin` — live admin dashboard (tasks + device leaderboard)
- `http://localhost:8000/metrics` — Prometheus metrics
- `http://localhost:8000/health` — health check

---

## Quick start without Docker

```bash
cd tfp-foundation-protocol
pip install -r requirements.txt
uvicorn tfp_demo.server:app --reload
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TFP_MODE` | `demo` | Runtime mode. Use `production` for fail-closed startup validation and hardened defaults. |
| `TFP_DB_PATH` | `pib.db` | SQLite database path. Use `:memory:` for ephemeral (tests). |
| `NOSTR_RELAY` | _(empty)_ | WebSocket URL of a Nostr relay to publish/subscribe content announcements. `NOSTR_RELAY_URL` is also accepted (used by the Fly.io configs). |
| `TFP_PEER_SECRET` | _(empty in demo)_ | Required in production. Shared secret for `/api/peer` and `/admin` via `X-TFP-Peer-Secret`. |
| `TFP_ADMIN_DEVICE_IDS` | _(empty in demo)_ | Required in production. Comma-separated device allowlist for `/api/admin/rag/reindex`. |
| `TFP_NOSTR_PUBLISH_ENABLED` | `1` in demo, `0` in production | Enables outbound Nostr gossip publishing. |
| `TFP_NOSTR_TRUSTED_PUBKEYS` | _(empty)_ | In production, empty means deny inbound Nostr gossip by default. |
| `TFP_CORS_ORIGINS` | _(empty — allows all)_ | Comma-separated allowed CORS origins (e.g. `https://app.example.com`). When unset, all origins are allowed with credentials disabled. Set explicitly in production. |
| `TFP_EARN_RATE_MAX` | `10` | Max earn calls per device per window. |
| `TFP_EARN_RATE_WINDOW` | `60` | Sliding window length in seconds for rate limiting. |
| `TFP_REDIS_URL` | _(empty)_ | Redis connection URL (e.g. `redis://localhost:6379`). When set, rate limiters use distributed Redis sliding-window counters shared across workers. |
| `TFP_DATABASE_URL` | _(empty — uses SQLite)_ | Database connection URL. **⚠️ Partial PostgreSQL support** — connection layer works, but store classes use SQLite-specific SQL. Use SQLite for production. Full PostgreSQL support requires store refactoring. |

---

## Connecting to Nostr

TFP uses Nostr as a **peer-discovery transport** — nodes publish content-hash announcements as NIP-01 events so other TFP nodes (and Nostr clients) can discover available content without a central registry.

### Step 1 — Pick a public relay

Good free relays to start with:
- `wss://relay.damus.io`
- `wss://nos.lol`
- `wss://relay.nostr.band`

For production, run your own relay with [nostr-rs-relay](https://github.com/scsibug/nostr-rs-relay) or [strfry](https://github.com/hoytech/strfry).

### Step 2 — Start a Nostr-connected node

```bash
NOSTR_RELAY=wss://relay.damus.io \
TFP_DB_PATH=./data/pib.db \
uvicorn tfp_demo.server:app --host 0.0.0.0 --port 8000
```

Or with Docker:
```bash
NOSTR_RELAY=wss://relay.damus.io docker compose up --build
```

### Step 3 — Publish content and watch it propagate

```bash
# Generate a fresh 32-byte PUF entropy value (do this once per device)
PUF_HEX=$(python3 -c "import os; print(os.urandom(32).hex())")

# Enroll a device
curl -s -X POST http://localhost:8000/api/enroll \
  -H "Content-Type: application/json" \
  -d "{\"device_id\": \"my-node-1\", \"puf_entropy_hex\": \"${PUF_HEX}\"}"

# Publish a content item (the node broadcasts a NIP-01 event to the relay)
curl -s -X POST http://localhost:8000/api/publish \
  -H "Content-Type: application/json" \
  -H "X-Device-Sig: $(python3 -c "import hmac,hashlib,os; puf=bytes.fromhex('${PUF_HEX}'); print(hmac.new(puf, b'my-node-1:Hello World', hashlib.sha256).hexdigest())")" \
  -d '{"device_id": "my-node-1", "title": "Hello World", "text": "This is a test"}'
```

Check Nostr event history:
```bash
curl -s http://localhost:8000/api/status | python3 -m json.tool
```

### Step 4 — Announce your node on Nostr

Post a note on Nostr with your relay + endpoint so others can connect:

```json
{
  "kind": 1,
  "content": "Running a TFP v3.1 node. Content available via TFP protocol. Relay: wss://your-relay.example.com. Node: https://your-node.example.com",
  "tags": [["t", "tfp"], ["t", "scholo"], ["t", "decentralized"]]
}
```

You can post this with any Nostr client (Damus, Amethyst, Snort) or via the CLI:

```bash
# Using nak (Nostr army knife): https://github.com/fiatjaf/nak
nak event --content "Running TFP v3.1 node..." -t t=tfp -t t=scholo wss://relay.damus.io
```

---

## Bootstrap: Join the Compute Pool

```bash
# Install CLI (run from repo root)
pip install -e tfp-foundation-protocol/

# Start a server in one terminal
cd tfp-foundation-protocol
uvicorn tfp_demo.server:app --reload

# Join from another terminal — enroll, earn credits, spend on content
tfp --api http://localhost:8000 join
```

Shortcut to run a compute worker loop:
```bash
tfp --api http://localhost:8000 tasks
```

Check leaderboard:
```bash
tfp --api http://localhost:8000 leaderboard
```

---

## Cloud Deployment

> **Status:** Docker local is verified. Cloud platforms below need community testing. See issue #29 for deployment validation progress.

### Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Bittermun/TheFoundationProtocol)

**Manual setup if button doesn't work:**
1. Create new Web Service from this repo
2. Set environment vars:
   - `NOSTR_RELAY` → `wss://relay.damus.io` (or your relay)
   - `TFP_DB_PATH` → `/data/tfp.db` (use a persistent disk)
3. Build command: `pip install -r tfp-foundation-protocol/requirements.txt`
4. Start command: `cd tfp-foundation-protocol && uvicorn tfp_demo.server:app --host 0.0.0.0 --port 8000`

### Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/Bittermun/TheFoundationProtocol)

**Manual setup:**
1. New project → Deploy from GitHub repo
2. Set start command: `cd tfp-foundation-protocol && uvicorn tfp_demo.server:app --host 0.0.0.0 --port $PORT`
3. Add Redis service from Railway marketplace (optional, for distributed rate limiting)

### Fly.io

Two deployment options are available:

**Demo deployment (recommended for testing):**

```bash
# Use the root fly.toml configuration
fly launch --no-deploy --name tfp-demo --config fly.toml
fly volumes create tfp_data --size 1 --region iad
fly deploy --config fly.toml
```

**Production deployment:**

```bash
# Use the production configuration with security hardening
fly launch --no-deploy --name tfp-production --config fly.production.toml
fly volumes create tfp_data --size 1 --region iad
fly secrets set TFP_PEER_SECRET=<your-secret>
fly secrets set TFP_ADMIN_DEVICE_IDS=<device-id-1,device-id-2>
fly secrets set NOSTR_PRIVATE_KEY=<your-private-key>  # optional
fly deploy --config fly.production.toml
```

> **Status:** Verified. Uses multi-stage Python 3.12 Dockerfile, port 8000, persistent volume at `/data`, auto-stop disabled.

---

## Listing Your Node

Once running, list your node in these directories to bootstrap the network:

| Platform | How |
|----------|-----|
| **Nostr** | Post with tags `#tfp #scholo` on any relay |
| **GitHub Awesome list** | See `docs/awesome_tfp_seed.md` — submit a PR to add your deployment |
| **nostr.band** | Search `#tfp` — your relay posts appear automatically |
| **Reddit** | r/nostr, r/decentralization, r/selfhosted |
| **Hackernews** | Post project URL + demo video |
| **Discord/Telegram** | Nostr, IPFS, and decentralized-web communities |

---

## Monitoring

```bash
# Prometheus metrics
curl http://localhost:8000/metrics

# Health check (returns 200 when ready)
curl http://localhost:8000/health

# Admin dashboard (HTML)
open http://localhost:8000/admin
```

For production monitoring, point Prometheus at `/metrics` and use the provided Grafana dashboard template in `tfp-foundation-protocol/docker-compose.observability.yml`.

---

## Security Checklist Before Public Deployment

- [ ] Generate a fresh `puf_entropy_hex` with `python3 -c "import os; print(os.urandom(32).hex())"` — never reuse a value across deployments
- [ ] Set `TFP_DB_PATH` to a persistent volume (not `:memory:`)
- [ ] Set `TFP_MODE=production` to enable fail-closed startup validation
- [ ] Set `TFP_PEER_SECRET` to a strong random secret (required in production mode)
- [ ] Set `TFP_ADMIN_DEVICE_IDS` to the comma-separated list of authorised admin device IDs (required in production mode)
- [ ] Set `TFP_CORS_ORIGINS` to your application's origin(s) instead of the default wildcard
- [ ] Enable HTTPS (Nginx/Caddy reverse proxy or Cloudflare tunnel)
- [ ] Set `TFP_EARN_RATE_MAX` and `TFP_EARN_RATE_WINDOW` to appropriate limits
- [ ] Review `bandit.ini` and run `bandit -r tfp_core/ tfp_security/` on any custom code
- [ ] Read `tfp-foundation-protocol/docs/SECURITY.md` for the full threat model
