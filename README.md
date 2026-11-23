# The Foundation Protocol

The Foundation Protocol includes tools for storing and fetching content by hash,
searching local collections, and transferring content over offline links. The v4
CLI also supports signed library updates.

Requires Python 3.11 or later, as specified in pyproject.toml.

```sh
python -m pip install -e .
python -m tfp_core_v4.cli --help
python -m tfp_core_v4.cli visualize --port 8080
```

Open http://127.0.0.1:8080/ for the visualizer.

[Acoustic receiver setup](docs/device_to_phone_deployment.md) ·
[Library conversion and updates](docs/library-converter.md) ·
[Creator examples](docs/creator-preview.md) ·
[Signed builder example](docs/school-creator-chain.md)

Checks:

```sh
python -m pip install -e ".[test]"
python -m pytest
```
