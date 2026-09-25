# ADR 0021: Everything that produces on the creative board goes through one Producer registry

## Status

Accepted — 2026-09-25. P0 (behaviour-preserving groundwork), P1 (the registry, a pure refactor) and
P2 (tool items, 2026-09-26) are **done**; P3–P4 are next. The "ComfyUI becomes a plugin generation provider" work (ADR 0020)
landed before P1, so board generation already sees plugin models as ordinary provider models.

## Context

The creative board (创意画板) cannot use plugins, while workflows can. The reason is structural:
everything on a board that *produces* something is one of four hard-wired paths — generate, speak,
trim, write. Each has its own route (`api/routes/boards.py` generate/write/speak/trim), its own
domain function (`domain/boards/actions.py` `*_on_board`) and its own panel (four conditional
blocks in `BoardCanvas.tsx`); which panel an item gets is guessed from its kind by
`boardItemState.composerFor`. Workflows instead have two registries — metadata (`NODE_TYPES` +
`plugin_node_types`) and behaviour (`executors.get_executor` plus prefix executors) — and every
plugin tool is automatically a first-class node there.

What workflows can do and the board cannot:

| capability | workflow | board |
| --- | --- | --- |
| plugin tools | `plugin.<package>.<tool>` nodes (`plugins/nodes.node_meta`, `executors/content.plugin_node` → `tools.invoke`) | none — `canvas.ITEM_KINDS` is fixed, `composerFor` knows note/image/video/audio only |
| generation providers | yes | partly — the submit hard-casts kind to `image`\|`video`, the audio slot always speaks |
| file outputs (`artifact`) | collected into the asset library | — |
| cancellation | cancel cascades to child jobs | no stop button |

Along the way we found problems that exist today, independent of the board:

- `_config_from_schema` ignored `"format": "asset"`, so an asset field not literally named
  `asset_id` got a free-text box instead of the asset picker in workflows too.
- Plugin processes were never registered with `register_job_child`: cancelling a workflow flipped a
  row while the plugin kept running until it finished or timed out. There was no admission limit
  either — a loop × parallel branches could start dozens of plugin interpreters.
- Executors were typed `(db, workflow: Workflow, config)` but read only `workspace_id` (34 places),
  `id` (6) and `name` (1); who runs them already comes from `current_actor(db)`. The signature was
  wider than the use, which is what tied nodes to workflows.
- The field renderer (`renderField`, `dynamicOptions`, basic/advanced split, field activation) lived
  inside `WorkflowsView.tsx::NodeInspector`; the node-type description (label translation and
  category ordering) lived inside a route handler; instance resolution lived inside an executor.
  None of them could be reused by a second host.

## Decision

Collect the board's producers into **one Producer registry** — a new module `producers` in the
boards domain (`domain/boards/producers.py`, created in P1):

```python
@dataclass(frozen=True)
class Producer:
    id: str                    # "generate" | "speak" | "trim" | "write" | "node:<node_type>"
    hosts: tuple[str, ...]     # which item kinds it can sit on
    permission: str            # the ensure_workspace_perm operation
    effects: str               # "none" | "paid" | "external" — does the agent need a confirmation card
    meta: Callable[[Session, str | None], dict]   # same shape as a NODE_TYPES entry
    start: Callable[[Session, RunRequest], Board] # create job → place pending → start job
```

Sources:

1. The four existing actions become built-in producers wrapping today's `*_on_board`; the hosts of
   `generate` are derived from the kinds the generation catalog actually offers.
2. Every non-internal plugin tool from `available_node_types(db, user_id)` becomes
   `node:plugin.<package>.<tool>`, hosted by a new item kind `action`, effects from `read_only`.
3. Built-in nodes that declare `"surfaces": ["workflow", "board"]` in `NODE_TYPES`. First batch:
   transcribe_asset, translate, text_transform, json_extract, template, video_to_gif,
   separate_audio, denoise_audio, note_search, scene_render, call_workflow, http_request.

A `node:*` producer creates a `board_run` job (payload carries `receipt_to_item`), places the
pending item, and dispatches through `jobs.dispatch_job` (so the parent job and `current_actor`
hold). The thread calls `get_executor(node_type)(db, BoardScope(workspace_id, id=f"board:{board_id}", name), config)`
and writes the result into `job.result` through `board_outputs()`. `write` stays synchronous
(`run_job_inline`).

**Landing.** On a media/note slot (image/video/audio/note hosts) the first output of a matching
type fills the host and the rest line up to the right (today's `_canvas_with_delivered_result`).
On an `action` host every output becomes a new item connected by an edge; re-running never
overwrites earlier outputs. `deliver_generated` first normalises through a single `outputs_of(job)`
into `[{"type":"asset","asset_id"},{"type":"text","text"},{"type":"json","value"}]`.

**Upstream → inputs.** Types reuse `config_data_type` / `output_data_type`, extended with
`("scene_id", "scene")` and `format: asset → data_type: asset`. note → text (`item.text`);
document → text (`notes.read_reference`); image/video/audio → asset; scene → scene; an action is
never a source. Bindings are `form.bindings = {field: [{"from": item_id}]}`; `_drop_detached_sources`
generalises to `_drop_detached_bindings` (one place in normalize). Values are read from the canvas
by the server at run time; several notes join in edge order with `\n\n`; a required field binds the
first type-compatible upstream by default, changeable and persisted.

**Outputs → items.** `board_outputs(meta, output)` dispatches by declared `outputs` /
`output_types`: assets by `Asset.kind` → image/video/audio, other files → a note naming the asset;
text/number → note; json → note with `text_format: "json"`; lists → several items. Only an
undeclared single `output` is sniffed. At most 12 derived items per run; the rest merge into one
JSON note.

**Run state, cancel, concurrency.** Reuse run/_ensure_slot_ready/_merge_into_latest/
_keep_server_owned_state (the `kind == "note"` special case generalises to "this producer's
in-place output is text"). A stop button calls `cancel_job`. Plugin processes spawned inside a job
are registered as that job's children; MCP calls cannot be interrupted, only their result dropped.
`jobs.PLUGIN_SLOTS` limits concurrent plugin calls. `BoardUpdate.base_revision` becomes required.

**Permission and ownership.** The route checks `ensure_workspace_perm(user, ws, producer.permission)`.
`form.config.instance_id` is used only if it belongs to the person running it; otherwise that
person's own instance is resolved — shared through `plugins/nodes.resolve_instance(db, package,
tool, chosen, actor)`. The panel says "will run with your connection 「X」"; without one it links to
the plugins page. Internal tools never enter the registry and are refused again at run time.
Normalize only checks the producer string's format, not whether the plugin is available (a board
must still open and save after a plugin is removed).

**Agent.** `boards/ops.py`: `add_item` accepts kind `action` with a form (producer/config/bindings);
new `set_form`; `_validate_edit_board` dry-runs that the producer exists. New read-only
`list_board_producers`; confirmable `run_board_item` (`agent/confirmable/automation.py`) — a card
when effects ≠ none, read-only plugins run directly.

**Data, migration, API, frontend.** Item: `{"kind":"action","form":{"producer":"node:plugin…",
"config":{…,"instance_id":…},"bindings":{…}},"run":{…}}`; derived notes may carry
`text_format:"json"`. `_normalize_form` validates producer against
`^(generate|speak|trim|write|node:[\w.\-]+)$` (P1 accepts the four built-in names; P2 adds the
`node:` form), config as an object, and the bindings shape;
`DEFAULT_SIZE` gains `action` (both ends). Migration `_migrate_board_forms_name_their_producer`:
form.trim → trim; note → write; audio → speak; image/video → generate; idempotent, in the upgrade
fixture; afterwards `composerFor` inference is deleted. API: `GET /api/boards/producers?workspace_id=`
(WorkflowNodeTypeOut + id/hosts/permission/effects, described by the shared
`describe_node_types(...)`); field options keep using `GET /api/workflows/field-options`;
`POST /api/boards/{id}/run` `{workspace_id, base_revision, item_id, x, y, kind, producer, form}`;
the four old routes and BoardGenerate/BoardWrite/BoardSpeak/BoardTrim are deleted (ADR 0006 — no
old names kept). Frontend: `features/nodeForms/NodeConfigForm.tsx` shared with the workflow
inspector; new `features/boards/ActionComposer.tsx` (template fields show upstream binding chips,
filtered by data_type); `composerFor` → `producerOf(item)`, the four conditional blocks →
a `BUILTIN_COMPOSERS` map, `node:*` falls to ActionComposer; `boardNodes.tsx` gains ActionNode
(label, plugin badge, run state, stop); toolbar and pull-to-create menu gain a "Tools" group from
the shared node-picker grouping; `api/domains/boards.ts` gains runOnBoard/listBoardProducers and
loses the four old functions.

### Decisions confirmed by the owner

1. On a shared board, whoever presses Run uses **their own** plugin connection; if they have none,
   the board tells them to create one.
2. A person pressing Run never gets a confirmation card. When the agent runs something for them,
   paid or externally-effectful producers need a card; read-only ones run directly.
3. Not on the board for now: `llm` / `ai_generate` / `synthesize_speech` (duplicates of the
   built-in write/generate/speak), `timeline_*` / `publish` (large side effects), and flow control
   (start/output/condition/subgraph/loop/code/delay).
4. Existing board data is **migrated** to name its producer. **No compatibility read path** is kept:
   the design draft's "old shapes read compatibly at the boundary" is replaced by migrating old
   `job.result` shapes and canvas forms to the new shape — or by showing that an old shape only
   lives in short-lived data and saying so.
5. Order: P0 now (it does not touch the generation path); P1–P3 after the ComfyUI plugin work lands.

## Phases

| phase | scope | state |
| --- | --- | --- |
| **P0** groundwork (behaviour unchanged) | ① `format: asset` → `data_type: "asset"`; `scene_id` → `scene` in the naming table. ② Executors take a `RunScope` protocol (workspace_id, id, name); a ratchet keeps them to those three. ③ Plugin processes registered as job children; `PLUGIN_SLOTS`. ④ Extract `NodeConfigForm`, the node-picker grouping, `describe_node_types`, `resolve_instance`. | **done** |
| **P1** registry (pure refactor) | `producers.py` with the four built-ins, `/run`, the migration, `outputs_of`; frontend switches to runOnBoard/producerOf; old routes and schemas deleted; test_boards.py / test_board_receipts_and_copies.py go through `/run` with unchanged assertions. | **done** |
| **P2** tool items | `node:*` producers, `surfaces`, the `action` kind, bindings and detaching, derived outputs; ActionComposer, ActionNode, stop button, tool picker; `generate` hosts from the generation catalog (meets the ComfyUI work). | **done** |
| P3 agent | add_item/set_form, list_board_producers, the run_board_item card, agent/prompt.py. | — |
| P4 extras | `node:*` on media slots with in-place output (manifest node block declares `board.primary_output`); multi-file plugin outputs; PLUGIN_MANIFEST "how it looks on a board". | — |

### What P0 actually did (and where it differs from the draft)

- `RunScope` lives in `workflows/executors/__init__.py`; the engine passes the `Workflow` itself,
  which satisfies it. Executor parameters are renamed `workflow` → `scope`. Ratchet:
  `tests/test_executors_only_read_run_scope.py`.
- Cancellation: `core/child_process.run_logged` gained `on_child` (the one door for external
  commands stays one door). The job child registry now holds **several children per job** —
  parallel plugin nodes all belong to the one workflow job — with `detach_job_child` removing one.
  A process killed by cancellation reports `pluginErr_cancelled`, not "exit code -9".
- `PLUGIN_SLOTS = 4` is taken in `plugins/tools.invoke` around both transports (process and MCP),
  after committing so the waiting thread does not hold a pooled connection.
- `resolve_instance` raises `PluginDomainError`; the three messages moved from `wfErr_plugin*` to
  `pluginErr_{instanceGone,noInstance,manyInstances}` and no longer say "on the node", because two
  hosts share them. The workflow executor relays them with `WorkflowDomainError.from_error`.
- `describe_node_types(registry, locale)` lives in `domain/workflows/node_catalog.py`, together
  with the helpers it needs (`with_data_type`, `translated_spec`, `option_label`).
- Frontend: `features/nodeForms/NodeConfigForm.tsx` exports `nodeConfigTiers`,
  `useNodeFieldOptions`, `NodeConfigForm` and a `FieldBinding` seam (the workflow's binding is data
  edges; the board's will be upstream items). `features/nodeForms/nodePicker.ts` holds the picker
  grouping. The `nodeInspectorIsNodeAgnostic` ratchet now reads the form and also forbids the
  inspector from growing its own renderer again.
- Not in the draft: to keep `featureBoundaries` acyclic (nodeForms must not import workflows), the
  field-level parts the form uses moved with it — `fieldActivation`, `RefEditor` + `refDoc`,
  `MapField`, `ScenePropsField`, and the soft data types (`DataType` / `fieldDataType` /
  `normalizeDataType`, now `nodeForms/fieldTypes.ts`). Workflows import them from there.
- `scene` is only added on the input side; the frontend treats unknown data types as `any`, so no
  current connection check changes.

### What P1 actually did (and where it differs from the draft)

- **Registry.** `domain/boards/producers.py`: `Producer(id, hosts, permission, effects, form, start,
  failures, failure_status)` and `RunRequest(workspace_id, board_id, item_id, kind, x, y,
  base_revision, actor_id, producer, form)`; `run(db, request)` is the one entry — it looks the
  producer up (unknown → `boardErr_unknownProducer`, 400), checks `kind ∈ hosts`
  (`boardErr_producerCannotHost`, 400), validates the form with the producer's pydantic model
  (`allow_inf_nan=False`, like `ApiModel`), then starts it. The four built-ins wrap the existing
  `actions.*_on_board`; `generate` edit/paid, `write` ai/paid, `speak` edit/paid, `trim` edit/none.
  The registry is rebuilt per call (four cheap entries; no process state). **`meta` is not in P1** —
  nothing consumes it until `GET /api/boards/producers` arrives with P2.
- **`generate` hosts** come from the generation catalog's kinds (`generation/resolution.KINDS`),
  which today is `("image", "video")`. An audio slot **cannot** pick `generate` yet: the catalog
  (and `plugin_connections.GENERATION_KINDS`) deliberately keeps plugin audio models out of the
  pickers until the host has an audio generation path. That needs new host code and UI, so it moves
  to P2 as planned rather than falling out of P1.
- **Errors keep their status codes.** A producer's own domain errors are relayed as
  `ProducerFailed` with the key and params intact and the status the producer declares
  (`GenerationDomainError`/`TrimError` 400, `AiChatError`/`VoiceError` 422 — as the four routes
  answered). A form that does not fit is re-raised by the route as a `RequestValidationError`
  (422, `loc: ["body", "form", …]`), so NaN in `form.start` still fails at the door with the
  readable 422 of `test_api_refuses_non_finite_numbers`.
- **`/run` requires `base_revision` too** (not only `BoardUpdate`): the check has to happen before
  money is spent, and the frontend always sent it. The rate limiter now treats `/boards/{id}/run`
  as billable, which includes trim (the old `/trim` route was not in the list).
- **Result shapes (owner decision 4).** `canvas.outputs_of(job)` is the only reader of `job.result`
  for the board and normalises to `[{"type":"asset","asset_id"}, {"type":"text","text"}]`. There
  is **no legacy shape to migrate**: `asset_ids` (generation), `asset_id` (speech, trim) and `text`
  (board write) are the three job kinds' *current* result contracts, and the receipt reads
  `job.result` exactly once, at the terminal transition (or, for a job the same request just
  created, in `_deliver_if_already_settled`) — a stored result is never re-read later. So no
  compatibility branch and no data migration are needed for results.
- **Migration `migrate-board-forms-name-their-producer`.** Mirrors the old `composerFor` exactly:
  items with a form get `form.producer` (note → write; `form.trim` → trim; audio → speak;
  image/video → generate); items with **no** form that used to get a panel — every note, and
  image/video/audio slots without an asset — get `{"producer": …}`, otherwise they would lose
  their panel. Items already naming a producer are left alone (idempotent). `producer` goes last in
  the form. Boards it changes get `revision + 1`, so a client still holding a pre-upgrade snapshot
  gets a 409 and reloads instead of saving forms without producers over the migrated ones.
- **Who writes `form.producer` from now on.** `actions._pending` writes the running producer last
  (overriding whatever the caller sent); the frontend stamps new empty slots at creation
  (`boardItemState.newSlotForm`, used by `add()` and double-click); the agent's `ops.add_item` does
  the same through `producers.producer_for_new_slot`. `normalize_canvas` only checks the name
  (`boards/producer_ids.py` — a dependency-free table, because canvas → producers → actions →
  canvas would otherwise be an import cycle) and does not require a producer.
- **Frontend.** `api/domains/boards.ts` has `runOnBoard` + `BoardRunRequest`/`BoardRunForms`
  (kept by hand: `form` is a bare dict in OpenAPI; recorded in `domainShadows.test.ts`).
  `boardItemState.producerOf(item)` reads `form.producer` (no producer, or an asset already there →
  no panel). The four conditional blocks became `features/boards/boardComposers.tsx`
  `BUILTIN_COMPOSERS` (producer → panel); `BoardCanvas` takes one `onRun` instead of
  onGenerate/onWrite/onSpeak/onTrim. Panels never see or edit the producer: `composerView` hides
  it, `withProducer` puts it back (last) when a panel saves its form — so a panel does not rewrite
  its form merely by opening. `BoardsView.run` is the one submit path: write keeps the synchronous
  `runNoteWrite` lifecycle; the others share one settlement (patch the local item with the server's
  form/run/asset, or add it when it is a new item) and failure toasts per producer.
- **Agent / MCP.** Nothing called the four routes or `*_on_board` (the MCP server only reads boards;
  the agent edits boards through `ops`), so there was nothing to reroute. Tests that called
  `generate_on_board`/`write_on_board` directly now go through `producers.run`.

### What P2 actually did (and where it differs from the draft)

- **Registry.** `producers.list_producers(db, actor_id)` / `get_producer(db, producer_id, actor_id)`
  now take the session and the person running: the registry is the four built-ins plus
  `_node_producers` — built-in nodes whose `NODE_TYPES` entry declares `"surfaces": ["workflow", "board"]`
  (the twelve of the first batch; ratchet in `test_board_producers.py`: declarations, registry and
  executors agree, and the kept-off nodes of decision 3 stay off) and the actor's own non-internal
  plugin tools (`plugins.tools.exposed(db, actor)`; none when there is no actor). All `node:*` have
  `hosts=("action",)`, `permission="edit"`; effects are `external` for built-ins declared
  `external` (http_request, call_workflow) else `none`, and for plugin tools `none` iff `read_only`.
  `Producer` gained `meta` (a `NODE_TYPES`-shaped entry; the built-ins have a label + description
  only) and `fills_empty_slot`. An unknown `node:plugin.*` explains itself: `boardErr_toolInternal`
  for an internal tool, otherwise `boardErr_pluginNotConnected` naming the plugin and the tool.
- **Run.** `boards/tools.py` (new): `run_node_on_board` checks revision/busy, **resolves bindings,
  checks number fields and resolves the plugin connection before creating the job** — a missing
  connection, a non-number in a number field or an unreadable document is a 400, not a failed job.
  Then `board_run` job (receipt to the item) → pending → `dispatch_job`; the thread takes
  `NODE_CONNECTIONS` then a session (same order as the engine, so `wait_for_job(release=db)` stays
  balanced) and runs `get_executor(node_type)(db, BoardScope(ws, "board:<id>", name), config)` inside
  `run_job_inline`. `form.config.instance_id` counts only if it is one of the runner's own
  connections; otherwise it is treated as unchosen (auto-pick the only one) rather than reported as
  "gone". The form keeps what the user saved (bindings, the owner's choice), not the resolved values.
  New job kind `board_run` (announce always; affects boards, assets).
- **Bindings.** Values are read by the server at run time in **edge order**; text fields join
  with `\n\n`, `*asset_ids` fields take a list, other asset/scene fields take the first. Which item
  kinds fit a field is decided **once, on the server** (`tools.binding_sink` / `bindable_kinds`) and
  sent to the UI as `board_sources` on every field in `GET /api/boards/producers` — the frontend
  does not keep its own table. The default binding (required field → first fitting upstream) is set
  by the panel and persisted; the server resolves only what is saved. `_drop_detached_sources`
  became `_drop_detached_bindings` and also drops binding refs whose edge is gone or whose source is
  an action; a field with no refs left is removed. `form.config` must be an object that serialises
  without NaN/Infinity.
- **Outputs.** `tools.board_outputs(meta, output)` → `[{"type": "asset"|"text"|"json", …}]` in
  `job.result["outputs"]`, the fourth current result contract read by `canvas.outputs_of` (still no
  legacy shape). **Not in the draft: `board_outputs`** — a `NODE_TYPES` entry (and a plugin's `node`
  block) may name which outputs land on the board; half of what a node returns exists for wiring
  (counts, status codes, engine names) and `video_to_gif` would otherwise re-place its own input.
  The receipt looks up asset kinds and names (this workspace only) and `_derive` places a new column
  right of the action and of its earlier outputs, top-down, each connected by an edge; at most 12,
  the rest merged into one JSON note. Derived notes carry `form.producer = "write"` (like a
  hand-placed note) and JSON notes `text_format: "json"` (notes only). Derived items get no title —
  a title is user data and would freeze the runner's language. On an action, success with nothing
  landable is still success; failure/cancel keep the form and the reason.
- **Import layering.** `DEFAULT_SIZE` moved from `ops` to `canvas` (the receipt places items;
  `ops` re-imports it) and the note producer name is `producer_ids.NOTE_PRODUCER`, so `canvas`
  never reaches back to `ops`/`producers`/`tools` (the no-lazy-cycles ratchet).
- **Plugin nodes.** A plugin's own `node.config` entry with `"format": "asset"` now gets
  `data_type: "asset"`, like the schema-derived one (P0 fixed only the latter).
- **`generate` on audio.** The generation catalog (`resolution.KINDS`) still has no audio, so the
  hosts are unchanged. The UI is ready for it: an empty slot whose kind is hosted by more than one
  `fills_empty_slot` producer gets a switch in its action bar (audio: speak / generate), and the
  board's model list is fetched per kind in `generate.hosts` — both derived from the registry.
  `NodeComposer` has not been exercised on an audio slot yet.
- **Frontend.** `features/boards/ActionComposer.tsx` renders `NodeConfigForm` with the board's
  `FieldBinding` (upstream chips filtered by `board_sources`; the form gained an optional
  `canBind` seam), a connection hint ("runs with your connection X" / no connection → link to
  `#/plugins`), Run / Run again. `boardNodes` `ActionNode`: tool name as the label fallback, source
  badge (plugin name / built-in), shimmer + job progress + Stop (→ `cancel_job`), failure reason,
  "unavailable" when the tool is not in the person's list. `boardComposers.renderComposer` maps
  `node:*` to the action panel. Tools appear in the toolbar Add menu and in the pull-to-create menu
  (which gained group headers and a search box) with `nodePicker` grouping. `prunedSourcesPatch`
  became `prunedLinksPatch` (sources and bindings). The `nodeInspectorIsNodeAgnostic` ratchet now
  covers the action panel too.
- **Not in P2.** The agent side (P3): `ops.add_item` accepts kind `action` (it is in `ITEM_KINDS`)
  but cannot set a form yet. The `_keep_server_owned_state` "in-place output is text" generalisation
  was not needed (actions derive; they have no in-place output).

## Alternatives rejected

- **A. Only make plugins generation providers.** Non-generation plugins would still be unusable on
  the board.
- **B. A mini-workflow embedded in an item.** Breaks the one-item-one-job invariant.
- **C. A "run workflow" item.** Comes for free as `call_workflow` in the registry.
- **D. A board-only plugin-tool item.** Yet another dedicated route — the thing this ADR removes.

## Consequences

- One route, one domain entry and one composer mapping replace four of each; a new capability on
  the board is a registry entry, and every plugin tool arrives without board-specific code.
- The workflow inspector and the board share one form and one node description, so a field, label
  or ordering cannot drift between them.
- Cancelling a job now actually stops process plugins, in workflows today and on the board later.
  MCP plugins still run to completion after a cancel; their result is discarded.
- Risks carried into P1–P2: executors that depend on the workflow job context
  (`wait_for_job(release=db)`, `current_actor`) must run inside `dispatch_job` threads and are tested
  node by node; undeclared plugin outputs are sniffed into JSON notes (capped; docs encourage
  `output_types`); stale snapshots overwriting derived items (hence required `base_revision`);
  `NODE_TYPES` labels are i18n keys, so `describe_node_types` must be shared; merge order with the
  ComfyUI work.
