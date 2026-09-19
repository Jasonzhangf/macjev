# MacJev Architecture

## Decision

Keep the Jev contract and replace only the inference backend.

```text
TypeSafe SDK or Jev client
        |
        v
MacJev Jev API
        |
        v
Backend interface
        |
        +-- MockBackend       protocol tests only
        |
        +-- DiffGemmaBackend  real Mac Metal inference
                |
                v
        diffgemma serve
                |
                v
        DiffusionGemma Metal
```

The model is not trained or modified.

## CUDA and Mac Split

The existing CUDA OpenJev path uses vLLM private request fields such as:

```text
diffusion_seed_canvas
diffusion_canvas_length
diffusion_max_steps
diffusion_read_only
vllm_xargs
```

The Mac `diffgemma` engine already implements structured reads internally. It
accepts a JSON question schema in the system message and returns JSON answers
in the assistant message. The adapter must translate between the two shapes.

## Preserved Semantics

| Layer | MacJev treatment |
| --- | --- |
| Jev wire API | Preserved |
| Question IDs | Preserved |
| `noul` | Preserved |
| `choice` | Preserved |
| `score` | Preserved |
| Candidate order | Preserved |
| Probability distribution | Preserved |
| Confidence | Recomputed from normalized probabilities |
| Re-read | Mapped to `diffgemma` sample policy |
| Diagnostics | Backend diagnostics retained |

## Request Mapping

Canonical request:

```json
{
  "state": "text",
  "questions": {
    "urgent": {
      "type": "noul",
      "instructions": "Does this need a reply today?"
    },
    "team": {
      "type": "choice",
      "instructions": "Which team owns this?",
      "criteria": {
        "billing": "Payment issue",
        "support": "Customer issue"
      }
    },
    "tone": {
      "type": "score",
      "instructions": "How angry is the customer?",
      "criteria": ["calm", "annoyed", "furious"]
    }
  }
}
```

DiffusionGemma schema:

```json
{
  "questions": [
    {
      "id": "urgent",
      "type": "noul",
      "instructions": "Does this need a reply today?"
    },
    {
      "id": "team",
      "type": "choice",
      "instructions": "Which team owns this?",
      "options": [
        {"name": "billing", "description": "Payment issue"},
        {"name": "support", "description": "Customer issue"}
      ]
    },
    {
      "id": "tone",
      "type": "score",
      "instructions": "How angry is the customer?",
      "levels": ["calm", "annoyed", "furious"]
    }
  ],
  "samples": "auto"
}
```

## Response Mapping

DiffusionGemma returns:

```json
{
  "answers": {
    "urgent": {
      "type": "noul",
      "noul": 0.6,
      "confidence": 0.6,
      "probabilities": {"yes": 0.6, "no": 0.4}
    }
  },
  "diagnostics": {}
}
```

MacJev normalizes this into the stable Jev result shape and preserves the raw
backend response separately for evidence.

## Explicit Limits

- `diffgemma` currently supports at most 26 choice candidates.
- The Mac Metal engine is text-only in the current release.
- `/v1/completions` and vLLM-specific thought-prefix behavior are not assumed.
- CUDA NVFP4 and Mac `.dgq` q4 are not bitwise equivalent.
- Softmax probabilities are not calibrated confidence.

## Failure Policy

The service fails explicitly when:

- the real backend is unavailable
- a choice exceeds the backend label limit
- an image is supplied to the text-only Mac path
- a schema uses an unsupported question type
- the backend response cannot be normalized

There is no automatic fallback from live Metal inference to mock output.

## Control Boundary

The model service returns semantic decisions only.

RouteCodex control truth remains with its existing owners. This service must
not own or reconstruct:

- routing
- provider health
- cooldown
- reselect
- continuation
- retry policy
