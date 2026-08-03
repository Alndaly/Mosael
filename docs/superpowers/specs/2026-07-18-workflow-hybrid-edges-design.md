# Workflow hybrid edges: control edges + typed data edges

Date: 2026-07-18
Status: Draft for review

## Problem

Open Studio's workflow canvas is Dify/Coze-shaped: an edge means **execution order + branch
routing**, and data flows separately through `{{node.output}}` string references inside
config fields. This is flexible but the data flow is **invisible** — you can't see, on the
canvas, that node B's input is fed by node A's output. ComfyUI makes data flow visible and
first-class (an edge *is* a typed data wire), which reads much better.

But pure ComfyUI is **not enough** for Open Studio: sometimes there is no parameter to pass — you
just want "run B after A" or "run A and B concurrently". A model where every edge must carry
typed data can't express pure ordering/concurrency.

**Goal:** a hybrid — keep pure ordering edges, AND add visible, typed data wires — without
throwing away the existing `{{var}}` model or rewriting the engine.

## Goals / non-goals

Goals:
- Two edge kinds: **control edges** (ordering/concurrency, no data) and **data edges** (a
  specific upstream output → a specific downstream input, carries a value).
- Data flow is visible on the canvas as ComfyUI-style wires between sockets.
- Build on the existing "input: manual ⇄ connect" toggle (already shipped) — an input in
  "connect" mode becomes an input socket that a data edge lands on.
- Engine change is additive: translate data edges into the same input-binding the `{{var}}`
  refs already produce; no handler rewrite.
- Non-destructive migration: existing `{{var}}` refs keep working; optionally visualize them
  as data edges.

Non-goals (for this design):
- Full type enforcement (hard-blocking incompatible connections). Type *hints* are a later,
  optional phase — see [[workflow-type-matching]]; data edges are strings under the hood
  so validation stays **soft** (warn, not block).
- Replacing control edges or the `{{var}}` syntax. Both stay.
- Sub-graph / group nodes.

## The model

### Edge kinds

`graph.edges[]` gains a `kind` discriminator (default `"control"` for back-compat):

```
Control edge:  { id, source, target, source_handle?, kind: "control" }
Data edge:     { id, source, source_output, target, target_input, kind: "data" }
```

- **Control edge** — exactly today's edge. `source_handle` still carries condition branches
  (`"true"`/`"false"`). Means: target runs after source. No data.
- **Data edge** — connects `source.source_output` (one of the source node's declared outputs,
  e.g. `text`, `asset_id`) to `target.target_input` (one of the target node's config fields,
  e.g. `sequence_id`, `prompt`). Means: at runtime, `target.config[target_input]` is bound to
  `source`'s `source_output` value. A data edge **also implies ordering** (source before
  target) — it is a data dependency.

### Socket model (node = control handles + data sockets)

Each `WfNode` renders:
- **Control target handle** — left edge (as today; hidden for `start`).
- **Control source handle** — right edge (as today; condition nodes keep true/false).
- **Data output sockets** — right side, one per entry in the node type's `outputs`
  (`text`, `asset_id`, …). Phase 2; Phase 1 may use a single output socket.
- **Data input sockets** — left side, one per config field currently in "connect" mode.
  This reuses the shipped input-mode toggle: switching a field to "connect" exposes its
  input socket instead of the value dropdown.

### Engine

`app/domain/workflows/engine.py` + `__init__.py`:
1. **Ordering** — `topo_order` and `validate_graph` treat **both** edge kinds as ordering
   constraints (build the DAG from `control` edges ∪ `data` edges). Cycle detection spans both.
2. **Input resolution priority**, per field, highest wins:
   1. **Data edge** bound to that input → use the source output's value from context.
   2. **Manual literal** in `config[field]`.
   3. **Inline `{{var}}`** inside a template/code string (rich-text mixing still works).
3. A data edge is equivalent to `config[target_input] = "{{source.source_output}}"`; the
   simplest implementation lowers data edges into that same reference at execution time, so
   node handlers are untouched.

### Connection rules

- Data edge: from a data **output** socket to a data **input** socket. Self/dup/cycle
  forbidden (existing `isValidConnection`, extended to consider data edges for cycles).
- Control edge: node → node, as today.
- Type compatibility: **not enforced** in this design (soft hints deferred to a later phase).

### Migration (dropped 2026-07-18 — project not live, no compat needed)

- Adding `kind` defaults existing edges to `"control"` — no data migration needed for stored
  graphs.
- **No legacy `{{var}}` → data-edge migration is built.** The project isn't live, so there's no
  old data to be compatible with; the auto-materialize-on-load pass was cut. Connect-mode
  bindings are created fresh as explicit data edges (inspector toggle / socket drag).
- Inline `{{var}}` stays a first-class feature for **mixed** rich-text templates
  (`"总结 {{a.text}} 和 {{b.text}}"`) — those can't be a single socket. The `/` picker + chips
  + backend `interpolate` remain. Single-value bindings use data edges.

## Visual

- Control edge — thin hairline (current styling), arrow-closed marker. Condition edges keep
  their true/false labels.
- Data edge — a distinct wire: semantic-colored (later keyed by output type), thinner/curved,
  sockets on node sides. Must stay legible on the flat + frosted-glass canvas (no heavy glow).
- Reuse the already-shipped socket-dot styling (`.wf-ref-slot::before`) for input sockets.

## Staged rollout

1. **Phase 1 — data edges + input sockets.** `kind` on edges; a field in "connect" mode
   exposes an input socket; drag from an upstream output socket creates a `kind:"data"` edge
   with `target_input`; engine lowers data edges to bindings and includes them in the DAG.
   Single output socket per node for now. Control edges unchanged.
2. **Phase 2 — per-output sockets.** Split the node's right side into one socket per declared
   output; `source_output` selects which.
3. **Phase 3 — soft type hints.** Annotate outputs/inputs with data types; mark incompatible
   data-edge attempts (warn, not block); feed the readiness checklist a `type-mismatch`
   warning. (Reuses `analyze.ts`.)
4. **Phase 4 — migration/visualization.** Optionally visualize legacy `{{var}}` as data edges;
   decide coexistence vs conversion.

## Testing

- Pure functions (Vitest): DAG ordering over mixed control+data edges; input-resolution
  priority; cycle detection spanning both kinds. Extend `analyze.ts` tests.
- Backend (pytest): `validate_graph`/`topo_order` with data edges; engine lowering of a data
  edge to a binding produces the same result as the equivalent `{{var}}`.
- In-app: build `llm → export` with a data edge from `llm.text` to `export.sequence_id`; run;
  confirm identical behavior to the `{{llm-1.text}}` reference.

## Decisions (all confirmed 2026-07-18)

1. **Legacy `{{var}}` → data edges** (see Migration).
2. **Data wire only** — a data edge already implies "B waits for A"; no separate control wire
   between the same pair. Control edges are used only for pure ordering/concurrency (no data).
3. **Per-output sockets** (ComfyUI-style) — one socket per declared output on the node's right
   side; drag from the specific output. Most Open Studio nodes have 1–3 outputs, so the dots are cheap
   and make "which output" obvious at a glance.
