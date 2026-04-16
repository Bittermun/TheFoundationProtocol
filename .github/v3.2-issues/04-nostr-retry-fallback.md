# [v3.2.1] Nostr Bridge Stability — Retry & Fallback

## Goal
Make Nostr relay connections resilient to failures: auto-retry with backoff, fallback to multiple relays, graceful degradation when all relays unavailable.

## Current State
Single relay configured via `NOSTR_RELAY` env var. If it fails:
- Content announcements fail silently
- Peer discovery stops
- HLT gossip stalls

## Technical Scope

### Phase 1: Multi-Relay Configuration (Complexity: Low)
**File:** `tfp_demo/server.py` — config parsing

Change from single to list:
```python
# Old
NOSTR_RELAY = "wss://relay.damus.io"

# New
NOSTR_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
]
```

Priority: First is primary, others are fallback.

### Phase 2: Connection Manager with Retry (Complexity: Medium)
**File:** `tfp_client/lib/bridges/nostr_connection.py` (new)

```python
class NostrConnectionManager:
    def __init__(self, relays: List[str]):
        self.relays = relays
        self.connections: Dict[str, WebSocket] = {}
        self.backoff = ExponentialBackoff(max_delay=300)

    async def publish(self, event: NostrEvent) -> List[str]:
        """Publish to all connected relays. Return list of successful relay URLs."""
        successes = []
        for relay in self.relays:
            try:
                await self._publish_to_relay(relay, event)
                successes.append(relay)
                self.backoff.reset(relay)  # Success, reset backoff
            except ConnectionError:
                delay = self.backoff.next_delay(relay)
                logger.warning(f"Relay {relay} failed, retry in {delay}s")
                asyncio.create_task(self._retry_later(relay, event, delay))

        if not successes:
            raise NoRelaysAvailable("All Nostr relays unreachable")

        return successes

    async def _retry_later(self, relay: str, event: NostrEvent, delay: float):
        await asyncio.sleep(delay)
        await self._publish_to_relay(relay, event)
```

### Phase 3: Graceful Degradation (Complexity: Medium)
**File:** `tfp_demo/server.py` — gossip control

When all relays fail:
- [ ] Pause outbound gossip (don't spam logs)
- [ ] Queue events in SQLite (`nostr_outbox` table)
- [ ] Retry every 60 seconds
- [ ] UI indicator: "Relay offline — operating in local mode"
- [ ] Still accept local API requests, just no peer discovery

### Phase 4: Relay Health Metrics (Complexity: Low)
**File:** `tfp_demo/server.py` — Prometheus metrics

Add counters:
```python
NOSTR_PUBLISH_SUCCESS = Counter('nostr_publish_success_total', 'Successful publishes', ['relay'])
NOSTR_PUBLISH_FAILURE = Counter('nostr_publish_failure_total', 'Failed publishes', ['relay'])
NOSTR_CONNECTION_STATUS = Gauge('nostr_connected', 'Connection status (1=up, 0=down)', ['relay'])
```

## Acceptance Criteria
- [ ] Configure 3 relays, primary fails, falls back to secondary
- [ ] Disconnect all relays, wait 2 min, reconnect when available
- [ ] Publish 100 events, < 5% failure rate with one relay down
- [ ] All events eventually published when relays return (queue drains)
- [ ] Metrics show per-relay success/failure rates
- [ ] No memory leak during extended offline period (> 24 hours)

## Configuration

```yaml
# docker-compose.yml or env
NOSTR_RELAYS: "wss://relay.damus.io,wss://nos.lol,wss://relay.nostr.band"
NOSTR_RETRY_MAX_DELAY: "300"  # seconds
NOSTR_RETRY_EXPONENTIAL_BASE: "2"
NOSTR_QUEUE_MAX_SIZE: "10000"  # events to queue when offline
```

## Database Schema

```sql
CREATE TABLE nostr_outbox (
    event_id TEXT PRIMARY KEY,
    event_json TEXT,
    attempts INTEGER DEFAULT 0,
    last_attempt REAL,
    created_at REAL DEFAULT (unixepoch())
);

-- Index for draining queue
CREATE INDEX idx_outbox_attempts ON nostr_outbox(attempts, last_attempt);
```

## Good First Sub-Issues
1. **Exponential backoff utility** — `ExponentialBackoff` class with tests
2. **Relay health checker** — Ping relay every 30s, update gauge
3. **SQLite outbox queue** — Basic `INSERT` / `SELECT` for events
4. **Metrics exporter** — Wire up Prometheus counters

## Estimated Effort
- Network engineer: 1 week
- Generalist: 2 weeks

## Priority
**P2** — Important for production reliability, not blocking v3.2.0

## Testing Strategy

**Chaos test:**
1. Start with 3 relays connected
2. Kill primary (iptables DROP)
3. Verify fallback to secondary within 5 seconds
4. Kill all 3 relays
5. Verify events queue, no crash
6. Restore one relay
7. Verify queue drains, all events published

---

## Related
- Issue #01 (Distributed Matrix) — needs reliable gossip for shard coordination
- Issue #02 (Radio App) — playlist sharing depends on Nostr
