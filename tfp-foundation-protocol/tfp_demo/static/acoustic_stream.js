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
