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

## Labelled evaluation

Run the real Metal backend over a labelled JSONL dataset:

```bash
PYTHONPATH=src:. python3 -m playground.evaluate_live \
  --dataset fixtures/evaluation-v1.jsonl \
  --output runs/evaluation-v1
```

The command records dataset hash, git revision, model provenance, public
responses, per-request latency, errors, metric slices, and the suitability
matrix. It does not fit a calibrator or change model weights.
