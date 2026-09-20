# Project Agent Contract

This file owns project facts and boundaries. Replace bracketed items during the
project setup; do not invent project-specific values. Reusable procedure
belongs in project Skills, and machine workflow belongs in declared guidance
contracts.

## Project Truth

- Purpose and user-visible contract: MacJev is a Mac-native, Jev-compatible
  decision service. It preserves the OpenJev request and response contract
  while replacing the inference backend with the local Metal implementation of
  DiffusionGemma.
- Active implementation and production entrypoints: `src/macjev/` owns the
  service, configuration, HTTP boundary, and managed daemon lifecycle;
  `scripts/macjev-server` and `macjev.cli` are the production entries;
  `playground/` contains experimental and evaluation entrypoints.
- Compatibility and legacy boundaries: the CUDA/vLLM OpenJev implementation is
  the compatibility reference, not a runtime dependency. `diffgemma` is the
  only real inference backend. The explicit mock backend is limited to protocol
  tests. Draft `webauto-v3/` material is not an approved runtime path.

## Semantic Invariants

- Preserve the request, response, state, and error semantics declared by this
  project.
- Fail explicitly at the owning boundary; do not add guessed repair, fallback,
  downgrade, silent drop, or success-wrapped error.
- Keep control state separate from business payload and metadata when the
  project has both planes.
- One semantic responsibility has one owner and one implementation.
- Control and configuration truth uses declared typed control resources, error
  chains, or project configuration sources. Request/response payloads,
  metadata, debug logs, and implicit context never carry control truth.
- Browser control state stays outside the Jev request and response. MacJev
  receives only the bounded page observation and action catalog when a browser
  adapter is explicitly implemented.

## Ownership

- Declare each module, resource, mutable truth, and cross-module edge with one
  owner.
- Record allowed and forbidden paths at the narrowest stable boundary.
- Derived output never becomes a second source of truth.
- If this project declares a fixed lifecycle skeleton, preserve its operation,
  hook and gate boundaries. Do not introduce that architecture by default.
- Before adding behavior, check whether it is needed and already owned. Reuse a
  shared function for common semantics; retain separate implementations only
  for necessary differences.
- Missing operators, hooks, or gates fail or skip explicitly with a recorded
  reason. They never produce mock success.

## Architecture Truth

- Maintain only the maps this project requires for ownership, affected
  boundaries and verification. Do not duplicate the same facts across maps.
- Runtime ownership is split by boundary: `src/macjev/cli.py` owns command
  dispatch, `src/macjev/config.py` owns TOML truth, `src/macjev/supervisor.py`
  owns managed daemon lifecycle, `src/macjev/http.py` owns HTTP authentication
  and projection, and `src/macjev/service.py` plus `src/macjev/schema.py` own
  Jev normalization. `src/macjev/backends/diffgemma.py` is the only real
  inference adapter.
- Missing or ambiguous ownership blocks the affected change, not unrelated
  project work.
- Update maps and verification gates in the same change when ownership, paths,
  call edges, or regression coverage changes.

## Development Process Control

- AppSDK quality, safety and evidence gates are mandatory when applicable.
  Guidance and Memory are auxiliary; no plan or memory write is required by
  default. Select persistent Guidance when it helps the task.
- When using Guidance, bind plans to current goal, task, module, owner, scope,
  declared rule sources, source commit, and tree.
- Within a selected workflow execute declared transitions. Optional nodes use an
  explicit bypass edge, never an undeclared jump.
- Append observations and evidence to the active step. Revise the plan when
  source, scope, owner, rules, environment, or evidence changes.
- Workflow close and lifecycle completion are separate results.
- Review blocks concrete quality, safety, contract and material structural
  regressions. Optional simplification is advisory. Reuse valid evidence when
  relevant inputs are unchanged; rerun affected checks on drift.
- Keep Collab automatic for multi-worker identity, communication and task/file
  ownership. Check conflicts before shared writes. Failure blocks dependent
  collaboration, not independent isolated work or quality checks.
- Long tasks and handoffs may save relevant notes; no automatic promotion to
  memory, Skills or rules. Delivery and retained-resource cleanup are separate.
- Memory stores historical conclusions, source references and retrieval
  summaries. Current facts, rules and gates remain owned by project AGENTS,
  Skills and declared contracts; memory never overrides them.

## Git Protection

- Treat the protected mainline checkout as read-only. Develop in a clean owner
  worktree created from the latest remote mainline and preserve other workers'
  state.
- Configure the project's own commit and push protection. A passing protection
  check proves only the Git boundary.
- Remove the owned worktree and release its claim only after required delivery,
  remote receipt, and retention evidence exist.

## Task Routing

Declare project-owned routes at setup or when the relevant boundary becomes
clear. Guide may assist; enabling it is not a prerequisite.

| Need | Project-owned source |
| --- | --- |
| requirements and architecture | [GOAL.md](GOAL.md), [PLAN.md](PLAN.md), and [docs/architecture.md](docs/architecture.md) |
| feature development and debug | the owning module under `src/macjev/` and the project regression command declared in `.appsdk/project.json` |
| build, install, restart, and replay | [docs/production-runtime.md](docs/production-runtime.md) |
| review and delivery | [AGENTS.md](AGENTS.md) and the declared AppSDK verification contract |
| optional memory retrieval, level-3 writes, and evidence-backed promotion | [.appsdk/skills/project-memory/SKILL.md](.appsdk/skills/project-memory/SKILL.md) |

The `.appsdk/maps/verification-map.json` file is the installed AppSDK canonical
gate catalog. Its Rust commands verify the AppSDK implementation that owns that
catalog; they are not MacJev project commands. MacJev regression execution is
owned by the `macjev-governance-regression` command in
`.appsdk/project.json`.

## Evidence Boundary

- Report source, test, build, installed artifact, restart, deployed-entrypoint
  replay, review, merge, remote receipt, freeze, and cleanup separately.
- Never infer a later evidence level from an earlier one.
- A blocked result names the first failing gate, preserved state, retry policy,
  owner, and one executable next action.
