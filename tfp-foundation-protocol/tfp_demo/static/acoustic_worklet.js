// SPDX-License-Identifier: Apache-2.0
// TFP Phase E AudioWorkletProcessor: off-main-thread live audio capture,
// bounded buffer pool reuse, sequence/sample-gap detection, and stall telemetry.

class TfpAfskCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this.blockSize = opts.blockSize || 2048;
    this.maxPoolBuffers = opts.maxPoolBuffers || 32;
    this.maxPendingTransfers = opts.maxQueueSize || 32;

    // Pre-allocated buffer pool for zero-GC steady-state capture
    this.freePool = [];
    this.allocatedBuffers = 0;
    for (let i = 0; i < 8; i++) {
      this.freePool.push(new Float32Array(this.blockSize));
      this.allocatedBuffers++;
    }

    this. stagingBuffer = this._acquireBuffer();
    this.stagingWriteIndex = 0;
    this.stagingStartFrame = 0;

    this.seq = 0;
    this.expectedFrame = null;
    this.sampleGapsDetected = 0;
    this.totalMissedSamples = 0;
    this.droppedBlocks = 0;
    this.droppedSamples = 0;
    this.inFlightBlocks = 0;
    this.maxInFlightBlocks = 0;
    this.processCallCount = 0;
    this.shutdownRequested = false;
    this.simulatedStallFrames = 0;
    this.simulatedDropCount = 0;

    this.port.onmessage = (event) => {
      const msg = event.data;
      if (!msg || typeof msg !== 'object') return;
      if (msg.type === 'return_buffer' && msg.buffer instanceof ArrayBuffer) {
        if (this.inFlightBlocks > 0) this.inFlightBlocks--;
        if (this.freePool.length < this.maxPoolBuffers && msg.buffer.byteLength === this.blockSize * 4) {
          this.freePool.push(new Float32Array(msg.buffer));
        }
      } else if (msg.type === 'simulate_worklet_stall') {
        // Deliberately skip/drop a specified number of frames to simulate a worklet stall/overrun
        const stallSamples = Number(msg.samples) || (this.blockSize * 2);
        this.simulatedStallFrames += stallSamples;
        this.sampleGapsDetected++;
        this.totalMissedSamples += stallSamples;
        this.port.postMessage({
          type: 'worklet_stall_event',
          missedSamples: stallSamples,
          sampleGapsDetected: this.sampleGapsDetected,
          totalMissedSamples: this.totalMissedSamples,
          frame: typeof currentFrame !== 'undefined' ? currentFrame : 0,
          timeSeconds: typeof currentTime !== 'undefined' ? currentTime : 0
        });
      } else if (msg.type === 'shutdown') {
        this.shutdownRequested = true;
        this.freePool.length = 0;
      }
    };
  }

  _acquireBuffer() {
    if (this.freePool.length > 0) {
      return this.freePool.pop();
    }
    if (this.allocatedBuffers < this.maxPoolBuffers) {
      this.allocatedBuffers++;
      return new Float32Array(this.blockSize);
    }
    return null;
  }

  process(inputs) {
    if (this.shutdownRequested) {
      return false;
    }
    this.processCallCount++;
    const input = inputs && inputs[0] && inputs[0][0];
    const quantumLen = input ? input.length : 128;
    const hwFrame = (typeof currentFrame !== 'undefined' ? currentFrame : this.processCallCount * quantumLen) + this.simulatedStallFrames;
    const hwTime = typeof currentTime !== 'undefined' ? currentTime : (hwFrame / sampleRate);

    if (this.expectedFrame !== null && hwFrame > this.expectedFrame) {
      const missed = hwFrame - this.expectedFrame;
      this.sampleGapsDetected++;
      this.totalMissedSamples += missed;
      this.port.postMessage({
        type: 'sample_gap',
        expectedFrame: this.expectedFrame,
        actualFrame: hwFrame,
        missedSamples: missed,
        sampleGapsDetected: this.sampleGapsDetected,
        totalMissedSamples: this.totalMissedSamples
      });
    }
    this.expectedFrame = hwFrame + quantumLen;

    if (!input || input.length === 0) {
      return true;
    }

    let readOffset = 0;
    while (readOffset < input.length) {
      if (!this.stagingBuffer) {
        this.stagingBuffer = this._acquireBuffer();
        this.stagingWriteIndex = 0;
        this.stagingStartFrame = hwFrame + readOffset;
        if (!this.stagingBuffer) {
          // Pool exhausted due to downstream overload: drop incoming samples deterministically
          const dropped = input.length - readOffset;
          this.droppedBlocks++;
          this.droppedSamples += dropped;
          this.sampleGapsDetected++;
          this.totalMissedSamples += dropped;
          this.port.postMessage({
            type: 'overload_drop',
            reason: 'buffer_pool_exhausted',
            droppedBlocks: this.droppedBlocks,
            droppedSamples: this.droppedSamples,
            inFlightBlocks: this.inFlightBlocks,
            allocatedBuffers: this.allocatedBuffers
          });
          break;
        }
      }

      if (this.stagingWriteIndex === 0) {
        this.stagingStartFrame = hwFrame + readOffset;
      }

      const spaceLeft = this.blockSize - this.stagingWriteIndex;
      const toCopy = Math.min(spaceLeft, input.length - readOffset);
      this.stagingBuffer.set(input.subarray(readOffset, readOffset + toCopy), this.stagingWriteIndex);
      this.stagingWriteIndex += toCopy;
      readOffset += toCopy;

      if (this.stagingWriteIndex === this.blockSize) {
        if (this.inFlightBlocks >= this.maxPendingTransfers) {
          // Queue bound reached: drop block and reuse stagingBuffer in-place without allocating
          this.droppedBlocks++;
          this.droppedSamples += this.blockSize;
          this.sampleGapsDetected++;
          this.totalMissedSamples += this.blockSize;
          this.stagingWriteIndex = 0;
          this.port.postMessage({
            type: 'overload_drop',
            reason: 'max_queue_exceeded',
            droppedBlocks: this.droppedBlocks,
            droppedSamples: this.droppedSamples,
            inFlightBlocks: this.inFlightBlocks,
            allocatedBuffers: this.allocatedBuffers
          });
        } else {
          const outBuf = this.stagingBuffer;
          const seqNum = this.seq++;
          const frameStart = this.stagingStartFrame;
          this.inFlightBlocks++;
          if (this.inFlightBlocks > this.maxInFlightBlocks) {
            this.maxInFlightBlocks = this.inFlightBlocks;
          }
          this.stagingBuffer = this._acquireBuffer();
          this.stagingWriteIndex = 0;
          this.port.postMessage(
            {
              type: 'audio_block',
              seq: seqNum,
              frameStart,
              sampleCount: this.blockSize,
              hwTimeSeconds: hwTime,
              inFlightBlocks: this.inFlightBlocks,
              maxInFlightBlocks: this.maxInFlightBlocks,
              allocatedBuffers: this.allocatedBuffers,
              freePoolSize: this.freePool.length,
              sampleGapsDetected: this.sampleGapsDetected,
              totalMissedSamples: this.totalMissedSamples,
              droppedBlocks: this.droppedBlocks,
              droppedSamples: this.droppedSamples,
              buffer: outBuf.buffer
            },
            [outBuf.buffer]
          );
        }
      }
    }

    return true;
  }
}

registerProcessor('tfp-afsk-capture-processor', TfpAfskCaptureProcessor);
