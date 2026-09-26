# ADR 0021: Everything that produces on the creative board goes through one Producer registry

## Status

Accepted — 2026-09-25. P0 (behaviour-preserving groundwork), P1 (the registry, a pure refactor),
P2 (tool items, 2026-09-26) and P3 (the agent, 2026-09-26) are **done**; P4 is next. **Amended
2026-09-26** (「修订:画板上只放内容变换」): the board and workflows serve different purposes, so tool
items are content transforms only; 修订 2 adds "one concept, one entry" (a plugin tool that `mirrors` a
generation model the user can use stays off the board) and `wiring_outputs` (never landed on the board); 修订 3 keeps
tools that fetch by an id from another system (`external_id` fields) off the board and stops counting ComfyUI preview
nodes as outputs when deciding `mirrors`. The "ComfyUI becomes a plugin generation provider" work (ADR 0020)
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
   `node:plugin.<package>.<tool>`, hosted by a new item kind `action`, effects from `read_only`
   (since ADR 0023: the tool's declared `effects`, the same value the agent's own plugin calls use).
3. Built-in nodes that declare `"surfaces": ["workflow", "board"]` in `NODE_TYPES`. First batch:
   transcribe_asset, translate, text_transform, json_extract, template, video_to_gif,
   separate_audio, denoise_audio, note_search, scene_render, call_workflow, http_request.
   (**Amended** — only content transforms stay on the board; see 修订 below.)

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
| **P3** agent | add_item/set_form, list_board_producers, the run_board_item card, agent/prompt.py. | **done** |
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
  `external` (http_request, call_workflow) else `none`, and for plugin tools `none` iff `read_only`
  (superseded by ADR 0023: plugin tools carry their manifest `effects`, which adds `local-code`).
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

### What P3 actually did (and where it differs from the draft)

- **Ops.** `ops.add_item` with `type: "action"` takes `producer` / `config` / `bindings` on the op itself
  and writes `form = {config, bindings, producer}` (producer last, like `_pending`). An action without
  a producer is refused (`boardErr_formNeedsTool`); a form on any other kind is refused
  (`boardErr_formOnlyOnAction`). New op `set_form` (action items only): `config` merges key by key
  (null deletes a key), `bindings` replace per field (`[]`/null unbinds), a different producer starts
  from an empty config and bindings. **Only `node:*` producers** — the built-in panels' forms
  (prompt, model, legends…) are the panel's shape; the agent writing one the panel has never seen
  would make a panel that cannot open.
- **One check, same tables.** `producers.check_forms(db, canvas, item_ids, actor_id)` runs on the
  post-ops canvas **before** normalize would silently drop detached bindings: producer exists for the
  actor (unknown plugin tools explain themselves as at run time), `kind ∈ hosts`, `NodeForm` shape,
  config keys ⊆ the tool's declared fields, `check_number_fields`, and `tools.check_bindings` —
  field declared and bindable (`binding_sink`), source on the canvas, **an edge source → item**, and
  a source kind in `_SOURCE_KINDS` (the table `board_sources` is made from). `_validate_edit_board`
  runs it on every item whose form this batch changed. At run time `resolve_bindings` stays lenient
  (a field removed by a plugin upgrade, an upstream not generated yet) — a stale form must still run;
  a form being written must be right.
- **Validators know who opens the card.** `request_confirmation(..., actor_id)` (the route passes the
  token's user) and every `ConfirmableTool.validate` takes `(db, workspace_id, payload, actor)`:
  whether a plugin tool exists is a per-person fact. Execution keeps using the approver.
- **`list_board_producers`** (read-only MCP tool) returns `GET /api/boards/producers` entries — the
  same `describe` the panel reads, so plugin tools are the caller's own — filtered to those hosted by
  `action` (built-in slots are added as empty slots, not configured by the agent).
- **`run_board_item`** (`agent/confirmable/automation.py`, payload `{board_id, item_id}`). Validate
  builds a `RunRequest` from the item **as it is on the board now** (its saved form, its position, the
  board's current revision) and calls the new `producers.dry_run` — `_admit` (look up, host, form) plus
  the producer's `preflight`, which for `node:*` is `tools.prepare_node_run`, the first half of
  `run_node_on_board` (revision/busy, bindings, number fields, the actor's own plugin connection). It
  writes the facts back (`producer`, `effects`, tool label, board name, item title, connection name) —
  always overwriting, so a caller cannot claim `effects: "none"`. Only action items with a `node:*`
  producer can be run (`confirmErr_runBoardItemNotTool`). Execute re-reads the item, refuses if its
  producer changed since the card (`confirmErr_boardItemChanged`), checks the approver's
  `producer.permission` and calls `producers.run` with the approver as actor — so the approver's own
  connection is used (decision 1). It returns `{board_id, item_id, producer, job_id}`; the job's
  receipt still goes to the item (a job has one receipt), so the agent follows it with `get_job`.
- **Cards by effect (decision 2).** `escalate`: `paid` → `ai-cost` (auto mode's streak limit applies),
  `external` → `external` (auto mode asks the human; no gate declared). **Read-only runs need no card:**
  new `ConfirmableTool.needs_card(db, payload)`; `autopilot.decide` asks it first — before "no session",
  because this is not someone's standing permission but a call that needs none — and approves with
  `decision_mode = "no-card"`. The card still exists (audit trail, and the sidecar's one waiting
  protocol stays true: the tool is `confirmation: true` and the card resolves at once); execution
  still goes through `authorize_and_approve`. The session's auto-approval trace lists these too.
- **No cost estimate.** Nothing in the codebase estimates the cost of a generation or a plugin call
  before it runs, and the only `paid` producers (the built-ins) are not agent-runnable; the card says
  "costs money" or "acts outside the app" instead of a number.
- **Prompts.** The backend system prompt, the frontend board-assistant context (zh/en) and the MCP
  docstrings of `edit_board` / `get_board` describe tool items, `set_form` and `run_board_item` briefly.

## 修订:画板上只放内容变换(2026-09-26,随 1.6.0)

P2 把「声明了 `surfaces: board` 的节点 + 这个人的全部插件工具」都放上了画板,结果画板长成了工作流:
「调用工作流」带着入参映射 JSON 和 `{{call_1.output.xxx}}` 摆在画板上,HTTP 请求、文本模板、JSON 提取、
文本处理、检索笔记也在;百度网盘的列目录 / 上传、ComfyUI 的服务器状态这种不产出内容的插件工具照样一格;
「添加」菜单照抄工作流面板的「工具 · 流程 / 工具 · AI」,格子上是写给搭流程的人的节点说明。决定 3 本来就说
流程控制不上画板,`call_workflow` 却上了 —— 缺的是一条**从注册表推出来、能审的规矩**,而不是再列一张清单。

### 两者各自是什么(判断一个功能归哪边的依据)

**工作流:「做一次,跑无数次」。** 把做过一次的事变成换个输入就能再跑、没人看着也能跑、成批地跑的东西:
可复用、带参数(开始节点的入参、模板);跨素材 / 时间线 / 字幕 / 导出 / 发布端到端出成品;循环、并发、分支
成批地做,失败说清是哪一条;定时、webhook、被智能体或别的工作流调用,不用人在场;就绪检查、每次运行每个
节点的输入输出和错误、修订和作者,可查可追。**流程本身就是产品。**

**画板:「想法摊开,边看边做」。** 把素材、文字、生成结果摊在一张桌上,看、比、改,直到一个想法成形:内容
就是界面,摆放和分组就是组织;并排试、挑一个接着做(同一句提示词三个模型、三个版本并排),发散、非线性;
一根线的意思是「参考它」(参考图、首帧、抄材料),不是「然后做它」;每一格记得自己是怎么来的(提示词、模型、
参考),能重生成、截一段、再跑,失败留着输入;评论、标记、共享画板、AI 助手一起改。**内容才是主角。**

**分界的问题:「这件事做第二次时,你是想再看着做一遍,还是想换个输入让它自己再来?」** 前者是画板,后者是
工作流。

| | 画板 | 工作流 |
| --- | --- | --- |
| 主角 | 内容 | 流程 |
| 方式 | 发散 | 收敛 |
| 人 | 在场 | 可以不在 |
| 单位 | 一格内容 | 一步 |
| 一根线 | 参考它 | 然后做它 |
| 能力边界 | 只有「内容 → 内容」的变换 | 流程控制、批量、数据、时间线、发布 |

两边**互相交接**,不共用积木:画板上的工具格跑的是同一个执行器(这份 ADR 的注册表不变),但画板只收其中
内容变换那一部分。

### 规矩(`boards/transforms.py`,内置节点和插件工具同一条)

一个节点要上画板,得是**内容变换**:

1. **不是流程或数据搬运**:分组不在 `workflows.WIRING_CATEGORIES`(流程控制、数据处理、知识库)里。按分组判,
   因为输出类型分不开 —— 模板、字符串处理的输出也是文字。
2. **交出画板摆得下的内容**:落板的输出(`board_outputs`,缺省全部)里有素材(`asset`),或**点名落板**的
   文字(写在 `board_outputs` 里、类型是 `text`)。只有类型没点名的文字不算 —— 一段转写和一行状态摘要光看
   类型分不开,得节点说「这段是成品」;没声明类型的输出(`any`)不算。
3. **吃画板上的内容,或者凭空产出素材**:至少一个字段能接上游的素材 / 文字 / 3D 场景(`binding_sink`),
   或者交出素材。凭空产出素材的留下(提示词出图的 ComfyUI 工作流、按参数出讲解视频、从对象存储取回文件)——
   画板内置的「生成」就是这种,它们做的正是往桌上放新材料;不吃内容、只交出文字的是报告(装环境、看状态),
   不留。
4. **必填的字段创作者填得了**:见下面的参数规矩。

内置节点仍要先在 `NODE_TYPES` 上声明 `surfaces: ["board"]`(和画板内置的写字 / 生成 / 念重复的、副作用大的
照旧不声明,规矩本身会放过它们);**声明了过不了规矩的由棘轮当场报出来**(`test_board_producers`),注册表
(`producers._node_producers`)也不收 —— 同一道门,不只是测试。插件工具不用声明,按清单 `node` 块的
`outputs` / `output_types` / `board_outputs` 判,每次取注册表现算(连接、ComfyUI 上的工作流会变)。

结果:内置的留下转写、翻译、视频转 GIF、分离人声、降噪、渲白模参考;撤掉调用工作流、HTTP 请求、文本模板、
JSON 提取、文本处理、检索笔记(检索笔记是查知识库、交回一串结果,不是把画板上的内容变成新内容;要把一篇
笔记放上桌,画板本来就有「文档」格)。插件里 ComfyUI 每张工作流的工具(`wf_…`)、对象存储的「取回」、网盘的
「导入」、ComfyUI 的「导入产出」、Manim / Remotion 的自定义代码动画留下;网盘的列目录 / 搜索 / 上传、对象存储
的列表 / 签链接 / 上传、ComfyUI 的状态 / 列工作流 / 列模型 / 中断 / 清队列 / 释放显存、两个「准备环境」不上。

### 参数规矩

画板上的工具格表单**只摆创作者看得懂的参数**:模型、比例、风格、时长、语言这一类。参数映射、`{{…}}` 引用、
原始 JSON、代码、节点引用一律不出现。做法是**画板那一份字段声明**(`transforms.board_config_view`,
`GET /api/boards/producers` 发的就是它,界面和智能体看到的同一份):`object` / `code` / `graph` 类型和
`data_type: json` 的字段不列;`template` 字段在画板上是 `type: "text"`(一段字,前端给普通文本框,不给引用
标签);说明里教 `{{…}}` 写法的那句不带过来。**必填**这种字段的工具在画板上填不完,规矩 4 让它不上画板
(Manim / Remotion 的「讲解视频」要一串结构化的步骤,就在工作流和对话里用)。智能体替人写表单时同一条:
画板上看不见的字段写不进去(`check_forms`)。

### 画板自己的呈现

`board_group`(按吃什么内容分:产出新素材 / 处理图片 / 视频 / 音频 / 文字 / 3D 场景 / 素材)和
`board_description`(给创作者看的一句)是注册表上的声明:内置节点写明,插件可以在 `node` 块里写,没写就按
字段(素材字段的 `media`)和输出推、取说明的第一句。「添加」菜单和拉线菜单按它分组、每行带图标,不再照抄
工作流面板的「工具 · 流程」。

### 已有数据

迁移 `migrate-board-wiring-tools-become-notes`:画布上跑那六种节点的工具格**改成一张便签**,同一个 id、位置、
大小、名字;正文写明「这一步归工作流」并附上原来的设置(模板里的字、请求地址不丢)。选便签而不是删掉:进出
它的线都还连得上,不留悬空的线;它跑出来的产出本来就是独立的格子,一格不动。插件工具的格子不迁 —— 它合不合格
随清单变,运行时由注册表说清楚:内置的回 `boardErr_nodeNotOnBoard`(「……流程控制和数据处理请在工作流里做」),
插件工具接着连接却不合格的回 `boardErr_toolNotOnBoard`,而不是叫人去插件页建连接。

### 修订 2:一个概念一个入口、只给连线用的输出不落板(2026-09-26,随 ComfyUI 插件 1.5.0)

画板审计找到两处重复。**一次运行落一堆格子**:ComfyUI 每张工作流的工具声明了 `asset_id`(和第一个输出节点
是同一个文件)、`asset_ids` / `texts`(JSON)、`summary`、`prompt_id`,却没写 `board_outputs`,按「缺省全部」
跑一次就落五格 —— 一张重复的图、一张 id 列表的 JSON 便签、一张摘要、一张任务号。**同一件事两个入口**:同一张
工作流既是图片 / 视频格里的生成模型,又是「添加」菜单里的工具格。

- **`wiring_outputs`**(节点声明,内置节点和插件 `node` 块都能写):这几个输出只给工作流连线用,画板上**从不**
  落成格子。落板的规矩只剩一条(`tools.landing_outputs`,规矩 2 也用它):点了名的(`board_outputs`)是那几个,
  没点名的是**全部不在 `wiring_outputs` 里的**;点了名又写进 `wiring_outputs` 的不落(棘轮报出来)。ComfyUI 的
  工具把那五个写进去、`board_outputs` 点每个输出节点自己的口子;棘轮对着假 ComfyUI 现报的清单钉住它
  (`test_plugin_nodes_declare_their_outputs`)。没声明类型的输出,值正好是这一轮收进素材库的文件时落成素材格
  (自定义保存节点的 `output_12`),不再是一张写着素材 id 的便签。
- **规矩 5:`mirrored_by_generation`**。插件报出的工具声明 `mirrors: {generation_model, kind}`(它和同一个插件
  目录里的某个生成模型是同一件事),而点运行的人在生成目录里用得上那个模型(`models_for_capability`,**同一条连接**
  下的)时,它不上画板 —— 画板上那件事走生成:结果落在原位、有张数、用量、6 小时、能换模型。用不上的人照旧看得到
  工具格;**工作流里两个都在**,节点面板上这个工具的说明多一句「只要图片的话,用『AI 生成素材』节点选这个模型」。
  规矩本身不查库:「用得上吗」由调用方(`producers._node_producers`)递进来。宿主不认识 ComfyUI —— 什么算同一件事
  由插件判:ComfyUI 只给**只有一个输出节点、交出图 / 视频 / 音频、没有拿 alpha 当蒙版**的工作流声明;交回几个输出
  节点、文字产出、预览临时文件、alpha 蒙版这些只有工具做得到的,工具格照旧是唯一的入口。
- **只交出文字的工作流不是生成模型**(打标签、反推提示词):`kind_of` 把它兜成 image,选了永远拿不回一张图。插件的
  模型目录跳过没有文件输出的图;它们照旧是工具,交出的字点名落板、吃的是图,按规矩归「处理图片」。

**已有数据**:画布上跑着被生成取代的工具的工具格,由对账(`rewrite-replaced-plugin-tools`,和 `replaces` 同一个
时机:每次清单刷新、每次启动 —— `mirrors` 只有插件报出清单之后才有,不是一次性迁移)改写成**那种素材的生成格**:
id、位置、名字不变,产出者 `generate`,选的就是那条连接下的那个模型。提示词原样带过去(接了上游便签 / 文档的留空,
连线还在,生成格的面板照连线填);素材字段按 `mirrors.sources` 换成素材角色(接上游的记着 `from`);参数按
`mirrors.parameters` 改名。**带不过去的**丢掉并记日志:没写进 `mirrors` 的入参(ComfyUI 的宽和高 —— 生成里是
一格「尺寸」;「也取回预览」)、选的连接、工具格的尺寸和上一轮的运行状态。在跑的那一格等它落终态再改;没选连接、
几条连接给出的模型不是同一个时不改,点运行时回 `boardErr_toolMirroredByGeneration`(说清楚去用生成),而不是
「它不交出素材」。

### 修订 3:不按另一个系统里的编号去取东西、预览不算输出节点(2026-09-26,随 ComfyUI 1.5.2、网盘 0.7.2、对象存储 1.0.2)

用户在「添加」单子里看到两个不该在的工具。

- **规矩 5:`external_id`**。「导入 ComfyUI 产出」(任务号)、网盘的「导入」(`fs_id`)、对象存储的「取回」(对象路径)
  过了规矩 3 —— 不吃内容、交出素材,被当成「凭空产出」。可它们是在**寻址另一个系统**:按编号把东西拉进来,不是把
  内容变成新内容;规矩 3 的「凭空产出」说的是按参数做出来(提示词出图、按参数出视频)。字段在声明里说清楚:
  `data_type: "external_id"`(插件写 `"format": "external_id"`,`workflows.EXTERNAL_ID`)。**必填**这种字段的,创作者
  在画板上填不出;**不吃画板内容却收**这种字段的(「导入产出」的任务号是选填,不给就取最近几次),交出的素材也是从
  外面取回来的 —— 两种都不上画板,工作流和智能体照常用。这种字段不接上游格子、不在画板表单上出现。上面「结果」里
  留下的「取回」「导入」「导入产出」据此撤掉。对象存储的对象路径虽然人读得懂(`videos/a.mp4`),也按这条判:它是
  对象在桶里的身份,工具做的是按地址导入;把文件放上画板走素材库和拖放。同一句声明也是选择器棘轮的归类:名字以
  `_id` 结尾的字段要么是工作区里的一种实体(给选择器),要么声明成外部编号(`test_entity_fields_have_a_picker`,
  插件清单一起查)。
- **`mirrors` 不数预览节点**。ComfyUI 的判据是「只有一个输出节点」,把「保存 + 看一眼线稿的 PreviewImage」的 ControlNet
  图数成两个,于是不声明 `mirrors`,同一张图在画板上两个入口。预览写的是临时文件:生成跑完不交回(`collect_outputs`),
  工具缺省也不交回。现在判据只数生成会交回的那几个(`graph.generation_nodes`:这一种里存下来的,一个都不存才是预览),
  和 `collect_outputs` 同一条;别的种类里存下来的文件、文字产出照旧说明「只有工具交得全」。

**已有数据**:两者都是对账,不是一次性迁移 —— 合不合格读的是插件此刻的清单,插件升级可能在任何一次启动之后。
被生成取代的照旧由 `rewrite_mirrored_tools` 改写成生成格;按编号取东西的由 `retire_external_id_tools` 改成便签,
做法和 `migrate-board-wiring-tools-become-notes` 一样(同一个 id、位置、名字,正文写明归工作流、附原来的设置)。
只改连接说得出、而且每条连接都说它按编号取东西的格子;还没改到的,点运行时回 `boardErr_toolFetchesByExternalId`。

### 修订 4:3D 场景格自己渲白模,「渲染白模参考」工具格撤下画板(2026-09-26)

「一个概念一个入口」的又一处:画板上渲白模要**两格** —— 一格场景格(引用场景、放缩略图),旁边一格工具格
(`node:scene_render`,在上面再挑一遍场景、挑镜头、挑渲什么)。两格是同一件事的两半,连线也只是把场景 id 递过去。

- **渲染是场景格自己会做的事**:内置产出者 `scene_render`,`hosts=("scene",)`,和「剪一段」挂在视频 / 音频格上
  同一个样子。表单是 `{config: {shot_id, render, project_id}}` —— 字段**就是工作流节点声明的那三个**(说明、选项来源、
  `sole_option_default` 读同一份,`render` 在画板上去掉 `allow_custom`),场景由宿主那一格给。跑的是**同一个执行器**,
  走工具格那条路(`tools.run_node_on_board`:`board_run` 任务、计量、取消、归属都一样);产出按 `landing: derived`
  新建在场景格右边、连线(`producer_ids.DERIVED_BUILTINS` / `derives_outputs` —— 宿主的 `asset_id` 是缩略图,
  摆占位、回执、保存都不动它)。`effects: none`(本机渲染);存在格子上的表单就是运行那一份(`runs_from_draft`),
  智能体能 `set_form`、`run_board_item`。新放下的场景格挂它(`SLOT_PRODUCERS["scene"]`)。
- 节点 `scene_render` 撤掉 `surfaces: board`(和 `board_outputs` / `board_group` / `board_description`),工作流里不变。
- **已有数据**:迁移 `migrate-board-scene-cells-render-themselves` —— 每一格场景格写明产出者;工具格接着(绑定且线在)
  或填的是板上某一格场景格的场景时,设置搬进那一格的 `form.config`、工具格删掉,连向产出的线改从场景格连出(同一对不重复);
  其余(或同一格场景已经收了另一套设置的)照 `migrate-board-wiring-tools-become-notes` 改成便签。改到的板版本号 +1。

### 下一版

- 「从画板沉淀为工作流」:一串在画板上验证过的变换,存成一张工作流;
- 「把工作流结果送到画板挑选」:工作流批量出的几版落到一张画板上并排比;
- 内容优先的操作:选中一格内容,就地列出能用在它身上的变换(规矩已经给出「吃什么内容」,`board_group` 就是
  这个入口的索引)。

把这份定位落进数据模型的结构改动(做法与版本、内置产出者的端口和服务端取值、落点与来历线、每种格子的字段表)
见 [ADR 0025](0025-board-recipes-versions-and-ports.md)。

## Alternatives rejected

- **A. Only make plugins generation providers.** Non-generation plugins would still be unusable on
  the board.
- **B. A mini-workflow embedded in an item.** Breaks the one-item-one-job invariant.
- **C. A "run workflow" item.** Comes for free as `call_workflow` in the registry. (After the 修订
  this no longer holds: `call_workflow` is flow control and is off the board; the hand-off between
  board and workflow is the next version's "save a board as a workflow" / "send workflow results to a
  board".)
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
