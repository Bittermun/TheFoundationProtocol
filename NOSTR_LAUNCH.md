# Nostr Launch — TFP v3.1

## Simple Authentic Post

Copy and paste this to Primal/Damus when ready:

```
Built a decentralized content protocol. High school, one week of focused coding.

TFP (The Foundation Protocol) — publish and share content without a central server.

- 42k LOC, 749+ tests
- Nostr for discovery, IPFS for persistence
- Offline-first PWA
- docker compose up → works in 5 minutes

Code: github.com/Bittermun/TheFoundationProtocol

What should I build next?

#nostr #opensource #p2p
```

## Optional Follow-ups

Only if people engage:

**Technical thread** (if asked how it works):
- Content-addressed (not server-addressed)
- Nostr events for peer discovery
- HABP consensus for distributed compute
- SQLite + RaptorQ for efficiency

**Demo link** (after deploying):
- Try it: https://tfp-demo.fly.dev
- Or run locally: docker compose up

---

*Keep it simple. One post is enough.*

---

## Post 2: Technical Thread (Day 2)

**Template:**
```
How TFP works (technical thread):

1/ Content addressing
Everything is hashed. Request by content ID, not server IP.
Works even if your ISP blocks domains.

2/ Nostr for discovery
Peers announce content via Nostr events. No central registry.
Subscribe to tags, get new content automatically.

3/ IPFS for persistence
Content pinned to IPFS. If my server dies, you can still fetch from any IPFS node.

4/ HABP consensus for compute
Devices earn credits by doing verifiable work (hash preimage, matrix verify).
3/5 devices must agree — no single point of failure.

5/ SQLite + erasure coding
Local database with WAL mode. RaptorQ for bandwidth efficiency.
Survives restarts, works on Raspberry Pi.

Code: github.com/Bittermun/TheFoundationProtocol

#nostr #ipfs #p2p #buildinpublic
```

**When to post:** Tomorrow morning (8-10am gets technical crowd)

---

## Post 3: Live Demo (Day 3)

**Template:**
```
TFP demo node is LIVE:

https://tfp-demo.fly.dev

Try it:
- Browse content
- See the compute pool leaderboard
- Join with CLI: tfp join

Running on Fly.io free tier. Single container, 512MB RAM.

If it goes down, I'll restart it. If it stays down, the protocol still works — just need another node.

That's the point.

#nostr #decentralization #demo
```

**Prerequisite:** You must deploy first (see deploy-fly.sh)

---

## Post 4: The "Why" (Day 5)

**Template:**
```
Why I built TFP:

Last summer, I was in [place with bad internet].
Couldn't access basic information. Sites blocked. Slow. Expensive.

Realized: the internet works great if you're near a data center.
Sucks if you're not.

TFP is designed for:
- Low connectivity
- Censorship resistance
- Community hosting

Not trying to replace the internet. Trying to make it work for more people.

High schooler. 1 week of focused coding. Open source.

What should I build next?

#nostr #offlinefirst #censorship #buildinpublic
```

**Note:** Adjust "last summer" to your real story or make it hypothetical. Authenticity > dramatic fiction.

---

## Post 5: v3.2 Plans (Day 7)

**Template:**
```
TFP v3.2 roadmap — what's coming:

🔧 Pooled compute
Distribute matrix multiply across multiple devices. Real workloads, not just proofs.

🎧 Radio app MVP
Offline-first audio player for NGOs. Podcasts, education, emergency info.

📁 Large file support
100MB - 10GB files. Movies, music, datasets. Optimized RaptorQ.

🔄 Nostr relay resilience
Multi-relay fallback. Queue when offline, resume when connected.

Specs: github.com/Bittermun/TheFoundationProtocol/tree/main/.github/v3.2-issues

Looking for:
- Testers (run a node, report bugs)
- Users (what content do you need distributed?)
- Contributors (Python, PWA, networking)

#nostr #opensource #roadmap #p2p
```

---

## Engagement Tactics

### Reply Strategy
When someone comments:
- **Technical question** → Answer with code snippet
- "Cool" → "Thanks! Try the demo: [link]"
- "What's this for?" → "Who needs offline content access?"
- Criticism → "Good point. Filed issue #[number]."

### Cross-Posting
- Same content works on Primal, Damus, Amethyst
- Use same hashtags
- Reply to your own posts to form threads

### Timing
- **Morning** (8-10am US time): Technical crowd
- **Evening** (6-8pm): Casual browsers
- Avoid 12-2pm (lunch dead zone)

---

## Hashtag Strategy

**Always use:**
- #nostr (protocol uses it)
- #bitcoin (Nostr audience overlap)
- #opensource (accurate)

**Rotate these:**
- #buildinpublic (engagement)
- #p2p (accurate description)
- #decentralization (accurate)
- #ipfs (uses it)
- #offlinefirst (key feature)

**Avoid:**
- #web3 (too broad, scam association)
- #crypto (wrong kind)
- #ai (not relevant)

---

## Measuring Success

| Metric | Good | Great |
|--------|------|-------|
| Post 1 likes | 20+ | 100+ |
| Demo clicks | 5+ | 20+ |
| GitHub stars (week 1) | 10+ | 50+ |
| Someone runs node | 1 | 5+ |
| Contributor appears | 0 | 1+ |

**Don't panic if low:** You're a high schooler with no followers. 20 likes is huge.

---

## Emergency Backup Plan

If Post 1 gets 0 engagement:
1. Wait 24 hours
2. Repost with different hook: "What if YouTube worked offline?"
3. Tag 3 specific people who care about this (find them first)
4. Try again

If still nothing: The content is fine, the timing is wrong. Try again in a week.

---

## Primal-Specific Tips

1. **Pin your best post** — Profile shows pinned first
2. **Use zaps strategically** — Zap thoughtful replies, get visibility
3. **Followback everyone** — Small community, reciprocity matters
4. **Use long-form** — Primal supports markdown, write detailed threads

---

## Ready to Post?

**Checklist:**
- [ ] GitHub repo is public
- [ ] README is current
- [ ] Demo is deployed (or ready to deploy)
- [ ] You have 30 min to respond to replies

**Go live when ready. Don't wait for perfect.**

---

*Drafted: 2026-04-13*
*Post 1 is ready to copy-paste*
