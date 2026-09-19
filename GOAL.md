# MacJev Goal

## Objective

Build a Mac-native, Jev-compatible decision server by keeping the existing
OpenJev API and decision contract, and replacing only the CUDA/vLLM inference
backend with the Apple Silicon Metal implementation of DiffusionGemma.

The model is not retrained. DiffusionGemma already provides the required
parallel structured read capability. The project adapts and verifies the
inference path.

## User-Visible Contract

The experiment must accept:

- `state`
- typed questions
- `noul`
- `choice`
- `score`

It must return:

- selected value
- complete candidate distribution
- confidence
- entropy or equivalent uncertainty diagnostics
- stable question IDs and candidate order

The first target is a runnable playground. The later target is a formal
Jev-compatible service.

## Non-Goals

- Do not retrain DiffusionGemma.
- Do not implement RLCD or any weight update.
- Do not replace the Jev API with a new decision protocol.
- Do not silently fall back to another model or mock backend.
- Do not connect this service to RouteCodex control state.
- Do not claim calibrated confidence without labelled calibration evidence.

## Hard Constraints

- The backend interface must remain swappable.
- A mock backend is allowed only for protocol tests and must be selected
  explicitly.
- The Mac backend must use the local `diffgemma` HTTP server.
- Unsupported image input must fail explicitly until the Metal vision path is
  available.
- Choice cardinality must fail explicitly above the backend limit.
- Model output, timing, and calibration evidence must identify the backend,
  model, revision, and quantization.

## Acceptance Evidence

The playground is complete when:

1. The mock backend passes end-to-end HTTP tests.
2. A real local `diffgemma` server can be probed without changing the Jev
   request shape.
3. `noul`, `choice`, and `score` requests return normalized results.
4. Invalid schemas and unsupported features return explicit errors.
5. The implementation records whether evidence came from mock or real Metal
   inference.

The formal implementation is complete only after:

- Mac Metal inference is measured on this machine.
- The Jev-compatible API passes contract tests.
- Probability quality is evaluated on a labelled calibration and test split.
- The deployment boundary with RouteCodex is documented and remains read-only
  at the decision layer.
