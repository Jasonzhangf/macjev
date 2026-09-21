# MacJev Plan

## Current Status

Status: M0-M3 and M5 implemented; M4 evaluation evidence is partial.

The objective is fixed in `GOAL.md`. The current implementation is the
production service under `src/macjev/`, exposed through `macjev.cli` and
`scripts/macjev-server`.

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

## M1: Runnable Jev-Compatible Service

Status: complete.

Deliverables:

- stdlib-only Jev-compatible HTTP server
- explicit mock backend
- real `diffgemma` HTTP client
- schema conversion
- result normalization
- example request in `fixtures/example_request.json`
- end-to-end mock test

Exit criteria:

- the production `macjev serve` path and its HTTP handler serve `/health`,
  `/v1/models`, and `/v1/systemone`
- `PYTHONPATH=src python -m unittest discover -s tests -v` passes

Evidence:

- The current declared regression command passes with 103 tests.
- `/health`, `/v1/models`, and `/v1/systemone` are exercised over HTTP.
- The mock result is explicitly marked `is_mock=true`; it is not model evidence.

## M2: Real Mac Metal Probe

Status: complete for the pinned local model path.

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
- The managed daemon downloads the pinned 19 GiB pack when it is missing.

## M3: Jev Contract Compatibility

Status: complete.

Deliverables:

- request validation matching the public Jev shapes
- stable candidate IDs
- error envelope compatibility
- SDK smoke tests
- OpenJev model aliases: `openjev-latest`, `openjev-0.1`, `jev-latest`,
  `jev-preview`
- `/v1/models` response shape with a `models` array
- `/v1/systemone` response envelope with `model`, `answers`, and `usage`
- optional `OPENJEV_API_KEY` and `OPENJEV_ORIGIN_SECRET` compatibility

Exit criteria:

- TypeSafe SDK or equivalent client can call the service without a custom
  transport

## M4: Evaluation Before Calibration

Status: partial. The recorded fixtures cover accuracy, NLL, Brier, ECE, AURC,
coverage-risk, option-order sensitivity, p50/p95 latency, prefill/denoise
timing, wall-clock throughput, and concurrency 1/2/4. P90/P99 latency and
explicit TTFT/process-startup measurements are not recorded.

Deliverables:

- labelled calibration split
- labelled test split
- OOD split
- Accuracy, NLL, Brier, ECE, AURC, and coverage-risk
- option-order sensitivity
- per-question-type and per-cardinality analysis
- complete-response p50, p90, p95, and p99 latency
- backend prefill and denoise timing reported separately
- wall-clock throughput, error rate, and concurrency 1/2/4 degradation
- explicit TTFT and process-startup observability limits

Exit criteria:

- evaluation artifacts are versioned and reproducible
- accuracy, applicable scenarios, and speed are reported separately
- no calibrator or confidence gate is selected in this milestone

## M5: Formal Implementation

Status: production runtime implemented.

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

1. Keep the production runtime and release gates green.
2. Implement the browser guard/repair server contract.
3. Implement the vision/computer-use server contract.
4. Add live browser and computer-use adapters only after their bounded
   capability probes are stable.
