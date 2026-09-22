# Computer-Use Containers and Flows

Status: design, first scope = 微信 / ChatGPT / QQ.

This document defines the container and flow layer for computer use. The
framework (observation, guard, correction) stays in MacJev. Containers and
flows are assets and live in the `webauto` project, in a directory parallel to
its existing browser container library, so the application layer consumes both
the same way.

## 1. Division of Ownership

| Layer | Owner | Responsibility |
| --- | --- | --- |
| Observation, guard, correction | MacJev | AX observation, hit-test, occlusion, verdicts, bounded repair |
| Container definitions | webauto | named regions, matchers, members, per-app knowledge |
| Operation definitions | webauto | intent, target container, parameters, postcondition |
| Flows | webauto | ordered operations that reach one goal |
| Execution | application | run the flow, decide retry/promotion |

MacJev never ships app knowledge. webauto never re-implements guard logic.

## 2. Why Containers Are Declared, Not Discovered

Measured on 微信: 132 AX nodes, but only 7 nodes have two or more children, and
only 1 of those is itself interactive. The app never names its regions — the
left navigation is an anonymous `AXGroup` holding 11 children. Nothing in the
tree says "this is a navigation bar".

So a container is a **declared matcher plus the members it resolves to**. The
browser library already works this way (`selectors` + `capabilities` +
`operations`); computer use mirrors it with AX matchers instead of CSS.

## 3. Container Definition

```json
{
  "id": "wechat.nav_bar",
  "app": {
    "bundle_id": "com.tencent.xinWeChat"
  },
  "kind": "navigation",
  "matcher": {
    "anchor_role": "AXGroup",
    "member_role": "AXButton",
    "min_members": 6,
    "uniform_size": true,
    "flat": true
  },
  "capabilities": ["enumerate", "find_by_label", "find_by_index", "hit_test"],
  "members": {
    "identity": "label",
    "fallback": "index_within_container"
  }
}
```

`bundle_id` is the profile key. Measured: every in-scope app exposes one
(`com.tencent.xinWeChat`, `com.openai.codex`, `com.tencent.qq`), whereas window
titles are not unique — iTerm2 exposes three different titles.

### Matcher fields

| Field | Meaning |
| --- | --- |
| `anchor_role` | role of the region node, or `"*"` for the window itself |
| `member_role` | role of the controls inside the region |
| `min_members` | smallest member count that still counts as this container |
| `uniform_size` | require all members to share one size |
| `flat` | require members to be direct siblings |

`uniform_size` + `flat` is what isolates 微信's session list: 12 siblings of
exactly 200x68. The same rule does **not** isolate the left navigation, whose
children have three distinct sizes — that container needs `uniform_size` false
and a role filter instead.

## 4. Container Kinds for the First Scope

| Kind | Matcher | Measured evidence |
| --- | --- | --- |
| `navigation` | group, labelled buttons, few distinct sizes | 微信 11 children, 10 clickable |
| `list` | `AXList`/`AXTable`/`AXOutline` | 微信 51 session rows, 12 contact rows |
| `text_input` | `AXTextArea`/`AXTextField` with `settable` | 微信 `chat_input_field`, settable 2/2 |
| `action_bar` | single row of equal-size unlabelled buttons | 微信 7 icon buttons at y=993 |

Do not nest containers. The AX nesting depth is 8 and semantically empty, so
nesting would encode app implementation detail. A flow expresses order; a
container list stays flat.

## 5. Operation Definition

```json
{
  "id": "wechat.open_contacts",
  "container": "wechat.nav_bar",
  "selector": {
    "label": "通讯录"
  },
  "kind": "click",
  "postcondition": {
    "kind": "tree_contains",
    "role": "AXList",
    "value": "通讯录"
  }
}
```

The postcondition is a required field. A click cannot be verified by its own
return value: measured, a recorded chain resolved to the wrong element after a
layout shift while still reporting success.

First-scope operation kinds: `click`, `set_text`, `send`, `select_row`.

### Postcondition forms that actually work

Measured on 微信:

| Form | Works | Note |
| --- | --- | --- |
| `tree_contains` | yes | clicking 通讯录 produced `AXList` titled 通讯录; element count 132 -> 58 |
| `element_count_delta` | yes | same event, 132 -> 58 |
| `value_equals` | yes | for `set_text` on a settable field |
| `window_title_changed` | **no** | 微信's title stays "微信" across tabs |

## 6. Flow Definition

```json
{
  "id": "wechat.send_message",
  "app": {"bundle_id": "com.tencent.xinWeChat"},
  "steps": [
    {"operation": "wechat.open_session", "params": {"name": "付邦"}},
    {"operation": "wechat.set_text", "params": {"text": "hello"}},
    {"operation": "wechat.send"}
  ]
}
```

The flow is a flat ordered list. Each step's postcondition gates the next step.
On a failed postcondition the application decides: retry, repair, or abort.
MacJev only supplies the guard verdict and any bounded correction.

## 7. First-Location and Replay

The model performs the flow once to record it, then replay is deterministic.
Recording and replay rules live in the `computer-use-path` Skill; the essential
points are that a locator is a ranked anchor set (identifier, then
role+label+ancestors, then chain, then geometry), never a chain alone, and that
a replay is stale until a fresh observation confirms it.

Correction is MacJev's job, but only as a verdict: `deny` with a reason code
and, when requested, a bounded set of candidate replacements. Promotion back to
automatic is application-owned.

Per-app readings are recorded in
[`wechat-verification.md`](wechat-verification.md).

## 8. Scope and Non-Goals

In scope: 微信, ChatGPT, QQ.

Earlier scope notes recorded ChatGPT as AX-poor (12 nodes, chrome only). That
reading was taken while its Chromium renderer was dormant and is wrong.
`observe` now wakes the renderer and reports the result in
`diagnostics.accessibility`; woken, ChatGPT exposes 2436 nodes including an
`AXWebArea` with DOM identifiers, so its flows are expressible with AX
containers and the question of a DOM or visual container is closed for the
first scope.

Non-goals for the first scope: free-coordinate clicking, container nesting,
storing flows in MacJev, and automatic promotion without a postcondition.
