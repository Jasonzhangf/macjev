# Computer-Use Framework

Status: implemented candidate; validated on live macOS windows.

This document defines the desktop-side companion to
[`vision-computer-use-api.md`](vision-computer-use-api.md). MacJev owns bounded
observation, guarding, and admitted execution. It does not own workflow,
planning, or application semantics.

## 1. Position

```text
application / agent
  -> picks a window and an intent
  -> MacJev observe          (AX tree + screenshot + revision)
  -> application proposes    (element_id, or point + expected_element_id)
  -> MacJev guard            (allow / deny / unknown)
  -> MacJev act              (only if allow)
  -> MacJev verify           (fresh observe)
  -> application decides     (accept, retry, or repair)
```

The driver is window-scoped. It never drives the whole desktop and never
invents a target.

## 2. Observation Contract

`observe` returns one immutable revision:

```json
{
  "revision": "sha256:...",
  "window": {"window_id": 48032, "bounds": {"x": 1660, "y": 469, "width": 520, "height": 292}},
  "elements": [
    {
      "element_id": "sha256:58de...",
      "element_chain": "0",
      "role": "AXButton",
      "identifier": "fixture-increment",
      "position": {"x": 1689, "y": 554},
      "size": {"width": 142, "height": 38},
      "actions": ["AXPress"]
    }
  ],
  "screenshot": {"ref": "file:///...", "digest": "sha256:...", "width": 520, "height": 292},
  "truncated": false
}
```

Rules:

- `element_id` is derived from the window-rooted sibling chain plus stable
  attributes (`role`, `subrole`, `title`, `identifier`). It is stable across
  fresh observations of an unchanged tree and never uses pointer identity or
  geometry.
- The revision binds both the AX tree and the screenshot digest, so a purely
  visual change invalidates the revision.
- The AX tree is rooted at the matched window, not at the application, so menu
  items and other application-global nodes are excluded.
- Window matching uses `AXWindowNumber` when available, then title, then frame.

## 3. Guard Contract

`guard` returns exactly one of `allow`, `deny`, or `unknown`.

| Verdict | Meaning |
| --- | --- |
| `allow` | The operation is admitted for this revision |
| `deny` | The operation contradicts the observation |
| `unknown` | Evidence is insufficient; the application must not execute |

Element clicks are checked for existence, enabled state, `AXPress`, and window
intersection. Point clicks are hit-tested and must resolve to
`expected_element_id`. `set_value` requires a settable element.

Point clicks accept two relations, because hit-test is anchored at the
application root while observe is anchored at the window root:

- the hit element is the expected element; or
- the hit element lands inside the expected element's box (hit-test often
  returns a deeper child, such as a button's icon).

Exact ID equality alone is the wrong test and would deny valid clicks.

Before admitting a point click, the guard also checks occlusion: it asks
`window-at-point` which on-screen window is topmost at that point. A different
window at layer `0` denies with `point_occluded`; windows in a higher layer
(Dock, menu bar, and full-screen overlays) are ignored.

`act` re-runs `guard` internally. A non-`allow` verdict raises
`computer_driver_error` and nothing is executed.

### Why a point click is a normal path

Not every clickable control exposes `AXPress`. Measured on WeChat: 51
`AXButton`s, of which only 3 expose `AXPress`, including the entire left
navigation. Element press cannot be the primary path for such apps; a guarded
point click is.

### A point click must activate the window first

Measured: a synthetic click posted at a control's center on an **inactive**
application is consumed as the activating click and never reaches the control.
The driver reported `performed: true` while the UI did not change, and the
window revision stayed identical.

The driver now activates the owning application and raises the target window
before posting the click, then waits briefly for the window server. Verified on
a fixture while another app was frontmost: 3/3 clicks delivered, where before
the fix 3/3 were swallowed.

Consequence for any recorded path: a "successful" point click is not evidence
of anything. Only the postcondition is.

## 4. Point Clicks

A point click carries two fields:

```json
{
  "kind": "click",
  "point": {"x": 1760, "y": 573},
  "expected_element_id": "sha256:58de..."
}
```

The driver receives `mode: "point"` and never an `element_id`, so a verified
point cannot silently degrade into an `AXPress`. Element clicks receive
`mode: "element"`.

## 4a. Keyboard and Extended Mouse Input

The driver originally had no keyboard path at all and a single unconditional
left click. Both are now first-class operations.

Mouse primitives: `mouse-move`, `drag` (`x/y` to `to-x/to-y`, interpolated over
`steps`), `scroll` (`dx`/`dy` wheel pixels, parked on the point first because
wheel events go to the view under the pointer). `click-point` accepts `button`
and `count`, and the click count is written to `mouseEventClickState` on both
the down and up events so AppKit reports a real double click.

Keyboard: `type-text` posts each character as a Unicode payload on its own
event pair; `key-tap` takes a named key (`return`, `escape`, `delete`, arrows,
letters, digits, function keys) plus `modifiers` (`cmd`, `shift`, `alt`,
`ctrl`), and also accepts a combined form such as `cmd+v`.

Two measured behaviours shaped this:

1. Sending the whole string in one event lost characters in hosts that route
   input through a separate process, so text is posted one character at a time.
2. `AXUIElementSetAttributeValue` on a text field can return
   `performed: true` and change nothing — observed on WeChat, where the value
   never applied. A real key event is the only reliable path, which is why
   `set_value` cannot be the sole write mechanism.

### Keyboard operations must assert their focus target

Keyboard input carries no coordinates, so the element holding focus *is* the
target. Observed failure mode: a point click was posted, focus never moved, and
the following keystrokes landed in whatever held focus — the operation reported
`performed: true` the whole way.

`type-text` and `key-tap` therefore require `expect_role` / `expect_identifier`
/ `expect_title`, and the driver refuses to post events unless the application
reports that exact element as the focus holder. The refusal is the point: it
converts silent corruption into `focus_mismatch`. `click-point` accepts the
same assertion optionally, to verify the focus a click was supposed to produce.

Focus transfer is asynchronous, so the assertion retries briefly
(`requireFocusSettled`, 1s) instead of racing the host application's run loop.

### Focus is not enough: the window must also be frontmost

Measured: WeChat reported the search field as the AX focus holder while the
terminal was the frontmost application, and every keystroke went to the
terminal. Synthetic keyboard events are delivered to the **frontmost**
application, not to the application holding accessibility focus, so a focus
assertion alone does not predict where a keystroke lands.

`type-text` and `key-tap` therefore call `requireFrontmost` first and fail with
`window_not_frontmost` rather than posting into the wrong application. Order
matters: activation also resets the application's first responder, so the
sequence is activate, wait for frontmost, then assert focus — never the reverse.

### Host-rendered panes need polling, not a fixed delay

Measured on WeChat: clicking a session row collapsed the accessibility tree from
~129 elements to ~58 (sidebar only) for about three seconds, then the full tree
returned. A background window shows the same collapsed shape. Any step that
reads chat-level elements must poll for them instead of sleeping a fixed
interval, or it reports a false failure and the real cause looks like a broken
click.

### Verified send path

`playground/wx-monitor-probe/demo/wechat_demo.py` runs the loop end to end:
resolve a session by name, click it, verify `current_chat_name_label`, clear the
input, assert focus, type, send, and confirm the text appears in
`chat_message_list`. Two traps it encodes:

- Leftover input text silently prefixes the next message (observed: a stale
  `rr` produced `rrmacjev-demo-test`). The demo clears the field and requires an
  exact match before sending, not a substring match.
- The message list extends past the window's own vertical midpoint; a
  hard-coded y bound dropped real messages. The scan is bounded by
  `chat_message_list`'s own frame.

Consequence for the container contract: a click that only "succeeds" proves
nothing. The focus it was supposed to establish is the postcondition, and it
must be asserted.

## 4b. Path Recording and Replay

The model-facing contract for first-time location and path replay lives in the
`computer-use-path` Skill. It requires a ranked anchor set rather than a single
key, because a recorded chain does not survive a layout change: measured, one
inserted view shifted the target from chain `1` to `2`, and chain `1` then
resolved to the newly inserted element.

The guard is what makes replay safe. A stale `element_id` against a fresh
revision returns `deny / candidate_not_found`; it is never silently remapped
onto whatever now occupies the old position.

### Observed element coverage

Interactive elements only, measured across seven apps, with the web renderer
awake (see below):

| App | interactive | has AXIdentifier | unique role+title | geometry only |
| --- | --- | --- | --- | --- |
| Obsidian | 3 | 0 | 0 | 3 |
| ChatGPT | 387 press-capable | 164 DOM ids | role+title | 0 |
| WeChat | 51 | 6 | 18 | 28 |
| QQ | 3 | 0 | 0 | 3 |
| iTerm2 | 20 | 8 | 11 | 9 |
| App Store | 32 | 8 | 2 | 23 |
| LM Studio | 3 | 0 | 0 | 3 |

Native AppKit windows expose identifiers and labelled controls.

Chromium-derived windows expose their whole document too, but only once their
renderer is awake. Until then the walk sees wrapper groups and chrome, exactly
like a sparse native window. `observe` performs the wake-up and reports the
result in `diagnostics.accessibility` (`not_applicable`, `enabled`,
`already_enabled`, `unsupported`). ChatGPT goes from 4 window-subtree elements
to 2436, with an `AXWebArea` carrying `AXDOMIdentifier`, `AXDOMClassList` and
`ChromeAXNodeId`. Obsidian and LM Studio stay thin because their own windows
were not loaded for this measurement; their helpers are present, so the
renderer can be woken the same way.

The discriminator is the live process tree — a `Renderer` child process — not
the bundle layout and not the tree shape. Bundle layout is unreliable: ChatGPT
nests its helper inside its own framework, and QQNT ships no Chromium-named
framework at all. Tree shape is worse: a dormant renderer and a sparse native
window are identical.

## 5. Interfaces

HTTP:

```text
GET  /v1/computer/windows
POST /v1/computer/observe
POST /v1/computer/guard
POST /v1/computer/act
POST /v1/computer/verify
```

MCP: `macjev_computer_windows|observe|guard|act|verify`.

CLI:

```text
macjev computer windows
macjev computer observe --window <id> --output <png> --observation-output <json>
macjev computer guard --observation <json> --element-id <id>
macjev computer act   --observation <json> --element-id <id>
macjev computer daemon-start|daemon-status|daemon-stop
```

`macjev serve --no-computer` disables the driver and returns
`capability_unavailable` on computer routes.

## 6. Driver Lifecycle

- The Swift driver compiles to `~/.macjev/bin/macjev-computer-driver`.
- Cache invalidation uses the source SHA-256 stored next to the binary.
- The daemon listens on `~/.macjev/run/computer-driver.sock` with an owned PID
  file at `~/.macjev/run/computer-driver.pid`.
- Clients use the socket when present and fall back to a one-shot subprocess.
- Observations persist under `~/.macjev/computer/observations/`, so guard and
  act can recover a revision across processes (HTTP, MCP, CLI).
- Screenshots live in `~/.macjev/computer/` and are pruned to a fixed
  retention count.

## 7. Measured Performance

Apple M3 Ultra, macOS 26.6.2, Swift 6.2.4. Obsidian window, 1213x884,
298 AX elements, warm daemon.

| Stage | Before | After |
| --- | --- | --- |
| `list_windows` | 85 ms (spawn) | 15 ms |
| `observe` | 1150 ms | 135-200 ms |
| `hit_test` | 134 ms (spawn) | 6-12 ms |
| element guard | ~0 ms | ~0 ms |

Two changes produced the gain:

1. The AX walk computes the sibling chain incrementally instead of re-walking
   ancestors per element. This removed ~660 ms of redundant parent lookups.
2. A persistent socket removes per-call process spawn and repeated
   `AXUIElementCreateApplication` warmup.

Remaining `observe` cost is dominated by `ScreenCaptureKit` capture
(~170-230 ms). Reducing it further means capturing only a changed region, not
switching the model.

Reproduce:

```bash
PYTHONPATH=src python3 tests/benchmark_computer.py --app Obsidian --runs 5
```

## 8. Acceleration Direction

Ordered by measured return:

1. Keep the driver daemon warm; never spawn per action.
2. Diff the AX tree and screenshot digest; only re-send changed elements.
3. Capture only the window and, when possible, only the changed region.
4. Cache by `window_id + revision + tree digest + screenshot digest`.
5. For visual fallback, detect candidate bboxes first and let the model choose
   a candidate ID rather than regress free coordinates.
6. Reuse model prefill; do not quantize further before prefill and image tokens
   are reduced.

## 9. Verification

- `swiftc -parse-as-library -O` builds the driver cleanly.
- Unit tests: `python3 -m unittest discover -s tests` (128 tests).
- Live loop on the fixture app: element click incremented `count=0 -> count=1`;
  hit-tested point click incremented `count=1 -> count=2`; `set_value` wrote
  `hello-macjev`; `verify` reported `found: true`.
- Live tree scope: Obsidian 298 nodes, Finder 476 nodes, WeChat 123 nodes,
  fixture app 10 nodes, all `truncated: false`.

## 10. Boundaries

- No workflow, planner, retry policy, or promotion logic in the driver.
- No free-coordinate click without a hit-test match.
- No global desktop control.
- No object tracking; that is a separate extension.
