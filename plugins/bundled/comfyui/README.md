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
| The canvas node's batch_size | "Image count" (up to 4, 1 when not set); every image is returned |
| The save nodes of that kind (the preview nodes when nothing is saved) | How many files one run returns (`outputs_per_run` = the node count, × the image count), so the host lays out that many placeholders up front; with more than one, the parameters get a "Results from" choice (node titles, "All" by default): pick one to get only its output, and the other save nodes don't run (1.6.0) |
| Any other tunable literal input | An entry in the parameter form: known inputs get plain names (`labels.py`: sampler, steps, LoRA…), and only on a name clash do they carry the node title or "KSampler #2"; the common ones come first and the rest go under "Advanced"; the raw "node · input name" is in the description |
| LoadImage nodes | Reference images; in a video graph, the ones wired to `start_image` / `first_frame` / `start_frame` / `first_frame_image`… are the first frame, `end_image` / `last_frame` / `end_frame`… the last frame (also when the image is resized or cropped first; an image-to-video graph's first frame is required, 1.6.1) |
| LoadImageMask, or a LoadImage whose mask output is the only one used | Mask (`mask`) |
| LoadVideo / VHS_LoadVideo | The video to edit (`source_video`, mode `video-edit`); one wired to a **reference** input such as `ref_videos.*` is a reference video |
| LoadAudio / VHS_LoadAudioUpload | Driving audio (video graphs) / reference audio; one wired to a reference input is reference audio |
| A video output node (VHS_VideoCombine, SaveVideo…; CreateVideo only assembles frames for the next node and doesn't count) | This is a video model |

A graph with neither a prompt nor a canvas (upscaling, background removal): an image is required and the only mode is
`image-to-image`. Inputs that belong to the ComfyUI side, such as the file name prefix, are not listed.

Only the part of the graph ComfyUI **actually runs** counts (1.6.1): the output nodes that can run and everything
upstream of them. A dangling canvas node is not a "size" or "images" control, a loader whose downstream is all bypassed
is not an input, and a preview cut off by a muted node upstream is not counted in "outputs per run"; frontend-only
virtual nodes such as rgthree's Relay / Repeater are left out.

**A preview that only shows a preprocessor result is not an output** (1.7.0): when the graph has a decoder (a class name
containing `Decode`: VAEDecode, VAEDecodeTiled, WanVideoDecode…, i.e. the graph generates something) and a PreviewImage /
PreviewAudio has no decoder anywhere upstream, it is looking at an image a LoadImage read, or at what a preprocessor
(OpenPose skeleton, Canny lineart, depth map) computed from it; sampling played no part. It is not an output and doesn't
run, and the preprocessing branch feeding only it (with its loader) drops out too. Only the wiring decides, never node
titles; a graph with no decoder at all (upscaling, background removal, partner API nodes) keeps its previews.

There are two more models: **Built-in text-to-image** (when the server has at least one checkpoint) and **API template**
(when the connection config has the JSON from "Export (API)" pasted in; the `{{prompt}}` `{{negative}}` `{{seed}}`
`{{width}}` `{{height}}` `{{steps}}` placeholders work as before; this config field is `type: "json"`, so the Plugins
page gives it a code editor and validates it before saving).

## Tools

**One tool per workflow** (`wf_<id>`, "Workflow · name", see `tools/tooling.py`): the plugin reports them to the host in
`op: tools` (host capability `tools`, claimed by the same `comfyui_generation` as `generation`), and derives inputs and
outputs from that graph: the prompts, every node that loads an asset (`image_10`, `mask_11`, `video_1`…), every tunable
parameter (`steps_3`…, the same names as the generation parameters), and seed / size / image count (advanced; the image count defaults to 1, as in generation, 1.7.0). Outputs
follow the output nodes (`image_9`, `text_40`…), plus `asset_id` / `asset_ids` / `texts` / `summary` / `prompt_id` for
wiring workflows (declared as `wiring_outputs`: on a board only each output node's own result lands, `board_outputs`).
The name comes from the id ComfyUI writes into the workflow file (stable across renames and moves between folders),
falling back to a hash of the path; the template is `wf_api_template` and the built-in text-to-image is
`wf_builtin_txt2img`.

**A graph that is the same thing as a generation model declares `mirrors`**: the tool of every workflow in the model
catalog (one that returns files, `graph.media_outputs`) carries `{"generation_model": <model id>, "kind": …}` and a
mapping from its inputs to the generation form (prompts, asset roles, the alpha mask → `mask`, parameter keys like
`steps_3` → `3.steps`; width and height don't map). Using that, the host keeps only the generation entry on boards (the
model picker of image / video cells): the "…" menu no longer lists "Workflow · name", and stored tool cells are rewritten
into generation cells; workflows and the agent keep the tool (what it does on top — returning every output node, text
shown by a node, previews — stays there). Since 1.6.0 graphs with several save nodes (generation has "Results from") and
graphs that use LoadImage's alpha as a mask (the model has a mask slot) declare it too; 1.5.x only declared it for "one
saved output node, no text, no alpha mask", so a graph with two save nodes had two entries on boards. **A graph that only
returns text (tagging, prompt extraction) is not in the model catalog**; it is only a tool and stays an ability of a
cell on boards.

There used to be a generic `run_workflow` (run by id, with a fixed table of inputs): it didn't know which graph it would
run, yet its form asked people to fill in parameters, so it was removed in 1.4.0. Every kind of graph it could run now
has its own tool above; each of those tools carries `replaces`, which the host uses to rewrite stored `run_workflow`
nodes and board tool cells (`values` keyed by node id or by node title are both accepted; cells that have no place in
the new tool are dropped and recorded in the revision notes).

The fixed ones:

| Tool | Read-only | Streaming | On by default | What it does |
| --- | --- | --- | --- | --- |
| `list_workflows` | ✓ | | ✓ | What each workflow takes (which node loads which kind of asset), what can be tuned, what it outputs, its `features` (upscale / inpaint / img2img / remove-background / …) and the tool that runs it (`tool`); workflows that can't be converted are listed too, with the reason; non-.json files in the workflows folder (a zip archive, say) are listed with why they can't be used (1.6.1) |
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
- Before submitting, the plugin checks object_info for the nodes and model files the graph needs and lists everything
  missing at once, queueing nothing. When only some outputs fail validation, ComfyUI still queues the prompt and runs the
  rest; the plugin removes it and says why instead of returning a leftover preview as the result (1.6.1).

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
