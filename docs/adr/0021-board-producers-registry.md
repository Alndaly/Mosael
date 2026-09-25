# ADR 0021: Everything that produces on the creative board goes through one Producer registry

## Status

Accepted — 2026-09-25. Phase P0 (behaviour-preserving groundwork) is **in progress**; P1–P4 wait
for the concurrent "ComfyUI becomes a plugin generation provider" work (ADR 0020, on its own
branch) to merge.

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
boards domain (created in P1; it does not exist yet):

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
`^(generate|speak|trim|write|node:[\w.\-]+)$`, config as an object, and the bindings shape;
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
| **P0** groundwork (behaviour unchanged) | ① `format: asset` → `data_type: "asset"`; `scene_id` → `scene` in the naming table. ② Executors take a `RunScope` protocol (workspace_id, id, name); a ratchet keeps them to those three. ③ Plugin processes registered as job children; `PLUGIN_SLOTS`. ④ Extract `NodeConfigForm`, the node-picker grouping, `describe_node_types`, `resolve_instance`. | **in progress** |
| P1 registry (pure refactor) | `producers.py` with the four built-ins, `/run`, the migration, `outputs_of`; frontend switches to runOnBoard/producerOf; old routes and schemas deleted; test_boards.py / test_board_receipts_and_copies.py go through `/run` with unchanged assertions. | waiting on ADR 0020 |
| P2 tool items | `node:*` producers, `surfaces`, the `action` kind, bindings and detaching, derived outputs; ActionComposer, ActionNode, stop button, tool picker; `generate` hosts from the generation catalog (meets the ComfyUI work). | — |
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
