# Recurring offline editions from a field guide

A publisher edits one Markdown guide. A scheduled job can check the same file, build and search a new ZIM, and publish a signed update. A library refresh applies any consecutive editions it missed to its dedicated Kiwix catalog.

## Run the local rehearsal

From the Foundation Protocol root, use Python 3.11 with `pip install ".[library]" libzim==3.13.0`. Make `kiwix-serve`, `kiwix-manage`, and `zimcheck` available on `PATH` or set `KIWIX_SERVE`, `KIWIX_MANAGE`, and `ZIMCHECK` to their executable paths. The rehearsal uses Kiwix tools 3.8.1 and zim-tools 3.8.0.

```text
python -m examples.recurring_library_editions.rehearse --out scratch/recurring-library-editions
```

Choose a fresh output directory. The rehearsal creates test keys and a loopback Kiwix server. It runs the publisher and refresh commands after copying each version to the same source path. Its `proof.json` records the two releases, recipient revisions, actual search results, repeat, and failed build. The handoff includes the bootstrap archive, the two signed edition directories and the disposable publisher's public key.

## Publisher and recipient commands

At setup, the publisher and station provision the exact same bootstrap ZIM. The station pins the publisher's public key through a trusted channel, adds the bootstrap with `kiwix-manage`, and runs `kiwix-serve --library --monitorLibrary` on a dedicated catalog. Start from the existing [IIAB configuration example](../../deploy/iiab/config.example.json), using the library ID in [recipe.json](recipe.json) and `index.html` as the reader probe.

```text
python -m examples.recurring_library_editions.editions publish --recipe examples/recurring_library_editions/recipe.json --source field-guide.md --channel channel --bootstrap bootstrap.zim --signing-key publisher.key
python -m examples.recurring_library_editions.editions refresh --channel channel --config station-config.json
```

The author publishes from one UTF-8 Markdown file with titled `##` sections. The final JSON line reports the source revision, source and archive SHA3-256 digests, title and release revision. Pass `--source-revision` to record the originating commit or editorial revision. By default the source digest identifies the revision. Each update is signed against the last published archive. An identical source produces an `unchanged` result. A candidate enters the channel after the converter, index check and signing succeed.

The receiving host syncs complete `edition-N` directories to its local channel in order. The refresh command applies unseen signed packages through Foundation's usual Kiwix activation. The catalog keeps the accepted edition available when a publisher build fails. If a signed package fails the reader probe, existing activation recovery restores the previous catalog.

## Trial on an existing library host

Use one Internet-in-a-Box host with a dedicated monitored Kiwix catalog for this publication. IIAB already uses the Kiwix tools and a local ZIM catalog. Configure a separate catalog and reader for this title so the station operator can choose its refresh schedule and apply the one-edition policy to this collection. [IIAB Kiwix role](https://github.com/iiab/iiab/tree/master/roles/kiwix) · [Foundation IIAB activation service](../../deploy/iiab/tfp-library-update.service)

The publisher approves the source and its reuse permission, records the source revision, and keeps the signing key in their approved credential store. Their existing scheduler invokes `publish` after an approved source update. The host's sync job stages each transferred edition before making its directory visible, then invokes `refresh` against the same local channel and catalog each time.

| Next source edit | Publisher | Library |
| --- | --- | --- |
| Edition 3 | Build and verify the new search index, then sign against edition 2. | Apply edition 3 and confirm its search result. |
| Edition 4 | Repeat against edition 3. | Apply edition 4. A station still on edition 2 applies 3 and 4 in order. |

[Draft request for a publisher](publisher-request.md)
