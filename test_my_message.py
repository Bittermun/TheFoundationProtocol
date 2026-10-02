import hashlib
from pathlib import Path
import random
import sys

# Repo root
repo_root = Path(__file__).resolve().parent
sys.path.insert(0, str(repo_root))

from tfp_core_v4.fountain import FountainCodec, FountainDroplet, _sample_soliton_degree

def test_custom_message(user_text: str | None = None):
    print("=" * 65)
    print("      THE FOUNDATION PROTOCOL: ZERO-JARGON HUMAN TEST")
    print("=" * 65)

    if not user_text:
        if len(sys.argv) > 1:
            user_text = " ".join(sys.argv[1:])
        else:
            try:
                user_text = input("\nType any secret sentence or phrase to test: ").strip()
            except (EOFError, KeyboardInterrupt):
                user_text = ""
        if not user_text:
            user_text = "Barrel of black beans."

    original_bytes = user_text.encode("utf-8")
    
    print("\n[STEP 1] YOUR SECRET PHRASE:")
    print(f"  \"{user_text}\"")
    print(f"  (Total length: {len(original_bytes)} characters)")

    # Symbol size: 16 bytes
    symbol_size = 16
    codec = FountainCodec(symbol_size=symbol_size)
    k = max(2, (len(original_bytes) + symbol_size - 1) // symbol_size)
    orig_len = len(original_bytes)

    # Pad data to K * symbol_size
    padded = original_bytes + b"\x00" * (k * symbol_size - len(original_bytes))
    source_symbols = [padded[i * symbol_size : (i + 1) * symbol_size] for i in range(k)]

    print("\n[STEP 2] CHOPPING INTO PUZZLE PIECES & SIMULATING RADIO STATIC:")
    print(f"  The computer cuts your phrase into {k} digital puzzle pieces:")
    for idx, s in enumerate(source_symbols, start=1):
        clean_preview = s.decode("utf-8", errors="replace").replace("\x00", " ")
        print(f"    Piece #{idx:02d} carries : \"{clean_preview}\"")

    print("\n  Now broadcasting into the air through heavy radio interference...")

    arrived_droplets = []
    packets_sent = 0
    packets_lost = 0
    seed = 0

    # Ensure at least piece #1 is destroyed so the human sees the magic of loss recovery
    must_drop_first = True

    while True:
        packets_sent += 1
        is_repair = seed >= k
        if not is_repair:
            droplet = FountainDroplet(seed=seed, degree=1, indices=[seed], payload=source_symbols[seed])
            label = f"Original Piece #{seed+1:02d}"
        else:
            rng = random.Random(seed)
            degree = _sample_soliton_degree(k, rng)
            indices = sorted(rng.sample(range(k), degree))
            acc = 0
            for idx in indices:
                acc ^= int.from_bytes(source_symbols[idx], "big")
            combined = acc.to_bytes(symbol_size, "big")
            droplet = FountainDroplet(seed=seed, degree=degree, indices=indices, payload=combined)
            combined_labels = "+".join([f"#{i+1}" for i in indices])
            label = f"Smart Repair Piece (combines {combined_labels})"

        seed += 1

        # Drop piece 1 deliberately to demonstrate loss, then 35% random drop
        if seed == 1 and must_drop_first:
            is_lost = True
        elif is_repair and len(arrived_droplets) < k:
            is_lost = False
        else:
            is_lost = random.random() < 0.35

        if is_lost:
            packets_lost += 1
            print(f"    Piece #{packets_sent:02d} [{label}] : [X] DESTROYED IN STATIC (Lost forever!)")
            continue

        arrived_droplets.append(droplet)
        print(f"    Piece #{packets_sent:02d} [{label}] : [OK] Received safely by radio")

        if len(arrived_droplets) >= k:
            try:
                recovered = codec.decode(arrived_droplets, k, orig_len)
                break
            except ValueError:
                continue

    print("\n  Notice: The original Piece #01 was completely lost and NEVER re-sent.")
    print(f"  The radio receiver only collected {len(arrived_droplets)} pieces, including the Smart Repair Piece.")

    recovered_text = recovered.decode("utf-8", errors="replace")

    print("\n[STEP 3] SOLVING THE PUZZLE & RECONSTRUCTION:")
    print("  The receiver uses the Smart Repair Piece to mathematically rebuild the missing piece...")
    print("\n  RECONSTRUCTED MESSAGE:")
    print(f"  \"{recovered_text}\"")
    print("=" * 65)

    if recovered_text == user_text:
        print("  VERDICT: 100% BIT-FOR-BIT PERFECT MATCH!")
        print("  Not a single letter or character was lost, even though Piece #01")
        print("  was destroyed in the air and never transmitted again.")
        print("=" * 65)
    else:
        print("  VERDICT: MISMATCH")
        print("=" * 65)

if __name__ == "__main__":
    test_custom_message()
