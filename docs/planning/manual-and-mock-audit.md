# Manual paths and mock audit — 2026-09-15

Follow-up: the Windows `ping` encoding failure is repaired. The v4 fetch/inspect actions remain unimplemented but now exit with an explicit error instead of false success; v4 publish/verify output now states its in-memory/local scope. The original observations below are retained as before-fix evidence. See [purpose/downside review](purpose-and-regression-review.md).

The 6.1% figure is a standalone, central Zstandard dictionary comparison against independent Zstandard compression on 100 held-out project-documentation records, including a dictionary delivery. It does not benchmark the integrated Foundation Lexicon, v4 system, pooled computation, or deployed network. The compression and decoding use the real library; the application-byte framing/reuse scenarios are experimental models, not observed network traffic.

Fresh checks performed in response to the user's request:

| Path | Result | Evidence boundary |
| --- | --- | --- |
| Browser library, publication, read/debit, exact download, draft recovery, filtering, offline reading, mobile views | Eight browser check groups passed again | Normal paths use real API requests. The failure-recovery test deliberately injects an HTTP error. Local reads use stored content and bypass Lexicon reconstruction. |
| HTTP service across two real processes | Operational smoke passed again | Executed tasks, all-participant credits, persisted balances/counters/tasks, quorum continuation, and exact retrieval; local SQLite, no external network. |
| Main CLI status/tasks/leaderboard/search | All returned nonempty output and exit 0 against an owned live server | Not exhaustive testing of all CLI options or mutating commands. |
| Main CLI ping | Failed | Unicode checkmark causes UnicodeEncodeError under the default Windows cp1252 subprocess output encoding. |
| RealLexiconAdapter | Input bytes returned unchanged; semantic_search returned an empty list with an unimplemented warning | Metadata enrichment is real; semantic reconstruction/search is not implemented by this adapter. |
| LexiconAdapter | Explicitly marked mock in source | Identity reconstruction only. |
| DictionaryLexiconAdapter | Source implements abbreviation expansion | Not the measured Zstandard candidate or proof of pooled lexicon compression. |
| Separate v4 CLI fetch | Exit 0, empty stdout, no requested output file | Parser advertises fetch/inspect, but the command dispatch implements publish/verify only. It also creates a fresh in-memory node each invocation. |
| v4 full-loss retrieval | Recovered content with simulated loss 1.0 | Fetch reintroduces original locally stored droplets. This cannot establish remote loss recovery. |
| v4 bandwidth_saved_pct | 50% after two identical local publishes | No network transfer took place; this is a chunk-reuse calculation, not bandwidth measurement. |
| Standalone dictionary experiment | Independent audit again recovered all 217 records and reconciled all five byte scenarios | Genuine compression; no integrated Foundation efficiency or pooling claim. |

Local evidence: `.dist_verify/manual-audit-browser.json`, `.dist_verify/manual-cli-audit.json`, `.dist_verify/manual-protocol-audit.json`. Relevant source: `tfp_core_v4/cli.py`, `tfp_core_v4/node.py`, `tfp_client/lib/lexicon/adapter_real.py` in the nested protocol tree, and the server's local-content retrieval branch.

Conclusion: not all manual functions work, and not all protocol paths are complete. Passing unit counts cannot justify that claim. Next implementation work should remove false-success paths and misleading measurement claims, then connect actual lexicon artifacts to independently verified consumers. Do not reinterpret the 6.1% proxy result as the ceiling of the intended Lexicon system.
