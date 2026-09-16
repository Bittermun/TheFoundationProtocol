# Showing Foundation

The best introduction is a working loop: publish something, find it, and retrieve the same bytes. You do not need to explain every module in the repository.

## Start the demo

From the repository root, with Python 3.11 or 3.12:

```sh
python -m pip install ".[cli]"
python -m tfp_cli.main demo
```

The browser opens automatically. The server stores notes in `~/.tfp/demo` and runs until you press Ctrl+C. External bridges are disabled, so the walkthrough needs no external services.

For a clean presentation each time, use `python -m tfp_cli.main demo --ephemeral`. This clears server data when it stops; your browser identity and drafts remain in browser storage. An occupied port is reported clearly; choose `--port 8001` if needed.

## A three-minute walkthrough

| Step | Do this | What it demonstrates |
| --- | --- | --- |
| 1 | Open the content library | Original sample notes are actually stored on the node |
| 2 | Click **Try a round trip** | The browser grants demo credits if needed, publishes a sample through the API, retrieves it, and compares the text |
| 3 | Open **Publish a note** and write a short community note | The content is your own; your draft survives a page reload |
| 4 | Add the tag `community`, publish, then read your note | Publishing, tag discovery, and reading are connected |
| 5 | Copy its fingerprint, close the reader, and use the fingerprint field in the library | The bytes have an address independent of the title |
| 6 | Open **Your node** | Content counts and balances are real server values; each successful read spends one credit |
| 7 | Open **How it works** | The implementation and research ambitions are clearly distinguished |

A useful introduction: “Foundation is a prototype for a shared information commons. This demo shows content-addressed publishing and retrieval on one node. The larger question is how to make that work efficiently across unreliable community networks.”

Do not describe the demo credit grant as mining or useful computation. Do not describe a local round trip as a test of global bandwidth, censorship resistance, or production security.

## What to expect

- Publishing costs no credits. Each successful retrieval request costs one credit, including a successful range or streaming request. Saving the already opened text does not make another retrieval request.
- Re-publishing identical text uses the same fingerprint and updates that entry's title/tags. Changing the text creates a different fingerprint.
- Notes render as plain text. HTML in a title, tag, or body is displayed as text, not executed.
- A refresh reuses your browser identity and preserves credits. Switching browser profiles or ports creates a separate local identity.
- If a request fails, its error is shown and the draft is retained. If publishing times out, check the library before retrying: the server may still have stored the note.
- Live listings and credit balances are never served from the offline cache. A previously opened note may be read offline with the same fingerprint and browser identity; the reader labels it as a saved copy. The library itself requires a connection.

## Verify before a presentation

```sh
python demo_30sec.py
```

This starts its own temporary server on an available port, verifies the actual installed interface and an exact UTF-8 publish/discover/retrieve flow, checks the credit debit and enrollment retry, then stops that server. A failure returns a nonzero exit code. It does not leave a server running at an advertised URL.

For automated browser checks:

```sh
python -m pip install ".[browser]"
python -m playwright install chromium
python scripts/check_demo_browser.py
```

The browser check uses a separate ephemeral server. It saves screenshots under `output/playwright/`, an ignored local output directory. It checks desktop and mobile layouts, normal publishing, HTML-as-text handling, saved drafts, search, offline cached reading, and recovery after a failed request.

## Troubleshooting

**The port is already in use.** Run `python -m tfp_cli.main demo --port 8001`. The launcher refuses to attach to an unrelated process.

**The page says the node is unavailable.** Keep the server terminal open. Start the server again and reload, or use Reconnect on desktop. Drafts remain in the browser.

**No credits.** Use **Add 10 demo credits** on Your node, or the allowance button in the reader. The rate limit may require a short wait after repeated grants.

**The device ID is already enrolled with another secret.** Use the browser profile that owns the identity. The server now refuses to replace another device's secret; that protects its saved balance.

**PowerShell won't activate the virtual environment.** Activation is optional. Use `.\.venv\Scripts\python -m tfp_cli.main demo` directly after installing through that Python, as shown in the README.

**Docker does not start.** Start Docker Desktop/Engine first. The Python launcher is the shorter route for a local presentation.
