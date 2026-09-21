---
name: vision-computer-use
description: "Use when an application needs bounded visual classification, region choice, visual guard, or capability-gated localization for computer-use or browser-use. Not for object tracking, arbitrary agent control, or execution."
---

# Vision and Computer Use

Use this Skill only through the standard visual server contract:

- `docs/vision-computer-use-api.md`
- `docs/product-positioning.md`

## Scope

Use for:

- classifying a supplied crop or region;
- choosing among application-supplied regions;
- answering a bounded visual guard assertion;
- returning a capability-gated region, bbox, or normalized point;
- helping repair when DOM, AX, UIA, or window priors are insufficient.

Do not use for:

- object identification without an application prior;
- object tracking or identity persistence;
- arbitrary desktop or browser control;
- direct execution;
- generating selectors or workflows;
- treating a bbox as stable identity;
- treating a coordinate as safe to click without hit testing.

## Inputs

- immutable image reference and digest;
- image size and coordinate space;
- subject kind and revision;
- bounded regions or labels;
- one bounded question or assertion;
- policy ID;
- application priors when available.

## Outputs

- classification, region choice, visual verdict, or capability-gated
  localization;
- confidence and model/backend diagnostics;
- evidence reference;
- explicit `unknown` or `unavailable`.

## Invariants

- Application priors remain the primary locator.
- Visual output is evidence, not an operation.
- The application maps the result to a real control and executes it.
- The application verifies the postcondition.
- A visual answer never bypasses the guard policy.
- Object identification and tracking are out of scope for this Skill.
