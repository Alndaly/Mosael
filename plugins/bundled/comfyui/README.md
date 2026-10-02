# ComfyUI

Connects a ComfyUI server (on this machine or another machine on your LAN) to Mosael. **It ships with Mosael**: once
Mosael is installed it is already on the Plugins page, so there is nothing to find in the marketplace.
One connection brings two things: **models** (every saved workflow is an image / video generation model) and **tools**
(used directly by the agent and by workflows).

## Connecting

1. Plugins page → ComfyUI → "New connection", and fill in the server URL (`http://127.0.0.1:8188` by default on this
   machine). If it sits behind a reverse proxy with login or behind ComfyUI-Login, put `user:password` (Basic) or a
   token (Bearer) into the "Access credential" credential; it is sent on both HTTP and WebSocket requests.
2. Grant `network:comfyui` and turn the connection on.
3. **Every workflow saved** in that ComfyUI shows up as a model in the model pickers of AI Studio, boards and the
   workflow "AI generate" node. A newly saved workflow appears within a minute (the host asks for the list's fingerprint
   once a minute); if you can't wait, click "Refresh models" on the Plugins page.

For several servers, create several connections; each brings its own set of models.

## How a workflow becomes a model

| In the workflow | In Mosael |
| --- | --- |
| Nodes upstream of a sampler / guider that encode a prompt (CLIPTextEncode and its Flux and SDXL variants, conditioning nodes that carry the prompt on their own `prompt` like MiniMax H3, a text node wired into one of those) | Prompt and negative prompt |
| Without a sampler ComfyUI knows (partner API nodes: MiniMax / Hailuo, Kling, Veo…; packs with their own sampler such as WanVideoWrapper): a **multiline** `prompt` / `prompt_text` / `positive_prompt` on a node wired into an output (1.6.0) | Prompt; a `negative_prompt` on the same node is the negative prompt |
| The sampler's seed, RandomNoise's noise_seed | "Seed" (random on every run when left empty) |
| Width and height of the node that creates the canvas (EmptyLatentImage, the Wan / Hunyuan video latent nodes…) | "Size" (the workflow's own size when not set) |
| The canvas node's batch_size | "Image count" (up to 4); every image is returned |
| Any other tunable literal input | An entry in the parameter form: known inputs get plain names (`labels.py`: sampler, steps, LoRA…), and only on a name clash do they carry the node title or "KSampler #2"; the common ones come first and the rest go under "Advanced"; the raw "node · input name" is in the description |
| LoadImage nodes | Reference images; in a video graph, the ones wired to `start_image` / `first_frame` / `start_frame` / `first_frame_image`… are the first frame, `end_image` / `last_frame` / `end_frame`… the last frame |
| LoadImageMask, or a LoadImage whose mask output is the only one used | Mask (`mask`) |
| LoadVideo / VHS_LoadVideo | The video to edit (`source_video`, mode `video-edit`); one wired to a **reference** input such as `ref_videos.*` is a reference video |
| LoadAudio / VHS_LoadAudioUpload | Driving audio (video graphs) / reference audio; one wired to a reference input is reference audio |
| A video output node (VHS_VideoCombine, SaveVideo…; CreateVideo only assembles frames for the next node and doesn't count) | This is a video model |

A graph with neither a prompt nor a canvas (upscaling, background removal): an image is required and the only mode is
`image-to-image`. Inputs that belong to the ComfyUI side, such as the file name prefix, are not listed.

There are two more models: **Built-in text-to-image** (when the server has at least one checkpoint) and **API template**
(when the connection config has the JSON from "Export (API)" pasted in; the `{{prompt}}` `{{negative}}` `{{seed}}`
`{{width}}` `{{height}}` `{{steps}}` placeholders work as before; this config field is `type: "json"`, so the Plugins
page gives it a code editor and validates it before saving).

## Tools

**One tool per workflow** (`wf_<id>`, "Workflow · name", see `tools/tooling.py`): the plugin reports them to the host in
`op: tools` (host capability `tools`, claimed by the same `comfyui_generation` as `generation`), and derives inputs and
outputs from that graph: the prompts, every node that loads an asset (`image_10`, `mask_11`, `video_1`…), every tunable
parameter (`steps_3`…, the same names as the generation parameters), and seed / size / image count (advanced). Outputs
follow the output nodes (`image_9`, `text_40`…), plus `asset_id` / `asset_ids` / `texts` / `summary` / `prompt_id` for
wiring workflows (declared as `wiring_outputs`: on a board only each output node's own result lands, `board_outputs`).
The name comes from the id ComfyUI writes into the workflow file (stable across renames and moves between folders),
falling back to a hash of the path; the template is `wf_api_template` and the built-in text-to-image is
`wf_builtin_txt2img`.

**A graph that is the same thing as a generation model declares `mirrors`** (1.5.0): a workflow with exactly one
**saved** output node that returns images / video / audio, no text output, and no "LoadImage alpha used as a mask" slot.
Since 1.5.2 preview nodes don't count: PreviewImage, and a video combine with `save_output` turned off, write temporary
files that a finished generation doesn't return (`graph.collect_outputs`) and that the tool doesn't return by default
either; the test is `graph.generation_nodes`, the same one generation uses to collect files, so a ControlNet graph that
"saves the result and previews the line art" is also a generation model. The tool carries
`{"generation_model": <model id>, "kind": …}` and a mapping from its inputs to the generation form (prompts, asset
roles, parameter keys like `steps_3` → `3.steps`; width and height don't map). Using that, the host keeps only the
generation entry on boards and rewrites stored tool cells into generation cells; workflows keep both. **A graph that
only returns text (tagging, prompt extraction) is not in the model catalog** (`graph.media_outputs`); it is only a tool.

There used to be a generic `run_workflow` (run by id, with a fixed table of inputs): it didn't know which graph it would
run, yet its form asked people to fill in parameters, so it was removed in 1.4.0. Every kind of graph it could run now
has its own tool above; each of those tools carries `replaces`, which the host uses to rewrite stored `run_workflow`
nodes and board tool cells (`values` keyed by node id or by node title are both accepted; cells that have no place in
the new tool are dropped and recorded in the revision notes).

The fixed ones:

| Tool | Read-only | Streaming | On by default | What it does |
| --- | --- | --- | --- | --- |
| `list_workflows` | ✓ | | ✓ | What each workflow takes (which node loads which kind of asset), what can be tuned, what it outputs, its `features` (upscale / inpaint / img2img / remove-background / …) and the tool that runs it (`tool`); workflows that can't be converted are listed too, with the reason |
| `import_outputs` | | ✓ | ✓ | Imports outputs from the history into the asset library, by task id (optionally waiting `wait_seconds`) or the most recent `last` runs. The task id is declared as `format: "external_id"`: it fetches things by their ComfyUI number rather than transforming content, so it is used in workflows and chat and not on boards |
| `server_status` | ✓ | | ✓ | Version, GPU and free VRAM, RAM, queue |
| `list_models` | ✓ | | ✓ | Model files under `/models`; on older versions without that endpoint, the loader nodes' dropdowns |
| `interrupt` | | | ✓ | Stops what is running; with a `prompt_id`, only that one |
| `clear_queue` | | | | Clears queued tasks (other people's too) |
| `free_memory` | | | | `/free`: unloads models and frees VRAM |

A workflow tool runs for at most 30 minutes per call (`timeout_seconds: 1800`) and returns **all** outputs (`artifacts`,
which the host turns into `assets` / `asset_ids`), text outputs and a per-node summary. It occupies the GPU, so it is
marked `effects: "paid"`: when the agent calls it, a confirmation card opens first, and once approved it runs in the
background without holding up that agent call. Longer jobs go through generation (6 hours, with receipts, and waiting
can resume).

## Progress, cancelling, restarts

- Progress comes from ComfyUI's WebSocket: which node is running (by its name in the interface), the sampler step and
  the node count; if the socket can't connect it falls back to polling. Newer ComfyUI's `progress_state` is understood
  too.
- When a generation task or a streaming tool is cancelled, the plugin tells ComfyUI to stop **this one** task (interrupt
  if it is running, remove it from the queue if it is waiting); other people's tasks on the same machine are left alone.
- When Mosael restarts, a generation that was running is waited on again (by task id) rather than submitted again.

## Code

`tools/` uses only the Python standard library:

- `convert.py`: saved workflow (UI graph) → the API graph `/prompt` accepts, following the semantics of the ComfyUI
  frontend's graphToPrompt: widget values ordered by the node definition (graphs saved by older frontends work too),
  muted nodes disconnected, bypassed nodes passed through, frontend-only nodes like Reroute / PrimitiveNode / Get·Set
  removed, and subgraphs expanded into "outer id:inner id";
- `graph.py`: finds prompts / seeds / sizes / slots / output nodes, describes the graph as a model, fills the graph in
  and collects outputs;
- `labels.py`: plain names for tunable inputs, their order, whether they are common, and the few that aren't tuned in
  Mosael;
- `models.py`: which models exist, which graph is behind a model id, and the list's fingerprint;
- `run.py`: uploading assets, submitting, following progress, cancelling and fetching results (shared by generation and
  the workflow tools);
- `workflows.py`: `list_workflows` / `import_outputs`, and the part that returns outputs;
- `tooling.py`: one tool per workflow: derives inputs and outputs from the graph and runs the current graph;
- `server.py`: `server_status` / `list_models` / `interrupt` / `clear_queue` / `free_memory`;
- `comfy_http.py` / `ws.py`: talking to ComfyUI.

For the protocol, see `docs/PLUGIN_MANIFEST.md` in the Mosael repository: the sections on doing generation for the host,
streaming tools, and returning several results at once.
