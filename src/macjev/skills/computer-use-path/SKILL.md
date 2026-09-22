---
name: computer-use-path
description: "Use when a model or agent must locate a control in a desktop app for the first time, record a replayable locator path, or decide how to replay and correct a recorded path. Covers anchor requirements, AX-rich vs AX-poor handling, and explicit escalation. Not for execution or workflow ownership."
---

# Computer Use Path

Use this Skill through the standard computer-use contract:

- `docs/computer-use-framework.md`
- `docs/vision-computer-use-api.md`
- `docs/product-positioning.md`

## Scope

Use for:

- the first, exploratory location of a control in a desktop window;
- recording that location as a replayable locator with anchors;
- deciding which anchor to try first for a given application;
- replaying a recorded path and handling a miss or a mismatch;
- deciding whether to escalate to visual grounding.

Do not use for:

- executing operations (that is the driver and its guard);
- owning retries, DAG transitions, or promotion policy;
- inventing coordinates, selectors, or element identities;
- treating a successful call as a successful operation;
- object identification or tracking.

## The Two Kinds of Application

Measure this before choosing anchors. It is not a preference, it is a property
of the app, and it decides which anchor can work at all.

| Kind | What the AX tree exposes | Example measured | Consequence |
| --- | --- | --- | --- |
| AX-rich | controls, roles, labels, identifiers | WeChat 149 nodes, 51 buttons, 6 identifiers | structural anchors work; screenshot can be skipped |
| web-content, awake | full document under an `AXWebArea`, DOM ids and class lists included | ChatGPT 2436 nodes, 164 DOM ids, 1218 press-capable | structural anchors work; `AXDOMIdentifier` and role+title are the strong keys |
| dormant web renderer | window chrome only, document absent | Obsidian 10 nodes, LM Studio 13 | the document has not been published yet — see below before falling back to vision |

A first-location pass must classify the window and say which class it decided,
before recording anything. A window that produces a "successful" structural
locator against chrome only is a false positive waiting to happen.

### Wake a dormant web renderer before giving up on structure

Chromium-derived applications (Electron, CEF, and vendor forks such as ChatGPT
and QQNT) build their AX tree lazily. It stays dormant until an assistive client
announces itself, so a plain walk sees only wrapper groups — indistinguishable
from a genuinely AX-poor native window. `observe` already performs this wake-up
and reports the outcome in `diagnostics.accessibility`:

| Value | Meaning |
| --- | --- |
| `not_applicable` | no web renderer in the process; structure is whatever it is |
| `enabled` | the renderer was dormant and is now publishing; re-read the tree |
| `already_enabled` | the renderer was already awake |
| `unsupported` | the attribute is unavailable; treat as a native window |

The discriminator is the live process tree, not the bundle layout and not the
tree shape: every Chromium-derived app runs a `Renderer` child process, and no
native app does. Bundle layout is unreliable — ChatGPT nests its helper inside
its own framework and QQNT ships no Chromium-named framework at all.

Only conclude "AX-poor, needs vision" when `accessibility` is `not_applicable`
or `unsupported` and the tree is still thin.

## Anchors Are a Ranked Set, Not One Key

Record every anchor the window actually exposes. One key is never enough:

| Priority | Anchor | Survives layout shift | Notes |
| --- | --- | --- | --- |
| 1 | `identifier` (AXIdentifier) | yes | best when present; often absent |
| 2 | `role` + `title`/`description` + ancestor roles | yes | must be unique; collides on lists |
| 3 | `element_chain` (window-rooted sibling indices) | **no** | fast, precise, unsafe alone |
| 4 | geometry (bbox relative to window) | partially | needed for AX-poor apps |
| 5 | visual description or crop | yes | for AX-poor apps and confirmation |

### Why chain alone is unsafe

Measured: inserting one view above a target moved it from chain `1` to `2`,
and chain `1` then resolved to the newly inserted element. Replay by chain
returned success on the wrong control.

So: a chain is a fast hint, never the identity. If the recorded anchors
resolve to a different element than the chain suggests, trust the stronger
anchor and treat the chain as stale.

## First Location Procedure

1. Observe the window and record the revision.
2. Classify AX-rich or AX-poor from the element count and the presence of
   content roles below the window.
3. Capture all anchors the tree exposes for the target: identifier, role plus
   title/description plus ancestor roles, chain, and geometry.
4. If the app is AX-poor, or the target has no unique structural anchor,
   capture a visual anchor: a crop reference, the window-relative bbox, and a
   short semantic description.
5. Record the postcondition that proves the operation happened, not just that
   the call returned.
6. Emit the locator set plus the AX-rich/AX-poor decision and the reason.

Never record only a chain. Never record a coordinate without its window
revision and a hit-test expectation.

## Replay Procedure

1. Observe fresh. Do not reuse the recorded revision.
2. Resolve anchors in priority order and stop at the first unique hit.
3. If the strongest hit disagrees with the chain, prefer the stronger anchor
   and mark the chain stale.
4. Ask the driver to guard the operation.
5. Execute only on `allow`.
6. Observe again and check the recorded postcondition.

## Guard Outcomes and Escalation

| Verdict | Reason | Action |
| --- | --- | --- |
| `allow` | anchor matched, hit-test agreed, not occluded | execute, then verify postcondition |
| `deny` `candidate_not_found` | recorded element is gone from the revision | re-locate; do not guess a replacement |
| `deny` `point_target_mismatch` | point resolved to a different control | re-locate; never click anyway |
| `deny` `point_occluded` | another window covers the point | raise/focus the window, then retry once |
| `deny` `element_disabled` | control is disabled | stop; this is application state, not a locator fault |
| `unknown` `element_action_unavailable` | no `AXPress`, but geometry exists | use a guarded point click |
| `unknown` `point_identity_unverified` | point without an expected element | supply the expected element id |

Escalate to visual grounding only on `deny` or `unknown`, and only with a
candidate identifier, never a free coordinate.

### A point click is normal, not a fallback

Measured: WeChat's entire left navigation is 51 buttons with zero `AXPress`.
Rejecting them because `AXPress` is missing would exclude the most common
operations. A guarded point click is the correct primary path there.

### Hit-test identity is not the observed identity

Hit-test is anchored at the application root; observe is anchored at the
window root. The same control legitimately reports two different IDs, and
hit-test often lands on a deeper child. The correct relation is *the hit lands
inside the expected control*, not *the IDs are equal*.

## Invariants

- The chain is a hint, never the identity.
- A recorded path is stale until a fresh observation confirms it.
- `deny` and `unknown` never become an execution.
- Escalation is explicit and recorded; there is no silent fallback.
- Missing anchors are an explicit error, never a guess.
- A successful call is not a successful operation; only the postcondition is.
- The application owns retry, promotion, and workflow state.
- Confidence never widens the guard; it may only reduce how often the
  postcondition is re-checked, and only under an application-owned policy.

## Reporting Back

Report: the AX-rich/AX-poor decision and its evidence, the anchors recorded and
which were unique, the replay outcome (which anchor hit, at which revision),
the guard verdict and reason code, and the postcondition result. Do not report
a recorded path as reliable until it has been replayed on a changed window.
