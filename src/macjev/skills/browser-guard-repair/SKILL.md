---
name: browser-guard-repair
description: "Use when an application needs MacJev to guard a proposed browser operation, validate selector semantics and target identity, or propose bounded repair candidates. Not for browser execution or workflow ownership."
---

# Browser Guard and Repair

Use this Skill only through the standard browser guard and repair server
contract:

- `docs/browser-guard-repair-api.md`
- `docs/product-positioning.md`

## Scope

Use for:

- selector, semantic, spatial, risk, and postcondition guard decisions;
- checking whether a proposed operation matches its intended target;
- returning `allow`, `deny`, `unknown`, `risk_control`, or `unavailable`;
- ranking application-supplied candidates after `deny` or `unknown`;
- providing evidence for an application-owned repair or promotion policy.

Do not use for:

- executing browser operations;
- generating selectors or JavaScript;
- creating candidates, URLs, or workflows;
- owning retry counts or DAG transitions;
- treating a model answer as a successful operation;
- treating visual coordinates as the primary locator.

## Required Inputs

- `page_revision` and `viewport_revision`;
- bounded candidates with IDs and source revisions;
- the proposed operation;
- expected target semantics and postconditions;
- required guard kinds;
- policy ID.

Missing priors are explicit errors or `unavailable`, never guessed.

## Required Outputs

- one typed top-level verdict;
- `guard_id`, `guard_version`, `subject_ref`, and `evidence_ref`;
- per-guard diagnostics;
- model, backend, policy, and latency diagnostics;
- bounded repair proposals only when requested.

## Invariants

- Camo remains the browser execution owner.
- The application owns page and workflow state.
- MacJev never receives or returns browser control state as model truth.
- Scores are diagnostics, not verdicts.
- `unknown` and `unavailable` never become `allow`.
- A click result is not success without a postcondition anchor.
- Promotion is application-owned and per action identity.
