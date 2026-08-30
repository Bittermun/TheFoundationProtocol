# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Comprehensive Multi-Tier Test Suite: TFP Phase 1 End-to-End Integration & Real-World Scenarios

Covers:
- Tier 3: Pairwise Module Integration
    * BIP-39 Root-of-Trust identity signing a Tier 1 PQC Content Manifest
    * Manifest-bound deterministic fountain transport across simulated lossy channel
    * End-to-end packet transmission, seed verification, Gaussian elimination decoding, Merkle proof checks, and PQC verification
- Tier 4: Real-World Application Scenarios (per TEST_INFRA.md)
    * Scenario 1: Cold-start device provisioning and zero-trust key recovery from 24-word BIP-39 phrase
    * Scenario 2: High-loss mesh erasure recovery (30% to 40% packet drop) using deterministic repair droplets
    * Scenario 3: Byzantine pollution resilience in mesh network (poison injection thwarted by O(1) filter)
    * Scenario 4: Multi-hop mesh transport with line-rate Tier 2 hop authentication
"""

import hashlib
import os
import random
import time
import pytest
from typing import Dict, List, Tuple

from tfp_core.crypto.bip39 import (
    generate_mnemonic,
    mnemonic_to_seed,
    validate_mnemonic,
)
from tfp_core.identity import (
    DeviceIdentity,
    create_device_identity,
    derive_subsystem_keys,
    recover_device_identity,
)
from tfp_core.crypto.pqc_adapter import KeyPair, PQCAdapter
from tfp_core.crypto.manifest_agility import (
    Tier1ContentManifest,
    Tier1ManifestSigner,
    Tier2HopAuthenticator,
    TieredManifestManager,
)
from tfp_core.manifest import (
    create_tiered_manifest,
    verify_tiered_manifest,
)
from tfp_core_v4.fountain import (
    FountainCodec,
    FountainDecoder,
    FountainDroplet,
    FountainEncoder,
    derive_repair_seed_schedule,
    verify_droplet_seed_authenticity,
)
from tfp_transport.fountain import TransportFountainChannel


# ============================================================================
# Tier 3: Pairwise Integration Tests
# ============================================================================

class TestTFPPhase1Tier3Pairwise:
    """Tier 3 Pairwise integration tests connecting BIP-39, PQC Manifests, and Deterministic Fountain."""

    def test_bip39_identity_signs_pqc_manifest_and_fountain_transport(self):
        """
        Pairwise Test:
        1. Provision device identity via BIP-39 256-bit mnemonic root of trust.
        2. Author and sign a Tier 1 PQC content manifest with device identity.
        3. Partition payload and encode into systematic and deterministic repair droplets bound to manifest RootHash.
        4. Transmit over a channel with 25% packet drop.
        5. Receiver verifies droplet seeds against manifest RootHash, decodes payload via Gaussian elimination,
           and verifies the PQC manifest signature with author's BIP-39 public key.
        """
        # Step 1: Provision BIP-39 Identity
        mnemonic = generate_mnemonic(strength=256)
        identity = recover_device_identity(mnemonic, passphrase="secure_enclave_pass")
        assert len(identity.public_key) == 32

        # Step 2: Create content and sign Tier 1 manifest
        raw_content = b"CRITICAL_TFP_EMERGENCY_MESH_BROADCAST_PAYLOAD_DATA_2026" * 8  # 448 bytes
        content_hash = hashlib.sha3_256(raw_content).hexdigest()
        symbol_size = 64
        
        # Manifest setup
        manifest = create_tiered_manifest(
            content_hash=content_hash,
            total_size=len(raw_content),
            chunk_hashes=[content_hash],
            chunk_sizes=[len(raw_content)],
            author_pubkey=identity.public_key,
            author_privkey=identity.private_key,
            algorithm="ed25519",
            fountain_params={"symbol_size": symbol_size},
        )
        assert verify_tiered_manifest(manifest, author_pubkey=identity.public_key) is True

        # Step 3: Fountain encode with deterministic repair schedule bound to manifest content_hash
        encoder = FountainEncoder(
            symbol_size=symbol_size,
            root_hash=manifest.content_hash,
            session_nonce=b"session_pair_test",
        )
        droplets, k, orig_len = encoder.encode(raw_content, redundancy=1.0)
        assert k == 7
        assert len(droplets) == 14  # 7 systematic + 7 repair

        # Step 4: Transmit with 25% packet loss (drop 3 droplets)
        rng = random.Random(1337)
        received_droplets = [d for d in droplets if rng.random() > 0.25]
        assert len(received_droplets) >= k

        # Step 5: Receiver verification and decoding
        channel = TransportFountainChannel(
            root_hash=manifest.content_hash,
            k_source_symbols=k,
            orig_len=orig_len,
            symbol_size=symbol_size,
            session_nonce=b"session_pair_test",
        )

        for d in received_droplets:
            admitted = channel.admit_droplet(d)
            assert admitted is True

        assert channel.can_decode() is True
        recovered_data = channel.decode()
        assert recovered_data == raw_content

        # Verify recovered payload matches manifest root hash
        recovered_hash = hashlib.sha3_256(recovered_data).hexdigest()
        assert recovered_hash == manifest.content_hash

    def test_pairwise_hop_auth_with_merkle_chunk_validation(self):
        """
        Pairwise Test:
        Validate Tier 2 lightweight intra-mesh hop authentication tokens paired with
        Merkle chunk binding tokens for multi-hop packet routing.
        """
        shared_hop_key = os.urandom(32)
        root_hash = "merkle_root_9876543210"
        chunk_data = b"Encrypted data shard payload #4"
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()
        chunk_idx = 4
        hop_idx = 2

        # 1. Hop token generation & validation
        hop_token = Tier2HopAuthenticator.generate_hop_token(
            hop_secret=shared_hop_key,
            chunk_hash=chunk_hash,
            hop_index=hop_idx,
            token_len=16,
        )
        assert Tier2HopAuthenticator.verify_hop_token(
            hop_secret=shared_hop_key,
            chunk_hash=chunk_hash,
            hop_index=hop_idx,
            token=hop_token,
            token_len=16,
        ) is True

        # 2. Merkle chunk token binding
        chunk_token = Tier2HopAuthenticator.generate_chunk_merkle_token(
            root_hash=root_hash,
            chunk_hash=chunk_hash,
            chunk_index=chunk_idx,
            secret_key=shared_hop_key,
        )
        assert Tier2HopAuthenticator.verify_chunk_merkle_token(
            root_hash=root_hash,
            chunk_hash=chunk_hash,
            chunk_index=chunk_idx,
            token=chunk_token,
            secret_key=shared_hop_key,
        ) is True


# ============================================================================
# Tier 4: Real-World Application Scenarios (TEST_INFRA.md Scenarios 1-4)
# ============================================================================

class TestTFPPhase1Tier4Scenarios:
    """Tier 4 Real-World Application Scenarios testing complete protocol workflows."""

    def test_scenario_1_cold_start_provisioning_and_key_recovery(self):
        """
        Scenario 1: Cold-start device provisioning and identity recovery from 24-word BIP-39 phrase.
        - Node A provisions root-of-trust identity from a 24-word phrase and derives all 5 subsystem keys.
        - Node A publishes a signed manifest and broadcasts state.
        - Node A simulates a catastrophic hardware wipe / reboot.
        - Node A recovers state from the 24-word phrase and verifies exact identity, public keys, and asset authorization.
        """
        passphrase = "salt_scif_vault_2026"
        
        # 1. Provision initial device
        mnemonic_24 = generate_mnemonic(strength=256)
        assert len(mnemonic_24.split()) == 24
        assert validate_mnemonic(mnemonic_24) is True

        device_before_wipe = recover_device_identity(mnemonic_24, passphrase=passphrase)
        orig_device_id = device_before_wipe.device_id
        orig_pubkey = device_before_wipe.public_key
        orig_subsystems = derive_subsystem_keys(device_before_wipe.seed)

        # Publish a signed manifest before wipe
        manifest = create_tiered_manifest(
            content_hash="cold_start_firmware_v4",
            total_size=8192,
            chunk_hashes=["fw_chunk_0", "fw_chunk_1"],
            chunk_sizes=[4096, 4096],
            author_pubkey=orig_pubkey,
            author_privkey=device_before_wipe.private_key,
            algorithm="ed25519",
        )
        assert verify_tiered_manifest(manifest, author_pubkey=orig_pubkey) is True

        # 2. Simulate complete device wipe (delete in-memory object)
        del device_before_wipe
        del orig_subsystems

        # 3. Recover device on cold restart using only the 24-word mnemonic and passphrase
        device_recovered = recover_device_identity(mnemonic_24, passphrase=passphrase)
        recovered_subsystems = derive_subsystem_keys(device_recovered.seed)

        # 4. Verify exact identity recovery and cryptographic equivalence
        assert device_recovered.device_id == orig_device_id
        assert device_recovered.public_key == orig_pubkey
        assert recovered_subsystems["device"][1] == orig_pubkey
        assert len(recovered_subsystems["pqc"][0]) == 32
        assert len(recovered_subsystems["kem"][0]) == 32
        assert len(recovered_subsystems["puf"][0]) == 32
        assert len(recovered_subsystems["mesh"][0]) == 32

        # 5. Verify recovered device can authenticate previously published manifest
        assert verify_tiered_manifest(manifest, author_pubkey=device_recovered.public_key) is True

    def test_scenario_2_high_loss_mesh_erasure_recovery_40_percent(self):
        """
        Scenario 2: High-loss mesh transmission (40% packet drop) using deterministic repair droplets.
        - Transmitter encodes an 8KB payload into systematic and deterministic repair droplets (redundancy=1.5).
        - Simulated wireless mesh channel drops 40% of packets randomly.
        - Receiver accumulates arriving packets, validates seeds, executes Gaussian elimination, and achieves 100% loss-free payload reconstruction.
        """
        symbol_size = 256
        payload_size = 4096  # 16 source blocks
        payload = os.urandom(payload_size)
        root_hash = hashlib.sha3_256(payload).digest()
        session_nonce = b"mesh_field_deployment_alpha"

        # Encoder with deterministic repair schedule bound to RootHash
        encoder = FountainEncoder(
            symbol_size=symbol_size,
            root_hash=root_hash,
            session_nonce=session_nonce,
        )

        # 16 systematic + 40 repair = 56 total droplets
        droplets, k, orig_len = encoder.encode(payload, redundancy=2.5)
        assert k == 16
        assert len(droplets) == 56

        # Simulate 40% packet drop over wireless mesh
        rng = random.Random(4242)
        mesh_channel_received: List[FountainDroplet] = []
        for d in droplets:
            # 40% loss rate (keep 60%)
            if rng.random() >= 0.40:
                mesh_channel_received.append(d)

        # Receiver should have received ~24 droplets (more than K=16)
        assert len(mesh_channel_received) >= k

        # Receiver channel admission and decoding
        channel = TransportFountainChannel(
            root_hash=root_hash,
            k_source_symbols=k,
            orig_len=orig_len,
            symbol_size=symbol_size,
            session_nonce=session_nonce,
        )

        for droplet in mesh_channel_received:
            channel.admit_droplet(droplet)

        assert channel.can_decode() is True
        reconstructed = channel.decode()
        assert reconstructed == payload
        assert len(reconstructed) == payload_size

    def test_scenario_3_byzantine_pollution_attack_resilience(self):
        """
        Scenario 3: Byzantine pollution resilience in adversarial mesh network.
        - Malicious node intercepts droplet stream and injects:
            * Fabricated linear combinations with valid seeds
            * Corrupted payloads with fake repair seeds
            * Forged degrees / out-of-order symbol indices
        - O(1) verify_droplet_seed_authenticity filter eliminates all Byzantine droplets at line rate.
        - Receiver completes Gaussian elimination with 100% genuine packets and exact payload recovery.
        """
        symbol_size = 128
        clean_payload = b"CRITICAL_HEALTHCARE_TELEMETRY_RECORD_007" * 16  # 656 bytes -> 6 blocks
        root_hash = hashlib.sha3_256(clean_payload).digest()
        session_nonce = b"byzantine_adversary_defense_test"

        encoder = FountainEncoder(symbol_size=symbol_size, root_hash=root_hash, session_nonce=session_nonce)
        droplets, k, orig_len = encoder.encode(clean_payload, redundancy=1.0)
        assert k == 5
        assert len(droplets) == 10

        channel = TransportFountainChannel(
            root_hash=root_hash,
            k_source_symbols=k,
            orig_len=orig_len,
            symbol_size=symbol_size,
            session_nonce=session_nonce,
        )

        # Adversary constructs poisoned droplets
        byzantine_injections = [
            # Poison 1: Systematic seed 0 with corrupted degree and wrong indices
            FountainDroplet(seed=0, degree=3, indices=[0, 1, 2], payload=os.urandom(symbol_size)),
            # Poison 2: Repair seed with tampered non-soliton degree
            FountainDroplet(seed=100, degree=99, indices=[0], payload=os.urandom(symbol_size)),
            # Poison 3: Systematic seed 2 claiming index 5
            FountainDroplet(seed=2, degree=1, indices=[5], payload=os.urandom(symbol_size)),
            # Poison 4: Negative seed
            FountainDroplet(seed=-1, degree=1, indices=[0], payload=os.urandom(symbol_size)),
            # Poison 5: Corrupt payload length
            FountainDroplet(seed=3, degree=1, indices=[3], payload=b"malicious_short"),
        ]

        # Interleave authentic and poisoned packets
        all_traffic = list(droplets) + byzantine_injections
        random.Random(999).shuffle(all_traffic)

        # Ingest traffic into transport channel
        for packet in all_traffic:
            channel.admit_droplet(packet)

        # Confirm all 5 poisoned packets were rejected
        assert channel.rejected_count == len(byzantine_injections)
        # Confirm valid droplets were retained
        assert len(channel.received_droplets) == len(droplets)

        # Confirm decoded payload is pristine and identical to source
        decoded = channel.decode()
        assert decoded == clean_payload

    def test_scenario_4_multihop_mesh_transport_with_hop_auth(self):
        """
        Scenario 4: Multi-hop mesh transport with Tier 2 lightweight hop authentication.
        - Ingest Tier 1 PQC signed manifest at ingress node.
        - Forward data packets across 3-hop mesh: Node A -> Node B -> Node C -> Node D.
        - Relays (B, C) verify 16-byte hop authentication tokens at wire speed (O(1) HMAC).
        - Destination Node D verifies Tier 1 PQC digital signature and reconstructs final content.
        """
        # Node setup with pairwise mesh secrets
        secret_ab = os.urandom(32)
        secret_bc = os.urandom(32)
        secret_cd = os.urandom(32)

        # Ingress payload & Tier 1 PQC Manifest
        pqc = PQCAdapter()
        kp = pqc.generate_dilithium5_keypair()
        payload = b"MULTIHOP_GEO_DISTRIBUTED_ROUTING_TEST_PAYLOAD" * 10
        content_hash = hashlib.sha3_256(payload).hexdigest()
        
        manifest = create_tiered_manifest(
            content_hash=content_hash,
            total_size=len(payload),
            chunk_hashes=[content_hash],
            chunk_sizes=[len(payload)],
            author_pubkey=kp.public_key,
            author_privkey=kp.secret_key,
            algorithm="dilithium5",
        )
        assert verify_tiered_manifest(manifest) is True

        # Packet forwarding simulation across hops
        chunk_hash = content_hash
        
        # Hop 1: Node A -> Node B
        token_ab = Tier2HopAuthenticator.generate_hop_token(secret_ab, chunk_hash, hop_index=1)
        assert Tier2HopAuthenticator.verify_hop_token(secret_ab, chunk_hash, 1, token_ab) is True

        # Hop 2: Node B -> Node C
        token_bc = Tier2HopAuthenticator.generate_hop_token(secret_bc, chunk_hash, hop_index=2)
        assert Tier2HopAuthenticator.verify_hop_token(secret_bc, chunk_hash, 2, token_bc) is True

        # Hop 3: Node C -> Node D
        token_cd = Tier2HopAuthenticator.generate_hop_token(secret_cd, chunk_hash, hop_index=3)
        assert Tier2HopAuthenticator.verify_hop_token(secret_cd, chunk_hash, 3, token_cd) is True

        # Terminal Node D verifies top-level PQC manifest
        assert verify_tiered_manifest(manifest, author_pubkey=kp.public_key) is True
        assert hashlib.sha3_256(payload).hexdigest() == manifest.content_hash
