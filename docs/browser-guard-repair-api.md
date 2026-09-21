# Browser Guard and Repair API

Status: proposed standard interface.

This document defines the server boundary for browser guard and repair. It
does not define a Camo replacement or a browser workflow runtime.

## 1. Ownership

| Owner | Responsibility |
| --- | --- |
| Application | goal, page revision, candidates, operation, retry, promotion, postcondition |
| Camo | target, profile, DOM observation, input, navigation, browser result |
| MacJev browser guard | semantic/visual verdict and bounded repair proposal |
| Policy store | versioned threshold, required guards, and promotion rules |

MacJev returns a verdict or proposal. The application executes through Camo.

## 2. Endpoint

```text
POST /v1/browser/guard
POST /v1/browser/repair
```

The endpoints are capability endpoints, not Jev model aliases.

## 3. Common Envelope

```json
{
  "api_version": "1",
  "request_id": "string",
  "run_id": "string",
  "node_id": "string",
  "page_revision": "string",
  "viewport_revision": "string",
  "policy_id": "string"
}
```

All revisions are opaque strings. The server does not derive browser control
truth from them.

## 4. Guard Request

```json
{
  "api_version": "1",
  "request_id": "guard-1",
  "run_id": "run-1",
  "node_id": "submit-post",
  "page_revision": "page-r17",
  "viewport_revision": "vp-1280x720-r17",
  "policy_id": "browser-guard-v1",
  "observation": {
    "url": "https://example.test/compose",
    "title": "Compose",
    "screenshot_ref": "artifact://screenshots/page-r17.png",
    "dom_digest": "sha256:..."
  },
  "operation": {
    "operation_id": "op-1",
    "kind": "click",
    "target_candidate_id": "candidate-submit",
    "expected_effect": "publish the composed post",
    "postconditions": [
      {
        "kind": "url_contains",
        "value": "/post/"
      }
    ]
  },
  "candidates": [
    {
      "candidate_id": "candidate-submit",
      "source": "dom",
      "source_revision": "dom-r17",
      "selector": "button.submit",
      "role": "button",
      "name": "发布",
      "bbox": [1020, 680, 1180, 720],
      "visible": true,
      "enabled": true,
      "parent_candidate_id": "candidate-compose-modal"
    }
  ],
  "required_guards": [
    "selector",
    "semantic",
    "spatial"
  ]
}
```

The selector is evidence supplied by the application. MacJev does not
generate or mutate it.

## 5. Guard Response

```json
{
  "api_version": "1",
  "request_id": "guard-1",
  "guard_id": "browser-guard",
  "guard_version": "1",
  "verdict": "allow",
  "subject_ref": "op-1",
  "evidence_ref": "evidence://guard/guard-1",
  "reason_code": "all_required_guards_passed",
  "diagnostics": {
    "model_id": "diffusiongemma-26b-a4b-it-optiq4-mlx",
    "backend_id": "mlx-optiq",
    "policy_id": "browser-guard-v1",
    "guard_results": [
      {
        "kind": "selector",
        "verdict": "allow",
        "score": 1.0
      },
      {
        "kind": "semantic",
        "verdict": "allow",
        "score": 0.94
      },
      {
        "kind": "spatial",
        "verdict": "allow",
        "score": 0.97
      }
    ],
    "latency_ms": 912.4
  }
}
```

The top-level verdict is the only admission result. Scores remain
diagnostics.

## 6. Verdict Rules

| Condition | Verdict |
| --- | --- |
| All required guards pass | `allow` |
| Selector, semantics, or target identity is contradicted | `deny` |
| Evidence is insufficient or ambiguous | `unknown` |
| Login, captcha, or risk-control state is detected | `risk_control` |
| Required model or guard capability is absent | `unavailable` |
| Page or viewport revision is stale | `deny` |

An absent optional guard does not become an allow. The application must
declare which guards are required.

## 7. Repair Request

Repair is requested only after `deny` or `unknown`.

```json
{
  "api_version": "1",
  "request_id": "repair-1",
  "run_id": "run-1",
  "node_id": "submit-post",
  "page_revision": "page-r17",
  "viewport_revision": "vp-1280x720-r17",
  "policy_id": "browser-repair-v1",
  "failed_guard": {
    "guard_id": "browser-guard",
    "verdict": "deny",
    "reason_code": "semantic_target_mismatch",
    "evidence_ref": "evidence://guard/guard-1"
  },
  "intent": {
    "operation_kind": "click",
    "semantic_goal": "publish the composed post"
  },
  "candidates": [
    {
      "candidate_id": "candidate-publish",
      "source": "dom",
      "source_revision": "dom-r17",
      "role": "button",
      "name": "发布",
      "bbox": [1020, 680, 1180, 720],
      "visible": true,
      "enabled": true
    },
    {
      "candidate_id": "candidate-save-draft",
      "source": "dom",
      "source_revision": "dom-r17",
      "role": "button",
      "name": "存草稿",
      "bbox": [860, 680, 1010, 720],
      "visible": true,
      "enabled": true
    }
  ]
}
```

The candidate catalog is application-owned and bounded.

## 8. Repair Response

```json
{
  "api_version": "1",
  "request_id": "repair-1",
  "proposals": [
    {
      "candidate_id": "candidate-publish",
      "rank": 1,
      "confidence": 0.93,
      "reason_code": "semantic_match",
      "required_rechecks": [
        "selector",
        "spatial",
        "postcondition"
      ]
    }
  ],
  "diagnostics": {
    "model_id": "diffusiongemma-26b-a4b-it-optiq4-mlx",
    "backend_id": "mlx-optiq",
    "policy_id": "browser-repair-v1",
    "latency_ms": 1104.8
  }
}
```

Repair proposals are not operations. The application must re-observe and
re-run the guard before execution.

## 9. Required Guard Semantics

### Selector guard

Checks existence, uniqueness when required, visibility, enabled state, parent
container, revision, and hit point. A selector is a locator, not semantic
identity.

### Semantic guard

Checks role, label, surrounding text, expected target semantics, and the
selected candidate ID against the bounded catalog.

### Spatial guard

Checks bbox, viewport intersection, occlusion, hit point, and optional
visual-region evidence. A visual point is secondary evidence.

### Risk guard

Checks login, captcha, account warnings, destructive actions, and other
application-declared risk boundaries.

### Postcondition guard

Runs after execution. A click result is not success. The expected URL, event,
container, data, or visual state must be observed.

## 10. Automatic Promotion

Promotion is application-owned and per action identity:

```text
page_kind | operation_kind | semantic_goal | selector | parent_selector
```

An action may be promoted only after repeated verified successes with no
guard or repair failure. A failed postcondition or semantic mismatch demotes
the action and creates a regression anchor.

MacJev may recommend promotion. It does not change the application mode.

## 11. Errors

| Code | Meaning |
| --- | --- |
| `invalid_request` | Schema or bounded-input violation |
| `stale_revision` | Page or viewport revision no longer valid |
| `candidate_not_found` | Proposed candidate is not in the catalog |
| `capability_unavailable` | Required guard or model is unavailable |
| `policy_not_found` | Policy ID is unknown |
| `backend_error` | Inference backend failed explicitly |

Errors never carry a success verdict.
