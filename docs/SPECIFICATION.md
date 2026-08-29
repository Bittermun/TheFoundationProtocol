# The Foundation Protocol (TFP) v3.2 Formal Specification

## 1. Abstract & System Architecture

The Foundation Protocol (TFP) is a decentralized, high-efficiency information sharing and receiving protocol optimized for lossy, low-bandwidth, or adversarial networks. It combines **Content-Defined Chunking (FastCDC)**, **Systematic Fountain Coding (RaptorQ / RFC 6330)**, and **Merkleized Droplet Authentication** to achieve:

1. **Sub-linear Bandwidth Consumption:** Up to 70–90% deduplication of repeated text, binary, and media templates.
2. **Zero-Retransmission Loss Recovery:** Any $k$ received packets out of $n$ transmitted droplets reconstruct original content without round-trip retransmission requests.
3. **Poisoned Shard Immunity:** Shard authentication via constant-time SHA3-256 Merkle proofs rejects corrupt packets before CPU-intensive decoding.

```
                          [ Raw Payload ]
                                 |
                                 v
                +---------------------------------+
                |   FastCDC 64-bit Chunk Engine   |
                +---------------------------------+
                    /            |            \
               [Chunk 1]     [Chunk 2]     [Chunk 3]
                    \            |            /
                     v           v           v
                +---------------------------------+
                |     RFC 6330 RaptorQ Engine     |
                +---------------------------------+
                    /      |     |     |      \
                [d_0]    [d_1] [d_2] [d_3]   [d_4] (Repair)
                    \      |     |     |      /
                     v     v     v     v     v
                +---------------------------------+
                |      Merkle Transport Layer     |  <-- Cryptographic Proof Root
                +---------------------------------+
                                 |
                                 v
                    [ Nostr Gossip / P2P Mesh ]
```

---

## 2. Layer 1: Content-Defined Chunking (FastCDC)

### 2.1 Algorithm & Matrix
Chunk boundaries are determined using the 64-bit Gear rolling hash matrix $\mathbf{G} \in \mathbb{Z}_{2^{64}}^{256}$ (USENIX ATC '16 standard).

For a byte sequence $B = [b_0, b_1, \dots, b_{n-1}]$, the rolling state $H_t$ is updated:
$$H_{t+1} = ((H_t \ll 1) + \mathbf{G}[b_t]) \pmod{2^{64}}$$

### 2.2 Normalized Dual-Masking
To avoid pathological chunk sizes, chunking is normalized across two regions:
* **Region A ($[\text{MinSize}, \text{TargetSize})$):** Evaluated against strict mask $\text{Mask}_S = 2^{\lfloor\log_2 \text{TargetSize}\rfloor + 1} - 1$.
* **Region B ($[\text{TargetSize}, \text{MaxSize})$):** Evaluated against relaxed mask $\text{Mask}_L = 2^{\lfloor\log_2 \text{TargetSize}\rfloor - 1} - 1$.

```
+----------------+--------------------------+--------------------------+
| 0 .. MinSize   | MinSize .. TargetSize    | TargetSize .. MaxSize    |
| (Skip window)  | (Tighter Mask_S trigger) | (Looser Mask_L trigger)  |
+----------------+--------------------------+--------------------------+
```

### 2.3 Chunk Recipe Format
A file is uniquely identified and reconstructed by its `ChunkRecipe`:
```json
{
  "total_size": 1048576,
  "root_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "chunk_hashes": [
    "5d41402abc4b2a76b9719d911017c592...",
    "7d88382497b53a7b6b7a5a8747f44d82..."
  ],
  "chunk_sizes": [65536, 65536]
}
```

---

## 3. Layer 2: RaptorQ (RFC 6330) & Binary Framing

### 3.1 Systematic Coding Properties
Given $K$ source symbols of size $S$, the encoder generates $N = K + R$ symbols such that receiving **any** $K' \approx K$ symbols allows 100% complete matrix reconstruction via Gaussian elimination / inactivation decoding over $GF(256)$ or $GF(2)$.

### 3.2 Binary Shard Frame Layout
Each transmitted droplet is framed with a standard 16-byte header:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                  Original Payload Size (uint64)              |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       Source Symbols K (uint32) |   Encoding Symbol ID (uint32)|
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     Payload Data (S bytes) ...                |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|             Optional HMAC-SHA3-256 Digest (32 bytes)          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

---

## 4. Layer 3: Merkle Droplet Authentication

Before passing any droplet to the decoding pipeline, the receiver verifies the cryptographic leaf proof against the known `RootHash`:

1. Leaf hash computed: $H_{\text{leaf}} = \text{SHA3-256}(\text{DropletPayload})$.
2. Proof path traversed:
   $$H_{i+1} = \text{SHA3-256}(H_i \parallel H_{\text{sibling}})$$
3. If $H_{\text{final}} \neq \text{RootHash}$, the droplet is dropped immediately. This protects decoding memory and CPU cycles from malformed/poisoned packets.

---

## 5. Layer 4: Nostr Event Discovery Schema

To announce available recipes and payloads without a central tracking server, nodes publish signed Nostr events (NIP-01 / NIP-77 compatible):

```json
{
  "kind": 30078,
  "pubkey": "<64-hex-sender-pubkey>",
  "created_at": 1772150000,
  "tags": [
    ["d", "tfp:recipe:<root_hash>"],
    ["t", "tfp-content"],
    ["h", "<root_hash>"],
    ["k", "<source_symbol_count>"],
    ["s", "<total_size_bytes>"]
  ],
  "content": "<compact_json_recipe_or_relay_hints>",
  "sig": "<schnorr_signature>"
}
```

---

## 6. Verification and Invariant Guarantees

| Invariant | Guarantee | Mathematical Mechanism |
| :--- | :--- | :--- |
| **Shift Resistance** | Inserting $m$ bytes alters at most $O(1)$ chunk boundaries. | Content-Defined FastCDC Gear Hash. |
| **Loss Resilience** | Zero data loss for any drop rate $\le \frac{R}{K+R}$. | Systematic RaptorQ / Fountain code. |
| **Data Integrity** | $0\%$ chance of undetected corrupted packet injection. | Constant-time SHA3-256 Merkle proofs. |
| **Deterministic Identity** | Identical content produces identical CIDs across all nodes. | Canonical SHA3-256 / BLAKE3 root addressing. |
