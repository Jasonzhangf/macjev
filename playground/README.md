# Playground

The playground has three explicit modes.

## Mock protocol mode

This mode verifies HTTP, schema conversion, normalization, and error handling.
It is not model evidence.

```bash
PYTHONPATH=src python3 -m playground.run_mock
```

## Real backend probe

This mode talks directly to `diffgemma serve` and prints the raw latency plus
normalized result.

```bash
PYTHONPATH=src python3 -m playground.probe_diffgemma
```

## Live Jev API mode

This mode exposes the Jev-compatible HTTP API with the real Metal backend.

```bash
PYTHONPATH=src python3 -m playground.run_live
```

The live mode checks `/health` at startup and fails if the backend is not
available.
