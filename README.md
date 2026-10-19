# The Foundation Protocol

Requires Python 3.11 or later, as specified in pyproject.toml.

```sh
python -m pip install -e .
python -m tfp_core_v4.cli --help
python -m tfp_core_v4.cli visualize --port 8080
```

Open http://127.0.0.1:8080/ for the visualizer.

Checks:

```sh
python -m pip install -e ".[test]"
python -m pytest
```
