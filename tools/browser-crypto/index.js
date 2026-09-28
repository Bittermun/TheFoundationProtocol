// SPDX-License-Identifier: Apache-2.0
import { ed25519 } from '@noble/curves/ed25519.js';
import { sha3_256 } from '@noble/hashes/sha3.js';
import { sha512 } from '@noble/hashes/sha2.js';

// Explicit strict RFC 8032 mode: ZIP215's permissive consensus semantics are
// unsuitable for authenticating bulletin publishers (including small-order keys).
export function verify(signature, message, publicKey) {
  return ed25519.verify(signature, message, publicKey, { zip215: false });
}
export { sha3_256, sha512 };
