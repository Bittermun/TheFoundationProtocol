# TFP Demo Guide - Complete Interactive Experience

This guide provides multiple ways to experience The Foundation Protocol (TFP) - from quick 30-second demos to advanced multi-node scenarios.

## 🚀 Quick Start Options

### Option 1: 30-Second Automated Demo (Recommended for First-Time Users)

**Perfect for:** Immediate hands-on experience without setup

```bash
cd TheFoundationProtocol
python demo_30sec.py
```

**What happens:**
- ✅ Starts a local TFP server automatically
- ✅ Enrolls a demo device with secure identity
- ✅ Publishes sample content to the network
- ✅ Demonstrates credit earning system
- ✅ Retrieves and displays the content
- ✅ Shows performance metrics (timing, throughput)

**Expected output:**
```
[23:31:57] ============================================================
[23:31:57] TFP 30-Second Demo
[23:31:57] ============================================================
[23:31:57] Starting TFP demo server...
[23:31:58] ✓ Server ready on http://localhost:8000
[23:31:58] Enrolling demo device...
[23:32:00] ✓ Device enrolled: demo-device-001
[23:32:00] Publishing sample content...
[23:32:02] ✓ Content published in 2059ms
[23:32:02]   Hash: edbc93e7ff9f110a...
[23:32:02] Earning demo credits...
[23:32:04] ✓ Credits earned: 10
[23:32:04] Retrieving content...
[23:32:06] ✓ Content retrieved in 2042ms
[23:32:06]   Title: Demo Content
[23:32:06]   Size: 51 chars
```

---

### Option 2: Interactive Web Demo (Best for Visual Experience)

**Perfect for:** Users who prefer a graphical interface

```bash
cd TheFoundationProtocol
docker compose up --build
```

Then open: `http://localhost:8000`

**Features:**
- 🎨 Modern web interface with responsive design
- 🔐 Device identity management with secure entropy generation
- 💰 Interactive credit earning system
- 📝 Content publishing with rich text support
- 🔍 Content search and retrieval by hash
- 📊 Real-time content listing
- 📱 PWA support (installable on mobile devices)

**Step-by-step walkthrough:**

1. **Device Identity** - The demo automatically creates a secure device identity using cryptographic entropy
2. **Earn Credits** - Click "Earn 10 credits" to participate in the compute pool
3. **Publish Content** - Create and publish content with custom title, text, and tags
4. **Retrieve Content** - Use the content hash to fetch published content
5. **Browse Content** - View all available content in the network

---

### Option 3: Command-Line Interface (Best for Developers)

**Perfect for:** Developers and power users who want full control

```bash
cd tfp-foundation-protocol
pip install -r requirements.txt
uvicorn tfp_demo.server:app --reload
```

Then in another terminal:

```bash
# Install CLI
pip install -e .

# Join the compute pool
tfp --api http://localhost:8000 join --device-id my-laptop

# List available tasks
tfp --api http://localhost:8000 tasks

# View leaderboard
tfp --api http://localhost:8000 leaderboard

# Publish content
tfp --api http://localhost:8000 publish --title "Hello World" --text "My first TFP post" --tags demo,hello

# Search content
tfp --api http://localhost:8000 search --tag demo

# Check node status
tfp --api http://localhost:8000 status
```

---

## 🎯 Advanced Demo Scenarios

### Scenario 1: Multi-Node Network Demo

**Experience the full power of decentralized content distribution**

```bash
# Start a 10-node testbed
docker compose -f docker-compose.testbed.yml up

# Operate the testbed
python tests/operate_testbed.py
```

**What this demonstrates:**
- 🌐 Multi-node peer-to-peer networking
- 📡 Content gossip and propagation
- 🔗 Nostr relay integration for peer discovery
- 📊 Network performance under load
- 🛡️ Byzantine fault tolerance

### Scenario 2: Compute Pool Participation

**Join the distributed compute network and earn credits**

```bash
# Terminal 1: Start the server
cd tfp-foundation-protocol
uvicorn tfp_demo.server:app --reload

# Terminal 2: Join as a compute worker
python -m tfp_cli.main join --device-id worker-1 --interval 5

# Terminal 3: Another worker
python -m tfp_cli.main join --device-id worker-2 --interval 5
```

**Watch the consensus mechanism in action:**
- Tasks are distributed across workers
- Results are verified via HABP consensus (3/5 agreement)
- Credits are minted only when consensus is reached
- Supply cap of 21M credits is enforced

### Scenario 3: Content Publishing with Nostr Integration

**Publish content that propagates across the Nostr network**

```bash
# Start with Nostr relay connection
NOSTR_RELAY=wss://relay.damus.io \
TFP_DB_PATH=./data/pib.db \
uvicorn tfp_demo.server:app --host 0.0.0.0 --port 8000

# Generate device identity
PUF_HEX=$(python3 -c "import os; print(os.urandom(32).hex())")

# Enroll device
curl -X POST http://localhost:8000/api/enroll \
  -H "Content-Type: application/json" \
  -d "{\"device_id\": \"my-node\", \"puf_entropy_hex\": \"${PUF_HEX}\"}"

# Publish content (will be announced on Nostr)
curl -X POST http://localhost:8000/api/publish \
  -H "Content-Type: application/json" \
  -H "X-Device-Sig: $(python3 -c "import hmac,hashlib; puf=bytes.fromhex('${PUF_HEX}'); print(hmac.new(puf, b'my-node:Hello Nostr', hashlib.sha256).hexdigest())")" \
  -d '{"device_id": "my-node", "title": "Hello Nostr", "text": "This content is on Nostr!", "tags": ["nostr", "demo"]}'
```

### Scenario 4: Performance Benchmarking

**Measure system performance under various conditions**

```bash
# Simple benchmark
python benchmark_simple.py

# Parallel chunk upload benchmark
python benchmark_parallel_chunk_upload.py

# Download/retrieval benchmark
python benchmark_download_retrieval.py

# RaptorQ encoding benchmark
python benchmark_raptorq.py
```

**Metrics measured:**
- Publish/retrieve latency
- Throughput (ops/sec)
- Encoding/decoding performance
- Network overhead
- Fault tolerance

---

## 🖥️ Admin Dashboard

Access the live admin dashboard to monitor the network:

```bash
# Start server
uvicorn tfp_demo.server:app --reload

# Open dashboard
open http://localhost:8000/admin
```

**Dashboard features:**
- 📊 Real-time task queue status
- 🏆 Device leaderboard (credits earned)
- 💰 Total credit supply tracking
- 🔄 Auto-refreshing metrics
- 📈 Supply cap visualization (21M max)

---

## 📊 Monitoring & Metrics

### Prometheus Metrics

```bash
curl http://localhost:8000/metrics
```

**Available metrics:**
- `tfp_tasks_total` - Total tasks processed
- `tfp_credits_minted` - Total credits minted
- `tfp_content_published` - Total content items
- `tfp_devices_enrolled` - Total enrolled devices
- `tfp_api_requests_total` - API request count
- `tfp_api_errors_total` - API error count

### Health Check

```bash
curl http://localhost:8000/health
```

Returns `200 OK` when the server is ready to accept requests.

---

## 🔧 Troubleshooting

### Windows Console Encoding Issues

If you see encoding errors on Windows, the demo script now handles this automatically by setting UTF-8 encoding.

### Port Already in Use

If port 8000 is already in use:

```bash
# Use a different port
uvicorn tfp_demo.server:app --port 8001
```

### Dependencies Missing

```bash
cd tfp-foundation-protocol
pip install -r requirements.txt
```

### Docker Issues

```bash
# Rebuild the container
docker compose up --build --force-recreate

# Check logs
docker compose logs tfp-demo
```

### Database Permissions

If you get database permission errors:

```bash
# Use in-memory database for testing
TFP_DB_PATH=:memory: uvicorn tfp_demo.server:app
```

---

## 🎓 Learning Path

### Beginner
1. Run `python demo_30sec.py` - Understand the basic flow
2. Open `http://localhost:8000` - Try the web interface
3. Read the README.md - Understand the architecture

### Intermediate
1. Join the compute pool with `tfp join`
2. Publish content with different tags
3. Experiment with the CLI commands
4. Monitor the admin dashboard

### Advanced
1. Set up a multi-node testbed
2. Integrate with Nostr relay
3. Run performance benchmarks
4. Explore the security model (SECURITY.md)
5. Contribute to the protocol

---

## 🌐 Production Deployment

For production deployment, see the detailed deployment guide:

```bash
# View deployment options
cat docs/deploy_demo.md
```

**Key production considerations:**
- Set `TFP_MODE=production` for hardened security
- Configure `TFP_PEER_SECRET` for peer authentication
- Set `TFP_ADMIN_DEVICE_IDS` for admin access control
- Use persistent storage (not `:memory:` database)
- Enable HTTPS with proper CORS configuration
- Set up monitoring and alerting

---

## 📚 Additional Resources

- **Integration Guide**: `tfp-foundation-protocol/docs/v3.0-integration-guide.md`
- **Security Model**: `tfp-foundation-protocol/docs/SECURITY.md`
- **Architecture**: `ARCHITECTURE.md`
- **API Documentation**: Interactive docs at `http://localhost:8000/docs`
- **Contributing**: `CONTRIBUTING.md`

---

## 💡 Demo Tips

1. **Start Simple**: Begin with the 30-second demo to understand the basic flow
2. **Explore Gradually**: Try each demo scenario in order
3. **Monitor Metrics**: Keep the admin dashboard open while experimenting
4. **Read Logs**: Watch server logs to understand what's happening
5. **Experiment**: Try different content, tags, and device identities
6. **Join the Community**: Check Nostr for #tfp tagged content

---

## 🎉 What Makes TFP Special?

- **Uncensorable**: Hash-based routing with no central server
- **Efficient**: RaptorQ erasure coding for low-bandwidth environments
- **Secure**: PUF/TEE identity with post-quantum crypto agility
- **Privacy-first**: Zero PII logging with device-bound identity
- **Inclusive**: Zero-config PWA installable on mobile devices
- **Economic**: Real pooled compute with credit-based incentives

This demo shows all these features in action!