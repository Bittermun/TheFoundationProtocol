# Shared dictionary experiment: first decision

2026-09-15. **Do not expand pooled dictionary construction for this workload yet.** The frozen exploratory test missed its minimum useful-benefit threshold. This is a decision about one candidate and proxy workload, not a rejection of the broader lexicon mission.

Training used 361 project-documentation records; selection used 45 different records. The selected 1,024-byte Zstandard dictionary was then evaluated on 217 held-out records from other source files. Candidate sizes and the 10% cold-client threshold at 100 distinct records were fixed in `lexicon-experiment-contract.json` before evaluation. Exact duplicate records were removed; near-duplicate documentation remains a limitation.

| Distinct records consumed | Ordinary independent compression | Shared dictionary, including delivery | Change |
| --- | ---: | ---: | ---: |
| 1 | 124 bytes | 1,187 bytes | 857% larger |
| 5 | 1,605 bytes | 2,561 bytes | 60% larger |
| 20 | 7,122 bytes | 7,587 bytes | 6.5% larger |
| 100 | 31,542 bytes | 29,631 bytes | 6.1% smaller |
| 217 | 67,699 bytes | 62,102 bytes | 8.3% smaller |

These are encoded application bytes under the declared framing, not measured network traffic. A cached dictionary reduces the 100-record payload to 28,566 bytes, but its prior delivery cannot disappear from lifetime costs. One extra dictionary delivery reduces the cold saving further. Repeated requests for exactly cached content require no new content bytes in either design; that is a cache-policy assumption, not measured network behavior.

When all 100 records can be batched, ordinary compression uses only 17,713 bytes. Batching changes access granularity and is not always suitable, but the dictionary candidate cannot claim a win against that baseline.

Training took about 6.8 milliseconds on the development host, with a process peak working set of about 32 MiB. The Windows process CPU timer reported zero at this short duration; that does not mean training costs no CPU. Warm-context decode/verification p95 was 4.8 microseconds for ordinary frames and 4.4 for shared frames in this run. These single-host microtimings do not support general performance claims. Training input totals 170,341 bytes: if those inputs must be transferred for this one client, total shared bytes become 199,972 at 100 records. Pool dispatch and redundant verification have not been measured.

All records recovered exactly. Random data gained nothing, as expected. Already-compressed data became about 1.5% larger once dictionary delivery was counted. Wrong artifact identity was rejected before decoding, and dictionary-free fallback recovered the content. An independent audit re-encoded and decoded all 217 records and reconciled all five scenario totals. Artifact eviction/update costs here are sensitivity calculations, not a live cache/update system.

## Consequence for the next work

The evidence supports a small sharing benefit at sufficient reuse, but not the frozen practical threshold and not any pooling benefit. Do not lower the threshold after observing the result or retune on this test set. The cheap local construction also makes remote coordination overhead a serious concern.

Next, complete honest transport accounting (W01) and obtain a representative workload/reuse pattern before promoting a lexicon candidate. If a different representation or workload is justified, give it a new frozen evaluation. Retain this negative result. Actual modest-device performance, useful pooled construction, demand-scaled video, and independent-network integration remain unverified.

## Reproduction and evidence

Install the optional experiment dependencies with `python -m pip install ".[experiments]"`. Regenerate the frozen corpus using `scripts/prepare_lexicon_corpus.py` with commit `42b31829dc8623a38a5c30ffffd4e37173ed671f`. Run `scripts/benchmark_shared_dictionary.py --corpus <corpus.json> --contract docs/planning/lexicon-experiment-contract.json --output-dir <new-directory>`, then `scripts/audit_dictionary_experiment.py <corpus.json> <new-directory>`.

Saved evidence: [contract](lexicon-experiment-contract.json), [selection](lexicon-e1-v1-selection.json), [results](lexicon-e1-v1-results.json), [independent audit](lexicon-e1-v1-audit.json). The corpus, contract, selected dictionary, and runner identities are hashed. The governance skill's model-tournament/settlement commands do not match this repository experiment; the frozen contract, raw comparison, and independent byte reconciliation are the applicable checks. Claim level remains L1 exploratory local comparison, not deployed quality improvement.

Implementation reference: [python-zstandard dictionary training documentation](https://python-zstandard.readthedocs.io/en/latest/dictionaries.html).
