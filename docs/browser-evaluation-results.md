# Browser Evaluation Results

## Run

- Dataset: `fixtures/browser-actions-v1.jsonl`
- Rows: 8 static browser states across 2 trajectories
- Repetitions: 3
- Requests: 96
- Errors: 0
- Backend: real `diffgemma-metal`
- Model: `diffgemma-26b-a4b-it-q4`
- Sampling: fixed `samples=1`
- Evidence: `evidence/browser-eval-v1/`
- Source commit: `0d50b21b02a301f6ee7adae782bc12faceea81d6`
- Dataset SHA-256: `807329c83a3bbe45fd7099633370d8760c2de286854a431e5f40012c65fb27f6`
- Report SHA-256: `30ed6f0dff8aa9fc98fdf31d35532b1ab7cadf81e9276cdd9f00bf7dc13a5aa9`
- Records SHA-256: `ca171dceed67a25b6fb8bf21daa74862878891f0f497ef6ac5e788d2790bfabd`

The run is an action-selection evaluation. No browser was driven and no
account, network page, login state, screenshot, selector generation, or page
mutation was involved.

## Correctness and Applicability

| Mode | Accuracy | Top-2 | Valid target | Errors |
| --- | ---: | ---: | ---: | ---: |
| Fresh schema | 0.750 | 1.000 | 0.875 | 0 |
| Stable schema | 0.708 | 1.000 | 0.917 | 0 |
| Continuous history | 0.792 | 1.000 | 1.000 | 0 |
| Schema churn + history | 0.750 | 0.875 | 1.000 | 0 |

| Scenario | Accuracy | Top-2 | Valid target |
| --- | ---: | ---: | ---: |
| Search | 0.896 | 1.000 | 0.896 |
| Form | 0.604 | 0.938 | 1.000 |

The tested workload supports a narrow conclusion:

- The model is promising for choosing among a small, explicitly indexed
  action set in navigation/search flows.
- It is not reliable enough to execute form actions without an external
  validator or confirmation step.
- Most form errors are semantic action-choice errors, not invalid targets.
  The repeated confusions are `CLICK:<field>` versus
  `TYPE_TEXT:<field>`, and `CLICK:close` versus `DONE` after completion.
- Search has one repeated invalid-target error: after already reaching the
  README, the model still selects `CLICK:result-macjev` instead of `DONE`.

The eight-row fixture is too small for a production claim. It establishes
direction and concrete failure modes only.

## Phase-Specific Speed

Follow-up rows exclude each trajectory's cold first request. Deltas are
candidate minus baseline; negative is faster.

| Comparison | Complete | Prefill | Non-prefill | Denoise |
| --- | ---: | ---: | ---: | ---: |
| Stable schema vs fresh schema | -312.9 ms | -314.4 ms | +1.5 ms | +1.5 ms |
| Continuous history vs stable schema | +271.6 ms | +259.2 ms | +12.4 ms | +12.2 ms |
| Continuous history vs schema churn | -212.4 ms | -210.8 ms | -1.6 ms | -1.6 ms |

Interpretation:

- Reusing an unchanged schema produces a real prefill advantage. On follow-up
  rows, stable schema was faster on complete latency in 18/18 comparisons.
- Appending trajectory history is not automatically faster. The model reuses
  the stable schema prefix, but must prefill the new history delta. On this
  fixture that cost exceeded the schema-reuse saving, so continuous history
  was slower than stable schema on all 18 follow-up comparisons.
- Continuous history is still faster than changing the question schema every
  step because schema churn gives back the reusable prefix.
- The material speed effect is in prefill, not denoise. Denoise deltas remain
  within about 1.6 ms on average and are not the source of the cache gain.
- `non_prefill_ms` is complete request minus prefill and includes denoise.
  It is reported separately from `denoise_ms`.

These are in-process `DecisionService` measurements against an already
started, model-resident Metal server. They exclude process startup and model
loading, and they do not measure public HTTP overhead.

The tracked evidence contains the exact dataset hash, source commit, working
tree status, backend health/model response, command arguments, raw records,
and the derived report. The source commit in `provenance.json` is the commit
from which the final run was executed.

## Decision

MacJev is usable as an experimental browser action evaluator, with a narrow
scope:

1. Use text/DOM snapshots and a small indexed action schema.
2. Keep execution outside the model.
3. Validate the selected action against the current page before execution.
4. Prefer stable schemas across steps.
5. Include only decision-relevant history; unbounded trajectory append can
   cost more prefill than it saves.
6. Do not treat high confidence as permission to execute. The observed wrong
   form choices were often high-confidence.

This is not yet evidence for live-site reliability, long trajectories, or
production browser automation.
