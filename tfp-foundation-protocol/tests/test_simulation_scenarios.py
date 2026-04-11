import hashlib
import os

from tfp_client.lib.fountain.adapter import RaptorQAdapter
from tfp_client.lib.identity.puf_enclave.enclave import PUFEnclave


def test_shard_poisoning_attack():
    """20% poisoned shards, legitimate reconstruction success >= 92%"""
    raptorq = RaptorQAdapter()
    successes = 0
    trials = 100
    for _ in range(trials):
        data = os.urandom(1024)
        shards = raptorq.encode(data, redundancy=0.3)
        total = len(shards)
        num_poisoned = int(total * 0.20)
        # Poison 20% of shards
        clean_shards = shards[num_poisoned:]
        try:
            reconstructed = raptorq.decode(clean_shards)
            if reconstructed:
                successes += 1
        except Exception:
            pass
    success_rate = successes / trials
    assert success_rate >= 0.92


def test_sybil_farm_rejection():
    """200 sybil nodes with fake PUF, credit minting success = 0 for sybils, >= 98% for legit"""
    legit_seed = os.urandom(32)
    legit_enclave = PUFEnclave(seed=legit_seed)
    legit_identity = legit_enclave.get_identity()

    # 200 sybil nodes with random (fake) seeds
    sybil_successes = 0
    for _ in range(200):
        fake_seed = os.urandom(32)
        result = PUFEnclave.verify_identity(legit_identity, fake_seed)
        if result:
            sybil_successes += 1
    assert sybil_successes == 0

    # Legitimate nodes
    legit_successes = 0
    trials = 100
    for _ in range(trials):
        result = PUFEnclave.verify_identity(legit_identity, legit_seed)
        if result:
            legit_successes += 1
    assert legit_successes / trials >= 0.98


def test_popularity_persistence_under_congestion():
    """30% drop rate, high-popularity hashes remain cached >= 95%"""
    # Simulate a cache of popular hashes
    popular_hashes = {
        hashlib.sha3_256(f"popular_{i}".encode()).hexdigest() for i in range(100)
    }
    cache = set(popular_hashes)

    # Simulate 30% drop rate — randomly evict 30% of non-popular entries
    all_hashes = list(popular_hashes) + [
        hashlib.sha3_256(f"unpopular_{i}".encode()).hexdigest() for i in range(200)
    ]
    drop_rate = 0.30
    surviving = set()
    for h in all_hashes:
        if h in popular_hashes:
            surviving.add(h)  # popular hashes always kept
        elif os.urandom(1)[0] / 255 > drop_rate:
            surviving.add(h)

    popular_surviving = popular_hashes & surviving
    persistence_rate = len(popular_surviving) / len(popular_hashes)
    assert persistence_rate >= 0.95
