# Evaluation Run Summary

## Serial Real-Metal Baseline

- Dataset: `fixtures/evaluation-v1.jsonl`
- Samples: 15 synthetic labelled rows
- Backend: `diffgemma-metal`
- Model: `diffgemma-26b-a4b-it-q4`
- Errors: 0
- Accuracy: 0.867
- NLL: 0.457
- Brier: 0.243
- ECE: 0.119
- AURC: 0.220
- p50 latency: 2211 ms
- p95 latency: 2493 ms
- Throughput: 0.508 req/s

## Concurrency

| Concurrency | Errors | p50 ms | p95 ms | Throughput req/s |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0 | 2211 | 2493 | 0.508 |
| 2 | 0 | 10754 | 13157 | 0.127 |
| 4 | 0 | 12189 | 13144 | 0.092 |

The backend serializes or heavily contends under concurrent requests. Higher
concurrency did not improve throughput and increased latency by roughly five
times.

## Quality Slices

| Slice | Samples | Accuracy | ECE | AURC | Suitability |
| --- | ---: | ---: | ---: | ---: | --- |
| Calibration | 6 | 1.000 | 0.061 | 0.000 | suitable |
| Test | 6 | 0.833 | 0.115 | 0.242 | caution |
| OOD | 3 | 0.667 | 0.313 | 0.611 | unsuitable |
| Short text | 5 | 1.000 | 0.004 | 0.000 | suitable |
| Structured state | 2 | 0.500 | 0.399 | 0.750 | unsuitable |
| Long text | 3 | 1.000 | 0.121 | 0.000 | suitable |
| Many options | 2 | 1.000 | 0.175 | 0.000 | suitable |

The slice sample sizes are too small for a production claim. The results do
show a concrete risk signal: structured-state and OOD rows had wrong,
high-confidence predictions, while short-text rows were stable.

The `suitable`/`caution`/`unsuitable` labels use
`evaluation-policy-v1`: minimum sample count, accuracy, AURC, and p95 latency
thresholds recorded in `report.json`. They describe this evaluation run only.
They are not production routing or calibration thresholds.

## Interpretation

This run evaluates the model as-is. It does not fit a calibration transform,
select a production threshold, change weights, or authorize RouteCodex
integration.
