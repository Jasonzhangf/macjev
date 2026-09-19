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
- p50 complete-response latency: 2195 ms
- p95 complete-response latency: 2497 ms
- Throughput: 0.509 req/s

The latency scope is the public Jev HTTP route, from request dispatch through
complete JSON response parsing. Throughput is measured from wall-clock runtime,
not from the sum of per-request latencies.

## Prefill and Denoise

The phase benchmark calls `DecisionService` directly against the same
`diffgemma` backend. It is a separate evidence scope because the public Jev
response intentionally does not expose internal timing diagnostics.

| Phase | Samples | p50 ms | Share of request |
| --- | ---: | ---: | ---: |
| Fresh prefill | 15 | 1450 | 70.1% |
| Denoise, all rows | 15 | 850 | 29.9% |
| Framework/other | 15 | 1.1 | 0.1% |

All 15 unique prompts were fresh prefill (`reused_tokens=0`). In a separate
warmup/repeat run, only the immediately repeated prompt reused KV state:

- Fresh prefill: 29 requests, p50 1447 ms
- Reused prefill: 1 request, p50 213 ms
- Denoise: 30 requests, p50 849 ms

The 0.42 s reused-request path is therefore a cache hit, not the normal
first-seen latency. Prefill is the dominant cost for these short prompts, and
the current dataset order gives almost no KV reuse.

Denoise is not autoregressive decode. It is the structured diffusion forward
over the answer canvas, and its cost depends on the confidence-driven sample
count:

| Samples | Rows | Prefill p50 ms | Denoise p50 ms |
| ---: | ---: | ---: | ---: |
| 1 | 6 | 1378 | 244 |
| 4 | 9 | 1489 | 859 |

The extra samples raise denoise cost by roughly 3.5 times; prefill remains
input-length driven.

## Concurrency

| Concurrency | Errors | p50 ms | p95 ms | Throughput req/s |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0 | 2195 | 2497 | 0.509 |
| 2 | 0 | 4037 | 4956 | 0.508 |
| 4 | 0 | 8014 | 9407 | 0.505 |

The backend serializes or heavily contends under concurrent requests.
Throughput is effectively flat, while p50 latency scales approximately
linearly with concurrency. The Mac service should not be treated as a
parallel-throughput backend without a scheduling or batching change.

TTFT is unavailable because the public Jev path is non-streaming. Process
startup and model-load time are not measured because the benchmark uses an
already running, model-resident service.

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
