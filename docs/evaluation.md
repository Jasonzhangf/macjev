# MacJev Evaluation Protocol

## Scope

This milestone evaluates the existing DiffusionGemma decision probabilities.
It does not fit a calibrator, choose confidence thresholds, alter model
weights, or change the public Jev contract.

The evaluation answers three separate questions:

1. Is the selected answer correct?
2. Are the reported probabilities useful as probability estimates?
3. Does confidence rank errors well enough to support later risk decisions?

Calibration is a follow-up decision. A calibration split may be recorded in
the dataset, but this milestone does not fit or apply a calibration transform.

## Data Contract

The canonical input is JSON Lines. Every row contains:

```json
{
  "id": "choice-team-001",
  "split": "test",
  "type": "choice",
  "cardinality": 3,
  "state": "A production outage is affecting every customer.",
  "question": {
    "instructions": "Which team owns this?",
    "criteria": {
      "billing": "Payment or subscription issue",
      "support": "Customer account issue",
      "engineering": "Defect or outage"
    }
  },
  "label": "engineering",
  "source": "synthetic-v1"
}
```

Rules:

- `id` is unique and stable.
- `split` is `calibration`, `test`, or `ood`.
- `type` is `noul`, `choice`, or `score`.
- `cardinality` is `2` for `noul`; candidate count for `choice`; level count
  for `score`.
- `label` is the observed truth in the same value space as the public answer.
  `noul` uses `true`/`false`; `choice` uses a criterion key; `score` uses the
  zero-based level index.
- `source` identifies the data origin. Synthetic rows must say so.
- `scenario` identifies the intended use case, such as `short_text`,
  `long_text`, `structured_state`, `many_options`, or `ood`. The scenario is
  part of the evaluation slice, not a routing instruction.

The split assignment is data, not an inference-time input. The evaluator never
chooses a split from the response.

## Inference Evidence

The live runner sends each row through the same Jev-compatible
`DecisionService` and real `DiffGemmaBackend` path used by the service. It
records:

- input dataset hash and row ID
- backend, model, and quantized model directory
- public response and raw backend diagnostics
- elapsed milliseconds
- errors without fabricating a prediction

Mock results are rejected by the evaluator as model evidence.

## Metrics

Metrics are reported per split and question type. Do not collapse different
types into one headline score.

### Classification

- Accuracy: selected label equals the observed label.
- NLL: negative log probability assigned to the observed label.
- Brier: sum of squared differences between the probability vector and the
  one-hot observed label.
- ECE: absolute difference between confidence and empirical accuracy, weighted
  by bin population. The report also includes the bin contents.

### Risk

- AURC: area under the risk-coverage curve when samples are sorted from least
  to most confident. Lower is better.
- Coverage-risk points: for a requested coverage, report the empirical risk
  among the retained, highest-confidence samples.

### Ranking and Stability

- `confidence` is the reported confidence in the public answer.
- Option-order sensitivity: rerun choice/score rows with candidate order
  reversed; report selected-label changes and total-variation drift in the
  probability vectors.

## Required Slices

- split
- question type
- cardinality
- source
- scenario
- OOD versus in-distribution

The report must include sample counts and failed-inference counts for every
slice. A slice with no observations is `null`, not zero.

## Interpretation Boundary

The evaluation may conclude:

- the probabilities are or are not useful for the tested distribution;
- confidence does or does not rank errors for the tested rows;
- a question type or cardinality is unreliable;
- the result is inconclusive because the sample is too small or the data is
  synthetic.

It must not claim production calibration, choose an operational threshold, or
claim RouteCodex readiness.

## Speed and Suitability

Speed is reported separately from correctness:

- warmup count and measured count
- p50, p90, p95, p99, mean, minimum, and maximum end-to-end latency
- throughput in requests per second
- timeout, backend error, and schema error counts
- concurrency 1, 2, and 4 latency/error observations

The suitability matrix reports `scenario × type × cardinality` with sample
counts, correctness, probability metrics, and latency. A suitability label is
derived from explicit thresholds recorded with the run:

- `suitable`: enough samples, no errors, accuracy and ranking meet the declared
  thresholds, and p95 latency is within the scenario budget.
- `caution`: the sample or one metric is weak, but no correctness or latency
  failure is established.
- `unsuitable`: errors, accuracy below the declared minimum, AURC above the
  declared maximum, or p95 latency above the declared budget.
- `inconclusive`: too few measured samples to support a conclusion.

These labels evaluate the tested workload. They do not authorize automatic
production routing or threshold changes.
