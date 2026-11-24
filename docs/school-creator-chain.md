
# Publish and reuse an offline school-library builder

A librarian writes a builder. A teacher runs it on their own lessons and separately signs three output packs. A recipient verifies those packs against the teacher's locally chosen public key and activates a searchable library. The recipient needs the installed TFP wheel and the three files. The builder and original lessons stay with their creators.

Use `examples/school-library/recipe.json` as a starting point. The builder declares input limits, a dictionary size in KiB, and an article compression level. Use UTF-8 `.txt` documents with a short title on the first line and filenames such as `orchard-lesson.txt`. Use a substantial set of related lessons for dictionary training. The demonstration uses 16 lessons. If training reports too little text, supply more text or reduce the dictionary size in the recipe.

The commands below are single lines and use raw 32-byte Ed25519 keys. Use a separate keypair per publisher. Exchange public keys and the builder digest through a channel you trust. Keep private keys off the handoff media. Output paths must be new. Choose an explicit supported license for material you can publish.

## Librarian

```text
tfp kit publish-builder examples/school-library/recipe.json --id librarian/school-builder --version 1.0.0 --revision 1 --license CC0-1.0 --key librarian.key --out school.tfpack
```

Send the signed builder and provision `librarian.pub` and the reported `digest` independently with the teacher.

## Teacher

```text
tfp kit run school.tfpack --builder-id librarian/school-builder --builder-key librarian.pub --builder-digest sha3-256:REPLACE_WITH_REPORTED_HASH --publisher-key teacher.pub --id teacher/field-library --title "School field library" --version 1.0.0 --revision 1 --license CC0-1.0 --input-dir lessons --out drafts
tfp kit sign drafts --key teacher.key --out signed
```

The first command needs only the teacher's public key. Review the drafts before signing. Signing binds the exact unsigned manifests to the corresponding publisher key. Send the signed `kit.tfpack`, `content.tfpack`, and `lexicon.tfpack` together. The kit binds both child packs by digest. The content also binds the dictionary, including the dictionary ID in every article frame.

To verify a build in the same environment, rerun with the same options into a new draft directory and compare all three files. Compare the recorded input and dictionary digests when a toolchain changes. A byte difference still requires investigation and may require a new release. Publish updates with a higher revision and a new version.

## Recipient

```text
tfp kit install signed --publisher-key teacher.pub --id teacher/field-library --db library.db
tfp kit search "orchard seed exchange" --id teacher/field-library --db library.db
tfp kit read lesson-00.txt --id teacher/field-library --db library.db
```

Installation only uses supplied local files. It verifies all three signatures and exact dependencies before decoding the articles. Activation writes the verified plain text and accepted publication together in one local database transaction. Keep the database to retain revision history and keep the signed handoff for independent re-verification. Choose a database path in a local directory you control.

## Scope of the school-library profile

The school profiles use a bounded stored ZIP with the shared envelope field layout. The writer uses SHA3-256 and Ed25519. The school reader also recognizes SHA-256 envelopes for these profiles. This is a profile-specific path with a small license allowlist and an explicit key-and-ID pin. Existing library-update and article formats have their own verification and readers.

Run the separate-environment proof with Python 3.11. Provision the wheelhouse once, then the verification installs from it with package indexes disabled. All three role processes reject Python socket operations.

```text
python -m pip wheel --wheel-dir wheelhouse .
python scripts/verify_creator_chain.py --wheelhouse wheelhouse
```
