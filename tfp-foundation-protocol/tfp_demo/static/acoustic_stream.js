// SPDX-License-Identifier: Apache-2.0
// Incremental Bell 202 / 1200-baud reception. Each timing hypothesis retains
// less than one symbol of PCM and at most one 4096-byte frame, never audio history.
class IncrementalAFSKReceiver {
  constructor(sampleRate, onPacket) {
    if (!Number.isFinite(sampleRate) || sampleRate < 8000 || sampleRate > 96000) {
      throw new Error('Supported audio sample rates: 8000–96000 Hz');
    }
    this.sampleRate = sampleRate;
    this.onPacket = onPacket;
    this.base = 0;
    this.buffer = new Float32Array(0);
    this.maxBufferedSamples = 0;
    this.seen = new Set();
    this.hypotheses = [];
    for (const drift of [0, -0.015, 0.015]) {
      const step = sampleRate / 1200 * (1 + drift);
      const width = Math.round(step);
      const stride = Math.max(1, Math.round(width / 8));
      for (let offset = 0; offset < width; offset += stride) {
        this.hypotheses.push({step, next: offset, shift: 0, bits: 0, nextByte: 0,
                              state: 0, flags: 0, payload: null, length: 0, index: 0});
      }
    }
  }

  resetFrame(h) { h.state = 0; h.payload = null; h.index = 0; h.flags = 0; }

  bit(h, value) {
    h.shift = (h.shift >>> 1) | (value << 7);
    h.bits++;
    if (h.state === 0) {
      if (h.bits >= 8 && h.shift === 0x7e) {
        h.state = 1; h.flags = 1; h.nextByte = h.bits + 8;
      }
      return;
    }
    if (h.bits < h.nextByte) return;
    h.nextByte += 8;
    const byte = h.shift;
    if (h.state === 1) {
      if (byte === 0x7e) { h.flags++; return; }
      if (h.flags < 2) { this.resetFrame(h); return; }
      h.length = byte << 8; h.state = 2;
    } else if (h.state === 2) {
      h.length |= byte;
      if (h.length < 1 || h.length > 4096) { this.resetFrame(h); return; }
      h.payload = new Uint8Array(h.length); h.index = 0; h.state = 3;
    } else if (h.state === 3) {
      h.payload[h.index++] = byte;
      if (h.index === h.length) h.state = 4;
    } else if (h.state === 4) {
      h.crc = byte << 8; h.state = 5;
    } else {
      if (crc16Ccitt(h.payload) === (h.crc | byte)) {
        const key = Array.from(h.payload, b => b.toString(16).padStart(2, '0')).join('');
        if (!this.seen.has(key)) {
          this.seen.add(key);
          if (this.seen.size > 128) this.seen.delete(this.seen.values().next().value);
          this.onPacket(h.payload);
        }
      }
      this.resetFrame(h);
    }
  }

  push(samples) {
    // Bound work buffers even when a file caller supplies a whole recording.
    for (let offset = 0; offset < samples.length; offset += 2048) {
      const block = samples.subarray ? samples.subarray(offset, offset + 2048) : samples.slice(offset, offset + 2048);
      const combined = new Float32Array(this.buffer.length + block.length);
      combined.set(this.buffer); combined.set(block, this.buffer.length);
      this.buffer = combined;
      this.maxBufferedSamples = Math.max(this.maxBufferedSamples, combined.length);
      const available = this.base + combined.length;
      for (const h of this.hypotheses) {
        while (Math.round(h.next + h.step) <= available) {
          const start = Math.round(h.next), end = Math.round(h.next + h.step);
          let im = 0, qm = 0, is = 0, qs = 0;
          for (let j = start; j < end; j++) {
            const x = combined[j - this.base];
            const t = j * 2 * Math.PI / this.sampleRate;
            im += x * Math.cos(1200 * t); qm += x * Math.sin(1200 * t);
            is += x * Math.cos(2200 * t); qs += x * Math.sin(2200 * t);
          }
          this.bit(h, im * im + qm * qm >= is * is + qs * qs ? 1 : 0);
          h.next += h.step;
        }
      }
      const consumed = Math.min(...this.hypotheses.map(h => Math.round(h.next))) - this.base;
      this.buffer = combined.slice(consumed);
      this.base += consumed;
    }
  }
}
window.IncrementalAFSKReceiver = IncrementalAFSKReceiver;

// ============================================================================
// Phase D: Canonical Bulletin Envelope & Ed25519 / SHA3-256 Verification
// Matches Python tfp_core_v4/bulletin_identity.py bit-for-bit.
// ============================================================================

const KECCAK_ROUNDS = 24;
const KECCAK_ROTC = [
  1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 2, 14,
  27, 41, 56, 8, 25, 43, 62, 18, 39, 61, 20, 44
];
const KECCAK_PILN = [
  10, 7, 11, 17, 18, 3, 5, 16, 8, 21, 24, 4,
  15, 23, 19, 13, 12, 2, 20, 14, 22, 9, 6, 1
];
const KECCAK_RC = (() => {
  const rc = [];
  let r = 1;
  for (let round = 0; round < KECCAK_ROUNDS; round++) {
    let c = 0n;
    for (let j = 0; j < 7; j++) {
      if (r & 1) {
        c |= 1n << BigInt((1 << j) - 1);
      }
      r = (r << 1) ^ ((r & 0x80) ? 0x171 : 0);
    }
    rc.push(c);
  }
  return rc;
})();

const MASK_64 = 0xffffffffffffffffn;
function rotl64(x, n) {
  const b = BigInt(n);
  return ((x << b) | (x >> (64n - b))) & MASK_64;
}

function keccakF1600(state) {
  const bc = new Array(5);
  for (let round = 0; round < KECCAK_ROUNDS; round++) {
    for (let i = 0; i < 5; i++) {
      bc[i] = state[i] ^ state[i + 5] ^ state[i + 10] ^ state[i + 15] ^ state[i + 20];
    }
    for (let i = 0; i < 5; i++) {
      const t = bc[(i + 4) % 5] ^ rotl64(bc[(i + 1) % 5], 1);
      for (let j = 0; j < 25; j += 5) {
        state[j + i] ^= t;
      }
    }
    let t = state[1];
    for (let i = 0; i < 24; i++) {
      const j = KECCAK_PILN[i];
      const tmp = state[j];
      state[j] = rotl64(t, KECCAK_ROTC[i]);
      t = tmp;
    }
    for (let j = 0; j < 25; j += 5) {
      for (let i = 0; i < 5; i++) bc[i] = state[j + i];
      for (let i = 0; i < 5; i++) {
        state[j + i] ^= (~bc[(i + 1) % 5] & MASK_64) & bc[(i + 2) % 5];
      }
    }
    state[0] ^= KECCAK_RC[round];
  }
}

function sha3_256Bytes(input) {
  const msg = (typeof input === 'string') ? new TextEncoder().encode(input) : new Uint8Array(input);
  const rateBytes = 136; // 1088 bits for SHA3-256
  const state = new Array(25).fill(0n);
  const block = new Uint8Array(rateBytes);

  let offset = 0;
  while (offset + rateBytes <= msg.length) {
    for (let i = 0; i < rateBytes / 8; i++) {
      let lane = 0n;
      for (let b = 0; b < 8; b++) {
        lane |= BigInt(msg[offset + i * 8 + b]) << BigInt(b * 8);
      }
      state[i] ^= lane;
    }
    keccakF1600(state);
    offset += rateBytes;
  }

  const rem = msg.length - offset;
  block.fill(0);
  for (let i = 0; i < rem; i++) block[i] = msg[offset + i];
  block[rem] = 0x06; // SHA-3 domain suffix
  block[rateBytes - 1] |= 0x80;

  for (let i = 0; i < rateBytes / 8; i++) {
    let lane = 0n;
    for (let b = 0; b < 8; b++) {
      lane |= BigInt(block[i * 8 + b]) << BigInt(b * 8);
    }
    state[i] ^= lane;
  }
  keccakF1600(state);

  const out = new Uint8Array(32);
  for (let i = 0; i < 4; i++) {
    const lane = state[i];
    for (let b = 0; b < 8; b++) {
      out[i * 8 + b] = Number((lane >> BigInt(b * 8)) & 0xffn);
    }
  }
  return out;
}

function sha3_256Hex(input) {
  const bytes = sha3_256Bytes(input);
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}

// FIPS 180-4 SHA-512 (synchronous implementation for RFC 8032 Ed25519)
const SHA512_K_EXACT = [
  0x428a2f98d728ae22n, 0x7137449123ef65cdn, 0xb5c0fbcfec4d3b2fn, 0xe9b5dba58189dbbcn,
  0x3956c25bf348b538n, 0x59f111f1b605d019n, 0x923f82a4af194f9bn, 0xab1c5ed5da6d8118n,
  0xd807aa98a3030242n, 0x12835b0145706fben, 0x243185be4ee4b28cn, 0x550c7dc3d5ffb4e2n,
  0x72be5d74f27b896fn, 0x80deb1fe3b1696b1n, 0x9bdc06a725c71235n, 0xc19bf174cf692694n,
  0xe49b69c19ef14ad2n, 0xefbe4786384f25e3n, 0x0fc19dc68b8cd5b5n, 0x240ca1cc77ac9c65n,
  0x2de92c6f592b0275n, 0x4a7484aa6ea6e483n, 0x5cb0a9dcbd41fbd4n, 0x76f988da831153b5n,
  0x983e5152ee66dfabn, 0xa831c66d2db43210n, 0xb00327c898fb213fn, 0xbf597fc7beef0ee4n,
  0xc6e00bf33da88fc2n, 0xd5a79147930aa725n, 0x06ca6351e003826fn, 0x142929670a0e6e70n,
  0x27b70a8546d22ffcn, 0x2e1b21385c26c926n, 0x4d2c6dfc5ac42aedn, 0x53380d139d95b3dfn,
  0x650a73548baf63den, 0x766a0abb3c77b2a8n, 0x81c2c92e47edaee6n, 0x92722c851482353bn,
  0xa2bfe8a14cf10364n, 0xa81a664bbc423001n, 0xc24b8b70d0f89791n, 0xc76c51a30654be30n,
  0xd192e819d6ef5218n, 0xd69906245565a910n, 0xf40e35855771202an, 0x106aa07032bbd1b8n,
  0x19a4c116b8d2d0c8n, 0x1e376c085141ab53n, 0x2748774cdf8eeb99n, 0x34b0bcb5e19b48a8n,
  0x391c0cb3c5c95a63n, 0x4ed8aa4ae3418acbn, 0x5b9cca4f7763e373n, 0x682e6ff3d6b2b8a3n,
  0x748f82ee5defb2fcn, 0x78a5636f43172f60n, 0x84c87814a1f0ab72n, 0x8cc702081a6439ecn,
  0x90befffa23631e28n, 0xa4506cebde82bde9n, 0xbef9a3f7b2c67915n, 0xc67178f2e372532bn,
  0xca273eceea26619cn, 0xd186b8c721c0c207n, 0xeada7dd6cde0eb1en, 0xf57d4f7fee6ed178n,
  0x06f067aa72176fban, 0x0a637dc5a2c898a6n, 0x113f9804bef90daen, 0x1b710b35131c471bn,
  0x28db77f523047d84n, 0x32caab7b40c72493n, 0x3c9ebe0a15c9bebcn, 0x431d67c49c100d4cn,
  0x4cc5d4becb3e42b6n, 0x597f299cfc657e2an, 0x5fcb6fab3ad6faecn, 0x6c44198c4a475817n
];

const SHA512_H0 = [
  0x6a09e667f3bcc908n, 0xbb67ae8584caa73bn, 0x3c6ef372fe94f82bn, 0xa54ff53a5f1d36f1n,
  0x510e527fade682d1n, 0x9b05688c2b3e6c1fn, 0x1f83d9abfb41bd6bn, 0x5be0cd19137e2179n
];

function rotr64(x, n) {
  const b = BigInt(n);
  return ((x >> b) | (x << (64n - b))) & MASK_64;
}

function sha512Bytes(msgBytes) {
  const msg = new Uint8Array(msgBytes);
  const bitLen = BigInt(msg.length) * 8n;
  const padLen = ((msg.length + 17 + 127) & ~127);
  const padded = new Uint8Array(padLen);
  padded.set(msg);
  padded[msg.length] = 0x80;
  for (let i = 0; i < 8; i++) {
    padded[padLen - 1 - i] = Number((bitLen >> BigInt(i * 8)) & 0xffn);
  }

  let [h0, h1, h2, h3, h4, h5, h6, h7] = SHA512_H0;
  const w = new Array(80).fill(0n);

  for (let offset = 0; offset < padLen; offset += 128) {
    for (let i = 0; i < 16; i++) {
      let word = 0n;
      for (let b = 0; b < 8; b++) {
        word = (word << 8n) | BigInt(padded[offset + i * 8 + b]);
      }
      w[i] = word;
    }
    for (let i = 16; i < 80; i++) {
      const s0 = rotr64(w[i - 15], 1) ^ rotr64(w[i - 15], 8) ^ (w[i - 15] >> 7n);
      const s1 = rotr64(w[i - 2], 19) ^ rotr64(w[i - 2], 61) ^ (w[i - 2] >> 6n);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & MASK_64;
    }

    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
    for (let i = 0; i < 80; i++) {
      const S1 = rotr64(e, 14) ^ rotr64(e, 18) ^ rotr64(e, 41);
      const ch = (e & f) ^ ((~e & MASK_64) & g);
      const temp1 = (h + S1 + ch + SHA512_K_EXACT[i] + w[i]) & MASK_64;
      const S0 = rotr64(a, 28) ^ rotr64(a, 34) ^ rotr64(a, 39);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) & MASK_64;

      h = g; g = f; f = e;
      e = (d + temp1) & MASK_64;
      d = c; c = b; b = a;
      a = (temp1 + temp2) & MASK_64;
    }

    h0 = (h0 + a) & MASK_64;
    h1 = (h1 + b) & MASK_64;
    h2 = (h2 + c) & MASK_64;
    h3 = (h3 + d) & MASK_64;
    h4 = (h4 + e) & MASK_64;
    h5 = (h5 + f) & MASK_64;
    h6 = (h6 + g) & MASK_64;
    h7 = (h7 + h) & MASK_64;
  }

  const out = new Uint8Array(64);
  const hs = [h0, h1, h2, h3, h4, h5, h6, h7];
  for (let i = 0; i < 8; i++) {
    for (let b = 0; b < 8; b++) {
      out[i * 8 + b] = Number((hs[i] >> BigInt((7 - b) * 8)) & 0xffn);
    }
  }
  return out;
}

// RFC 8032 Ed25519 Curve Math
const ED_P = (1n << 255n) - 19n;
const ED_L = (1n << 252n) + 27742317777372353535851937790883648493n;

function mod(a, m = ED_P) {
  const r = a % m;
  return r >= 0n ? r : r + m;
}

function modPow(base, exp, m = ED_P) {
  let res = 1n;
  let b = mod(base, m);
  let e = exp;
  while (e > 0n) {
    if (e & 1n) res = (res * b) % m;
    b = (b * b) % m;
    e >>= 1n;
  }
  return res;
}

function modInv(a, m = ED_P) {
  return modPow(a, m - 2n, m);
}

const ED_D = mod(-121665n * modInv(121666n));
const ED_I = modPow(2n, (ED_P - 1n) / 4n);

function edRecoverX(y, sign) {
  if (y >= ED_P) return null;
  const y2 = mod(y * y);
  const u = mod(y2 - 1n);
  const v = mod(ED_D * y2 + 1n);
  let x = mod(u * modPow(v, 3n) * modPow(mod(u * modPow(v, 7n)), (ED_P - 5n) / 8n));
  const vx2 = mod(v * x * x);
  if (vx2 !== u) {
    if (vx2 === mod(-u)) {
      x = mod(x * ED_I);
    } else {
      return null;
    }
  }
  if (x === 0n && sign === 1n) return null;
  if ((x & 1n) !== sign) x = ED_P - x;
  return x;
}

const ED_BY = mod(4n * modInv(5n));
const ED_BX = edRecoverX(ED_BY, 0n);
const ED_B = [ED_BX, ED_BY, 1n, mod(ED_BX * ED_BY)];

function edPointAdd(P, Q) {
  const [X1, Y1, Z1, T1] = P;
  const [X2, Y2, Z2, T2] = Q;
  const A = mod((Y1 - X1) * (Y2 - X2));
  const B = mod((Y1 + X1) * (Y2 + X2));
  const C = mod(2n * ED_D * T1 * T2);
  const D = mod(2n * Z1 * Z2);
  const E = mod(B - A);
  const F = mod(D - C);
  const G = mod(D + C);
  const H = mod(B + A);
  return [mod(E * F), mod(G * H), mod(F * G), mod(E * H)];
}

function edScalarMult(P, s) {
  let R = [0n, 1n, 1n, 0n];
  let Q = P;
  let k = s;
  while (k > 0n) {
    if (k & 1n) R = edPointAdd(R, Q);
    Q = edPointAdd(Q, Q);
    k >>= 1n;
  }
  return R;
}

function edDecodePoint(bytes32) {
  if (!bytes32 || bytes32.length !== 32) return null;
  let y = 0n;
  for (let i = 0; i < 32; i++) {
    y |= BigInt(bytes32[i]) << BigInt(i * 8);
  }
  const sign = (y >> 255n) & 1n;
  y &= (1n << 255n) - 1n;
  const x = edRecoverX(y, sign);
  if (x === null) return null;
  return [x, y, 1n, mod(x * y)];
}

function edPointsEqual(P, Q) {
  const [X1, Y1, Z1] = P;
  const [X2, Y2, Z2] = Q;
  return mod(X1 * Z2 - X2 * Z1) === 0n && mod(Y1 * Z2 - Y2 * Z1) === 0n;
}

function hexToBytes(hex) {
  if (typeof hex !== 'string' || hex.length % 2 !== 0 || !/^[0-9a-fA-F]+$/.test(hex)) {
    return null;
  }
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

function bytesToLittleEndianBigInt(bytes) {
  let v = 0n;
  for (let i = 0; i < bytes.length; i++) {
    v |= BigInt(bytes[i]) << BigInt(i * 8);
  }
  return v;
}

function ed25519VerifySync(pubKeyHex, sigHex, messageBytes) {
  const pubBytes = hexToBytes(pubKeyHex);
  const sigBytes = hexToBytes(sigHex);
  if (!pubBytes || pubBytes.length !== 32 || !sigBytes || sigBytes.length !== 64) {
    return false;
  }
  const R_bytes = sigBytes.subarray(0, 32);
  const S_bytes = sigBytes.subarray(32, 64);
  const S = bytesToLittleEndianBigInt(S_bytes);
  if (S >= ED_L) return false;

  const A = edDecodePoint(pubBytes);
  const R = edDecodePoint(R_bytes);
  if (!A || !R) return false;

  const msg = (typeof messageBytes === 'string')
    ? new TextEncoder().encode(messageBytes)
    : new Uint8Array(messageBytes);
  const hashInput = new Uint8Array(64 + msg.length);
  hashInput.set(R_bytes, 0);
  hashInput.set(pubBytes, 32);
  hashInput.set(msg, 64);

  const kHash = sha512Bytes(hashInput);
  const k = mod(bytesToLittleEndianBigInt(kHash), ED_L);

  const lhs = edScalarMult(ED_B, S);
  const rhs = edPointAdd(R, edScalarMult(A, k));
  return edPointsEqual(lhs, rhs);
}

async function verifyBulletinSignatureWebCrypto(pubKeyHex, sigHex, messageBytes) {
  const pubBytes = hexToBytes(pubKeyHex);
  const sigBytes = hexToBytes(sigHex);
  if (!pubBytes || pubBytes.length !== 32 || !sigBytes || sigBytes.length !== 64) {
    return { supported: false, valid: false, engine: 'invalid_hex_length' };
  }
  const msg = (typeof messageBytes === 'string')
    ? new TextEncoder().encode(messageBytes)
    : new Uint8Array(messageBytes);

  if (typeof window !== 'undefined' && window.crypto && window.crypto.subtle) {
    try {
      const cryptoKey = await window.crypto.subtle.importKey(
        'raw',
        pubBytes,
        { name: 'Ed25519' },
        false,
        ['verify']
      );
      const valid = await window.crypto.subtle.verify(
        { name: 'Ed25519' },
        cryptoKey,
        sigBytes,
        msg
      );
      return { supported: true, valid: Boolean(valid), engine: 'WebCrypto-Ed25519' };
    } catch (_) {
      // Fallback if the platform browser does not support Ed25519 in SubtleCrypto
    }
  }
  const syncValid = ed25519VerifySync(pubKeyHex, sigHex, msg);
  return { supported: false, valid: syncValid, engine: 'JS-RFC8032-Fallback' };
}

function normalizeBulletinBody(body) {
  if (typeof body !== 'string') return '';
  return body.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

function canonicalBulletinEnvelope(bulletinId, revision, title, contentHash, publisherId, version = 2) {
  const effectiveTitle = (title !== undefined && title !== null && title !== '') ? title : bulletinId;
  if (version !== 2) {
    throw new Error('Legacy or unsupported signature envelope; reissue using version 2');
  }
  return JSON.stringify(['TFP_BULLETIN', 2, bulletinId, revision, effectiveTitle, contentHash, publisherId]);
}

function validateBulletinIdentityFields(wireObj) {
  if (!wireObj || typeof wireObj !== 'object' || Array.isArray(wireObj)) {
    return { ok: false, reason: 'Payload is not a JSON object' };
  }
  const id = wireObj.id;
  const rev = wireObj.rev;
  const title = wireObj.title !== undefined && wireObj.title !== null ? wireObj.title : id;
  const body = wireObj.body;

  if (typeof id !== 'string' || !id.trim()) {
    return { ok: false, reason: 'bulletin_id must be a nonempty string' };
  }
  if (typeof rev !== 'number' || typeof rev === 'boolean' || !Number.isSafeInteger(rev) || rev < 1) {
    return { ok: false, reason: 'revision must be a positive safe integer' };
  }
  if (typeof title !== 'string') {
    return { ok: false, reason: 'title must be a string' };
  }
  if (typeof body !== 'string' || body.length === 0) {
    return { ok: false, reason: 'Bulletin body must be a nonempty string' };
  }
  return { ok: true, id, rev, title: title || id, body };
}

function verifyBulletinEnvelope(wireObj, trustedPublishers = [], options = {}) {
  const strictSignedClaim = options.strictSignedClaim !== undefined ? Boolean(options.strictSignedClaim) : true;
  const fieldCheck = validateBulletinIdentityFields(wireObj);
  if (!fieldCheck.ok) {
    return {
      validFields: false,
      verification: 'invalid_fields',
      pythonVerifiedStatus: 'invalid_fields',
      publisherTrust: 'not_established',
      contentHash: null,
      canonicalEnvelope: null,
      publisher: 'unsigned',
      reason: fieldCheck.reason
    };
  }

  const { id, rev, title, body } = fieldCheck;
  const normalizedBody = normalizeBulletinBody(body);
  const contentHash = sha3_256Hex(normalizedBody);
  const rawPub = (wireObj.pub !== undefined && wireObj.pub !== null && String(wireObj.pub).trim() !== '')
    ? String(wireObj.pub).trim()
    : 'unsigned';
  const rawSig = (wireObj.sig !== undefined && wireObj.sig !== null && String(wireObj.sig).trim() !== '')
    ? String(wireObj.sig).trim()
    : null;
  const version = wireObj.v !== undefined && wireObj.v !== null ? wireObj.v : 2;
  const normalizedTrusted = Array.isArray(trustedPublishers)
    ? trustedPublishers.map(k => String(k).trim().toLowerCase())
    : [];
  const pubLower = rawPub.toLowerCase();
  const isConfiguredTrustedKey = normalizedTrusted.includes(pubLower);

  // Case 1: Explicitly unsigned (no pub or pub === 'unsigned', and no sig)
  if (rawPub === 'unsigned' && rawSig === null) {
    return {
      validFields: true,
      verification: 'unsigned',
      pythonVerifiedStatus: 'unsigned',
      publisherTrust: 'not_established',
      contentHash,
      canonicalEnvelope: null,
      publisher: 'unsigned',
      claimedPublisherUnverified: false,
      reason: null
    };
  }

  // Legacy unverified callsign/claimed-key packet without signature (used in legacy UI tests when not claiming a configured trusted key)
  if (!strictSignedClaim && rawSig === null && wireObj.sig === undefined && !isConfiguredTrustedKey) {
    return {
      validFields: true,
      verification: 'unsigned',
      pythonVerifiedStatus: 'invalid_signature',
      publisherTrust: 'not_established',
      contentHash,
      canonicalEnvelope: null,
      publisher: rawPub,
      claimedPublisherUnverified: true,
      reason: 'Claimed publisher without cryptographic signature'
    };
  }

  // Case 2: Any packet with sig, or claiming a configured trusted publisher key, or strict signed check
  if (version !== 2) {
    return {
      validFields: true,
      verification: 'invalid_signature',
      pythonVerifiedStatus: 'invalid_signature',
      publisherTrust: 'invalid_signature',
      contentHash,
      canonicalEnvelope: null,
      publisher: rawPub,
      reason: `Unsupported signature version: ${version}`
    };
  }
  if (rawPub === 'unsigned' || !rawSig) {
    return {
      validFields: true,
      verification: 'invalid_signature',
      pythonVerifiedStatus: 'invalid_signature',
      publisherTrust: 'invalid_signature',
      contentHash,
      canonicalEnvelope: null,
      publisher: rawPub,
      reason: 'Signed bulletin requires both publisher key and signature'
    };
  }

  const envelopeStr = canonicalBulletinEnvelope(id, rev, title, contentHash, rawPub, version);
  const sigOk = ed25519VerifySync(rawPub, rawSig, envelopeStr);
  if (!sigOk) {
    return {
      validFields: true,
      verification: 'invalid_signature',
      pythonVerifiedStatus: 'invalid_signature',
      publisherTrust: 'invalid_signature',
      contentHash,
      canonicalEnvelope: envelopeStr,
      publisher: rawPub,
      reason: 'Ed25519 signature verification failed'
    };
  }

  if (isConfiguredTrustedKey) {
    return {
      validFields: true,
      verification: 'trusted_publisher',
      pythonVerifiedStatus: 'verified_ed25519',
      publisherTrust: 'trusted_publisher',
      contentHash,
      canonicalEnvelope: envelopeStr,
      publisher: rawPub,
      reason: null
    };
  }

  return {
    validFields: true,
    verification: 'valid_signature_unknown_key',
    pythonVerifiedStatus: 'verified_ed25519',
    publisherTrust: 'unknown_key',
    contentHash,
    canonicalEnvelope: envelopeStr,
    publisher: rawPub,
    reason: null
  };
}

window.sha3_256Hex = sha3_256Hex;
window.sha512Bytes = sha512Bytes;
window.ed25519VerifySync = ed25519VerifySync;
window.verifyBulletinSignatureWebCrypto = verifyBulletinSignatureWebCrypto;
window.normalizeBulletinBody = normalizeBulletinBody;
window.canonicalBulletinEnvelope = canonicalBulletinEnvelope;
window.verifyBulletinEnvelope = verifyBulletinEnvelope;

