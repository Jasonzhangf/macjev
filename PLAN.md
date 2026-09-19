# MacJev Plan

## Current Status

Status: M1 playground implemented; M2 model download in progress.

The objective is fixed in `GOAL.md`. The project is intentionally starting as
an experiment under `playground/` before the formal service is extracted.

## M0: Goal and Architecture Lock

Status: complete when this file, `GOAL.md`, and `docs/architecture.md` exist.

Deliverables:

- training explicitly excluded
- OpenJev contract preserved
- CUDA/vLLM and Mac Metal backends separated
- unsupported features identified

Exit criteria:

- every later change can be classified as API, adapter, backend, or calibration
  work

## M1: Runnable Playground

Status: complete for mock protocol mode.

Deliverables:

- stdlib-only Jev-compatible HTTP server
- explicit mock backend
- real `diffgemma` HTTP client
- schema conversion
- result normalization
- example request
- end-to-end mock test

Exit criteria:

- `PYTHONPATH=src python -m playground.run_mock` serves `/health`,
  `/v1/models`, and
  `/v1/systemone`
- `PYTHONPATH=src python -m unittest discover -s tests -v` passes

Evidence:

- 7 unit tests pass.
- `/health`, `/v1/models`, and `/v1/systemone` were exercised over HTTP.
- The mock result is explicitly marked `is_mock=true`; it is not model evidence.

## M2: Real Mac Metal Probe

Status: in progress.

Deliverables:

- install or build `mmastrac/diffgemma`
- download the q4 pack
- start `diffgemma serve`
- probe `/health`
- send one `noul`, one `choice`, and one `score`
- record latency and diagnostics

Exit criteria:

- evidence comes from the real Metal backend
- raw response is preserved
- no mock result is accepted as live evidence

Current evidence:

- `diffgemma` 0.1.0 was built and installed from commit `6f6c825d`.
- The pinned q4 pack revision is `be312db884e99c963518a5e5a97de6080263f2a8`.
- The official downloader is resuming the 19 GiB pack.

## M3: Jev Contract Compatibility

Status: pending.

Deliverables:

- request validation matching the public Jev shapes
- stable candidate IDs
- error envelope compatibility
- SDK smoke tests

Exit criteria:

- TypeSafe SDK or equivalent client can call the playground without a custom
  transport

## M4: Calibration and Quality

Status: pending.

Deliverables:

- labelled calibration split
- labelled test split
- OOD split
- Accuracy, NLL, Brier, ECE, AURC, and coverage-risk
- option-order sensitivity
- per-question-type and per-cardinality analysis

Exit criteria:

- calibration artifacts are versioned and reproducible
- confidence gating is based on measured data, not softmax appearance

## M5: Formal Implementation

Status: production skeleton implemented.

Deliverables:

- stable package boundary
- production server entry point
- backend configuration
- deployment documentation
- explicit RouteCodex integration boundary

Current implementation:

- `macjev` package CLI and `scripts/macjev-server` entry point
- `~/.macjev/config.toml` as the single runtime configuration source
- managed `diffgemma` daemon lifecycle with PID and log ownership
- backend health and model readiness gate before API startup
- standard Jev API projected from the existing contract
- browser adapter protocol reserved without coupling browser state to Jev

Exit criteria:

- runtime, protocol, and calibration evidence are separately recorded
- no control-plane state is owned by the model service

## Immediate Tasks

1. Finish the playground server and tests.
2. Run the mock end-to-end path.
3. Build `diffgemma` on this Mac.
4. Download the q4 pack.
5. Probe the real backend and record the first evidence.
