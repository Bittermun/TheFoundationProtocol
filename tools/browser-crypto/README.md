# Offline browser cryptography bundle

The receiver loads `static/vendor/tfp_crypto.js` locally before
`acoustic_stream.js`. No CDN, npm installation, or network access is needed at
runtime. The generated bundle is checked in so a prepared phone can reopen it
offline.

The source is `index.js`; exact dependency versions and integrity hashes are
recorded in `package-lock.json`. From this directory, regenerate with:

```sh
npm ci
npm run build
```

`@noble/curves` 2.4.0 supplies Ed25519 verification, and
`@noble/hashes` 2.4.0 supplies SHA3-256 and SHA-512. `esbuild` 0.28.2 bundles
the browser artifact. Ed25519 uses the library's strict `zip215: false`
verification mode to reject small-order publisher keys and noncanonical
encodings. The adjacent MIT license files are copied by the build script.

Any change to the bundle, HTML, worklet, stream engine, or publisher
configuration requires a new release-specific Service Worker cache ID. Browser
vectors compare the bundle with Python's canonical v2 bulletin signatures.
