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
        this.hypotheses.push({step, initialOffset: offset, next: offset, shift: 0, bits: 0, nextByte: 0,
                              state: 0, flags: 0, payload: null, length: 0, index: 0});
      }
    }
  }

  resetAfterGap() {
    // Missing PCM invalidates symbol timing and any partially assembled frame.
    // Preserve duplicate suppression and cumulative buffer diagnostics.
    this.base = 0;
    this.buffer = new Float32Array(0);
    for (const h of this.hypotheses) {
      h.next = h.initialOffset;
      h.shift = 0;
      h.bits = 0;
      h.nextByte = 0;
      h.state = 0;
      h.flags = 0;
      h.payload = null;
      h.length = 0;
      h.index = 0;
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
// Canonical v2 wire format matches Python tfp_core_v4/bulletin_identity.py.
// ============================================================================

// Maintained, locally bundled primitives. See tools/browser-crypto/README.md.
// This is the synchronous verifier used by actual bulletin admission, including
// browsers without native Ed25519. Wire canonicalization and trust stay below.
function cryptoMessageBytes(input) {
  return typeof input === 'string' ? new TextEncoder().encode(input) : new Uint8Array(input);
}

function sha3_256Hex(input) {
  return Array.from(window.TFPCrypto.sha3_256(cryptoMessageBytes(input)),
    b => b.toString(16).padStart(2, '0')).join('');
}

function sha512Bytes(input) {
  return window.TFPCrypto.sha512(cryptoMessageBytes(input));
}

function hexToBytes(hex) {
  if (typeof hex !== 'string' || hex.length % 2 !== 0 || !/^[0-9a-fA-F]+$/.test(hex)) {
    return null;
  }
  return Uint8Array.from(hex.match(/../g), b => parseInt(b, 16));
}

function ed25519VerifySync(pubKeyHex, sigHex, messageBytes) {
  const pubBytes = hexToBytes(pubKeyHex);
  const sigBytes = hexToBytes(sigHex);
  if (!pubBytes || pubBytes.length !== 32 || !sigBytes || sigBytes.length !== 64) return false;
  try {
    return window.TFPCrypto.verify(sigBytes, cryptoMessageBytes(messageBytes), pubBytes);
  } catch (_) {
    return false;
  }
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
  return { supported: false, valid: syncValid, engine: 'Noble-Ed25519-Strict' };
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

