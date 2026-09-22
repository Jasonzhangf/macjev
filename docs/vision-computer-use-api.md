# Vision and Computer-Use API

Status: proposed standard interface.

This document defines how MacJev exposes bounded visual capability to
computer-use and browser-use applications. The API surface itself defines no
desktop executor and no workflow runtime; the companion framework below
implements the desktop executor that consumes it.

The implemented desktop-side companion that owns observation, guarding, and
admitted execution is described in
[`computer-use-framework.md`](computer-use-framework.md).

The model-facing contract for locating a control for the first time and
replaying a recorded path is in the
[`computer-use-path`](../src/macjev/skills/computer-use-path/SKILL.md) Skill.

## 1. Purpose

MacJev answers bounded questions over supplied visual evidence. The
application owns observation, priors, candidate generation, execution, and
postconditions.

```text
window / AX / UIA / DOM / Camo priors
  -> bounded visual question
  -> MacJev visual result
  -> application maps result to a real control
  -> application executes
  -> application verifies postcondition
```

## 2. Endpoints

```text
POST /v1/vision/classify
POST /v1/vision/choose-region
POST /v1/vision/guard
POST /v1/vision/locate
```

`locate` is capability-gated. It may return a region, bbox, or normalized
point only when the active capability probe proves that output mode.

## 3. Common Envelope

```json
{
  "api_version": "1",
  "request_id": "vision-1",
  "run_id": "run-1",
  "subject": {
    "kind": "browser | desktop | window | application",
    "revision": "subject-r17",
    "application_id": "com.example.app"
  },
  "image_ref": "artifact://screenshots/subject-r17.png",
  "image_digest": "sha256:...",
  "image_size": {
    "width": 1280,
    "height": 720
  },
  "policy_id": "vision-guard-v1"
}
```

The image is immutable evidence. A changed image requires a new request.

## 4. Classify

Use for bounded semantic questions over a crop or region.

```json
{
  "api_version": "1",
  "request_id": "vision-classify-1",
  "run_id": "run-1",
  "subject": {
    "kind": "desktop",
    "revision": "desktop-r3"
  },
  "image_ref": "artifact://screenshots/desktop-r3.png",
  "image_digest": "sha256:...",
  "image_size": {
    "width": 1920,
    "height": 1080
  },
  "region": {
    "x": 100,
    "y": 200,
    "width": 300,
    "height": 120
  },
  "labels": [
    "text input",
    "button",
    "menu",
    "unknown"
  ],
  "question": "Which label best describes the supplied region?",
  "policy_id": "vision-classify-v1"
}
```

Response:

```json
{
  "api_version": "1",
  "request_id": "vision-classify-1",
  "result": {
    "kind": "classification",
    "label": "button",
    "confidence": 0.91
  },
  "diagnostics": {
    "model_id": "diffusiongemma-26b-a4b-it-optiq4-mlx",
    "backend_id": "mlx-optiq",
    "latency_ms": 934.2
  }
}
```

## 5. Choose Region

Use for a bounded choice among application-supplied regions.

```json
{
  "api_version": "1",
  "request_id": "vision-choose-1",
  "run_id": "run-1",
  "subject": {
    "kind": "browser",
    "revision": "page-r17"
  },
  "image_ref": "artifact://screenshots/page-r17.png",
  "image_digest": "sha256:...",
  "image_size": {
    "width": 1280,
    "height": 720
  },
  "question": "Which region contains the publish button?",
  "regions": [
    {
      "region_id": "region-left",
      "bbox": [0, 0, 640, 720],
      "label": "left half"
    },
    {
      "region_id": "region-right",
      "bbox": [640, 0, 1280, 720],
      "label": "right half"
    }
  ],
  "policy_id": "vision-region-choice-v1"
}
```

Response:

```json
{
  "api_version": "1",
  "request_id": "vision-choose-1",
  "result": {
    "kind": "region_choice",
    "region_id": "region-right",
    "confidence": 0.88
  },
  "diagnostics": {
    "model_id": "diffusiongemma-26b-a4b-it-optiq4-mlx",
    "backend_id": "mlx-optiq",
    "latency_ms": 1031.7
  }
}
```

Region IDs are application-owned. MacJev never invents them.

## 6. Visual Guard

Use to allow, deny, or mark unknown a proposed visual assertion.

```json
{
  "api_version": "1",
  "request_id": "vision-guard-1",
  "run_id": "run-1",
  "subject": {
    "kind": "desktop",
    "revision": "desktop-r3"
  },
  "image_ref": "artifact://screenshots/desktop-r3.png",
  "image_digest": "sha256:...",
  "image_size": {
    "width": 1920,
    "height": 1080
  },
  "assertion": {
    "subject_region_id": "region-input",
    "predicate": "is visible and unobstructed",
    "expected": true
  },
  "regions": [
    {
      "region_id": "region-input",
      "bbox": [420, 300, 900, 360]
    }
  ],
  "policy_id": "vision-guard-v1"
}
```

Response:

```json
{
  "api_version": "1",
  "request_id": "vision-guard-1",
  "verdict": "allow",
  "subject_ref": "region-input",
  "evidence_ref": "evidence://vision/vision-guard-1",
  "reason_code": "assertion_supported",
  "diagnostics": {
    "model_id": "diffusiongemma-26b-a4b-it-optiq4-mlx",
    "backend_id": "mlx-optiq",
    "policy_id": "vision-guard-v1",
    "confidence": 0.96,
    "latency_ms": 887.1
  }
}
```

## 7. Locate

`locate` is an optional capability. It is not the primary locator when
DOM, AX, UIA, or window metadata provides a target.

```json
{
  "api_version": "1",
  "request_id": "vision-locate-1",
  "run_id": "run-1",
  "subject": {
    "kind": "browser",
    "revision": "page-r17"
  },
  "image_ref": "artifact://screenshots/page-r17.png",
  "image_digest": "sha256:...",
  "image_size": {
    "width": 1280,
    "height": 720
  },
  "target": {
    "semantic_description": "publish button"
  },
  "output": "region",
  "policy_id": "vision-locate-v1"
}
```

Allowed output modes:

```text
region
bbox
normalized_point
```

The capability response must state which output modes are supported:

```json
{
  "api_version": "1",
  "request_id": "vision-locate-1",
  "result": {
    "kind": "bbox",
    "bbox": [1020, 680, 1180, 720],
    "confidence": 0.72
  },
  "diagnostics": {
    "model_id": "diffusiongemma-26b-a4b-it-optiq4-mlx",
    "backend_id": "mlx-optiq",
    "coordinate_space": "pixels",
    "latency_ms": 945.1
  }
}
```

Coordinate outputs are evidence only. The application must project them onto
a real control, verify hit testing and occlusion, and require a postcondition.

## 8. Capability Probe

Before a visual endpoint is enabled, the server must report:

```json
{
  "api_version": "1",
  "backend_id": "mlx-optiq",
  "model_id": "diffusiongemma-26b-a4b-it-optiq4-mlx",
  "capabilities": {
    "classify": true,
    "choose_region": true,
    "guard": true,
    "locate": {
      "region": true,
      "bbox": true,
      "normalized_point": true
    }
  },
  "limits": {
    "max_image_bytes": 20971520,
    "max_regions": 16
  }
}
```

Unsupported modes return `capability_unavailable`, not a guessed answer.

## 9. Computer-Use Priors

Computer-use applications should supply:

- application ID and window ID;
- window frame and revision;
- UIAutomation or AX role, name, value, and bbox;
- visible text or semantic summary;
- candidate region IDs;
- expected operation and postcondition.

Visual questions are asked only when the prior is insufficient, ambiguous, or
needs confirmation.

## 10. Browser-Use Priors

Browser applications should supply:

- URL, title, viewport, scroll, and page revision;
- DOM and ARIA role, name, value, selector, and bbox;
- Camo target/profile as opaque application-owned context;
- candidate region IDs;
- expected operation and postcondition.

MacJev does not receive Camo target IDs as model input and does not own the
browser session.

## 11. Output Rules

- A visual answer is not an operation.
- A bbox is not an object identity.
- A point is not safe for clicking without hit testing.
- A model confidence is not a calibrated probability unless a versioned
  calibration policy says so.
- `unknown` and `unavailable` are explicit outcomes.
- No score bypasses the policy layer.

## 12. Errors

| Code | Meaning |
| --- | --- |
| `invalid_request` | Schema, image, or region violation |
| `image_not_found` | Image reference cannot be resolved |
| `image_too_large` | Image exceeds declared limits |
| `capability_unavailable` | Requested visual mode is not supported |
| `backend_error` | Visual backend failed explicitly |
| `policy_not_found` | Policy ID is unknown |

Errors never carry `allow`.
