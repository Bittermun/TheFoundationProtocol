# SPDX-License-Identifier: Apache-2.0
"""Small, original notes for an empty demo library. No external content."""

SAMPLE_NOTES = (
    (
        "Start a community knowledge shelf",
        ["community", "welcome"],
        "A knowledge shelf begins with a few things people actually use.\n\n"
        "Try a repair note, a local event checklist, or a guide to a shared tool. "
        "Give each note a clear title and a small set of tags. Ask someone else "
        "to find it before adding more.\n\n"
        "This is sample content stored on your Foundation node. You can publish "
        "your own note, copy its fingerprint, and retrieve it from the same node. "
        "Connecting separate nodes is a further experiment.",
    ),
    (
        "A fingerprint for your words",
        ["learning", "protocol"],
        "Foundation addresses a note by the SHA3-256 hash of its bytes.\n\n"
        "Publish the same text twice and it has the same address. Change one "
        "character and the address changes. Titles and tags are separate metadata; "
        "publishing identical text with new metadata updates that entry.\n\n"
        "Try it: publish a short note, copy the fingerprint, then change a word "
        "and publish again. Compare the two addresses.\n\n"
        "A fingerprint identifies bytes. It does not tell you whether the words "
        "are true, who wrote them, or whether another node stores a copy.",
    ),
    (
        "What this node can show you",
        ["protocol", "demo"],
        "This demo joins three operations: publish a note, discover it by tag, "
        "and retrieve it by its content fingerprint.\n\n"
        "The round-trip button compares retrieved text with what your browser "
        "submitted. The node screen reports live content counts and device credits. "
        "Demo credit grants are test allowances, not proof of useful computation.\n\n"
        "The larger repository explores peer exchange, chunking, and loss-tolerant "
        "delivery. A successful local round trip is a useful starting point; it is "
        "not evidence of production security or network-scale efficiency.",
    ),
)
