# MacJev Product Positioning

Status: project positioning and roadmap truth.

This document owns the intended role, capability boundaries, and delivery
order of MacJev. It does not claim that every proposed interface is already
implemented.

## 1. Positioning

MacJev is a foundation-capability enabler for applications. It is not a
browser automation application, a WebAuto replacement, a desktop agent, a
workflow runtime, or an end-user product.

Applications own:

- user goals and task state;
- page, window, DOM, accessibility, and platform priors;
- candidate generation;
- workflow and page DAGs;
- execution through Camo, UIAutomation, or an application adapter;
- retries, repair policy, promotion policy, and postconditions.

MacJev owns:

- bounded semantic judgment;
- bounded visual judgment;
- guard verdicts and repair proposals;
- model and inference capability exposure;
- capability probes, typed errors, diagnostics, and evidence shape.

The application always decides what operation is allowed. MacJev never owns
browser or desktop control state.

## 2. Capability Layers

| Layer | Current role | Mainline status |
| --- | --- | --- |
| Text decision | `choice`, `score`, and `noul` over bounded candidates | Implemented service contract |
| Visual guard | Answer bounded visual questions about supplied evidence | Experimental; OptiQ path proven |
| Computer-use guard | Guard a proposed desktop/window/control operation | Proposed standard interface |
| Browser guard | Guard a proposed browser operation and propose bounded repairs | Proposed standard interface |
| Object identification | Find or classify objects without an application prior | Deferred extension |
| Object tracking | Maintain identity or boxes across time | Deferred extension |

Object identification and tracking are not mainline capabilities. They may
become optional adapters after browser and computer-use guards are stable.

## 3. Standard Server Boundary

MacJev exposes capability endpoints, not application workflows.

```text
application observation
  -> bounded candidates and expected operation
  -> MacJev guard or visual capability
  -> typed verdict, proposal, or explicit unavailability
  -> application validates and executes
  -> application verifies the postcondition
```

Every capability endpoint uses the same principles:

- a versioned request and response schema;
- explicit input and output types;
- bounded candidates or bounded visual questions;
- no browser target, profile, selector mutation, or shell command;
- no silent fallback between model or execution providers;
- no raw score promoted directly to `allow`;
- typed `unavailable` when a required capability is absent;
- model, provider, artifact, policy, and latency recorded as diagnostics.

The browser guard and computer-use guard contracts are defined separately:

- [browser-guard-repair-api.md](browser-guard-repair-api.md)
- [vision-computer-use-api.md](vision-computer-use-api.md)

## 4. Browser Guard and Repair

Browser guard is an application-level guard service behind one standard
server interface. It does not replace Camo and does not directly execute
operations.

The application supplies:

- page revision and viewport revision;
- bounded DOM, AX, Camo, or platform candidates;
- the proposed operation;
- expected target semantics and postconditions;
- an optional screenshot or crop reference.

MacJev returns one typed verdict:

```text
allow | deny | unknown | risk_control | unavailable
```

On `deny` or `unknown`, the application may request bounded repair. Repair
returns ranked candidate IDs with evidence. The application re-observes,
validates the candidate, executes through Camo, and verifies the
postcondition. Repeated verified success may be promoted to automatic mode
only by an application-owned policy.

MacJev must not:

- generate selectors or JavaScript;
- invent candidates or URLs;
- click, type, scroll, navigate, or mutate the page;
- own retry counts or workflow transitions;
- treat a plausible model answer as a successful operation.

## 5. Vision and Computer Use

Visual capability is a foundation service used by browser and computer-use
applications. The same contract applies to both.

Supported question classes:

- semantic classification of a supplied crop or region;
- choice among bounded labeled regions;
- yes/no or allow/deny visual guard;
- coarse region selection for repair;
- direct or bounded coordinate evidence where the capability probe permits
  it.

The application supplies window, AX, UIA, DOM, or Camo priors whenever they
exist. Visual output is secondary evidence unless an application policy
explicitly and safely promotes it.

The application remains responsible for:

- turning a visual result into an operation;
- mapping a region or point back to a real control;
- checking hit testing, occlusion, enabled state, and revision;
- executing the operation;
- verifying the postcondition.

Visual coordinates, bounding boxes, and region choices are never stable
object identities.

## 6. Evidence Boundary

Current evidence is split by capability:

| Capability | Evidence state |
| --- | --- |
| Text Jev service | Implemented and evaluated on local fixtures |
| Browser action selection | Evaluated on static browser states |
| OptiQ image path | Experimental compatibility launcher; not productized |
| Browser location | Controlled viewport fixture; direct normalized coordinates worked |
| UI recognition | Controlled fixture; semantic recognition worked, spatial guarantees did not |
| Video/person tracking | Not reliable for identity or real sequences |
| Computer-use UI frames | Capability evidence exists; no stable standard API yet |
| Object identification/tracking | Deferred; not a mainline capability |

Evidence is capability-specific. A successful image probe does not prove
production browser guard behavior. A successful controlled localization does
not prove arbitrary page or desktop localization.

## 7. Roadmap

### Phase 1: Contract and Backend Boundary

- Keep the existing Jev text service stable.
- Define one browser guard/repair server contract.
- Define one vision/computer-use server contract.
- Define capability probes and typed `unavailable` behavior.
- Keep the OptiQ vision path experimental until its owner and serving
  compatibility are selected.

### Phase 2: Browser Guard Vertical Slice

- Use Camo DOM and AX priors as the primary source.
- Guard selector identity, visibility, enabled state, hit point, and expected
  semantics.
- Add bounded repair from the live candidate catalog.
- Require a postcondition anchor after every operation.
- Record verified successes and failures as regression anchors.

### Phase 3: Computer-Use Guard Vertical Slice

- Use window metadata, UIAutomation, AX, and application anchors as priors.
- Apply the same bounded visual guard contract used by browser automation.
- Keep visual localization secondary to application-provided structure.

### Phase 4: Promotion and Self-Correction

- Promote an action identity only after repeated verified success.
- Demote immediately on a failed postcondition or semantic mismatch.
- Keep promotion, rollback, and selector correction application-owned.

### Phase 5: Optional Extensions

- Add object identification only if a concrete application requires it.
- Add tracking only if identity persistence is a proven requirement.
- Keep both outside the browser/computer-use mainline until their contracts
  and acceptance tests are separate.

## 8. Non-Goals

- Replacing Camo or UIAutomation.
- Owning browser or desktop workflows.
- Generating arbitrary selectors or coordinates.
- Treating model confidence as calibrated confidence.
- Making object tracking a prerequisite for browser automation.
- Turning MacJev into a general-purpose agent framework.
