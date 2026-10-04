# ComfyUI

Connects a ComfyUI server (on this machine or another machine on your LAN) to Mosael. **It ships with Mosael**: once
Mosael is installed it is already on the Plugins page, so there is nothing to find in the marketplace.
One connection brings two things: **models** (every saved workflow is an image / video generation model) and **tools**
(used directly by the agent and by workflows).

## Connecting

1. Plugins page → ComfyUI → "New connection", and fill in the server URL (`http://127.0.0.1:8188` by default on this
   machine). If it sits behind a reverse proxy with login or behind ComfyUI-Login, put `user:password` (Basic) or a
   token (Bearer) into the "Access credential" credential; it is sent on both HTTP and WebSocket requests.
2. Grant the permissions it asks for and turn the connection on (since 1.10.0 it declares five):
   - `network:comfyui`: talk to this ComfyUI;
   - `network:huggingface`, `network:civitai`, `network:modelscope`: the model library looks up links and downloads
     models from these sites;
   - `filesystem:write`: when ComfyUI runs on the same computer as Mosael, downloaded models are written into its
     models folder.

   **Upgrading from an older version**: an upgraded connection is **paused** until you grant the new ones: one more
   (`network:modelscope`, 1.10.0) when coming from 1.9, four more when coming from 1.8 or earlier. The top of the
   connection card lists them, and "Grant these N" resumes it right away; earlier grants are kept. The plugin list marks
   it "Needs permission".
3. **Every workflow saved** in that ComfyUI shows up as a model in the model pickers of AI Studio, boards and the
   workflow "AI generate" node. A newly saved workflow appears within a minute (the host asks for the list's fingerprint
   once a minute); if you can't wait, click "Refresh models" on the Plugins page.

For several servers, create several connections; each brings its own set of models.

**When it can't connect** (1.9.2), the first line of the error only says what to do — "Can't reach this ComfyUI. Make
sure it is running and the URL is right"; the URL and the raw reason (`[Errno 61] Connection refused` and the like) are
on the next line, which Mosael puts under "Details" or in a hover note.

## How a workflow becomes a model

| In the workflow | In Mosael |
| --- | --- |
| Nodes upstream of a sampler / guider that encode a prompt (CLIPTextEncode and its Flux and SDXL variants, conditioning nodes that carry the prompt on their own `prompt` like MiniMax H3, a text node wired into one of those) | Prompt and negative prompt |
| Without a sampler ComfyUI knows (partner API nodes: MiniMax / Hailuo, Kling, Veo…; packs with their own sampler such as WanVideoWrapper): a **multiline** `prompt` / `prompt_text` / `positive_prompt` on a node wired into an output (1.6.0) | Prompt; a `negative_prompt` on the same node is the negative prompt |
| The sampler's seed, RandomNoise's noise_seed | "Seed" (random on every run when left empty) |
| Width and height of the node that creates the canvas (EmptyLatentImage, the Wan / Hunyuan video latent nodes…) | "Size" (the workflow's own size when not set; that size and a few common ones are only suggestions: any width x height is accepted, each side rounded to the nearest multiple of 8 and at least 16, the same rule as the tool's width and height, 1.7.0) |
| The canvas node's batch_size | "Image count" (up to 4, 1 when not set); every image is returned |
| An image workflow with no canvas of its own (inpainting, image-to-image: it starts from a loaded image) but with a seed | Still has "Image count" (1.7.0): the plugin **submits it N times**, one after another, with a new seed each time (counting up from the given seed, or random when none is given); each image's seed comes back with it (the generation record / the tool's `seeds`). Cancelling stops the run in progress and submits no more; when one run fails, the images that came out are still returned with a note saying how many of N came out and why the others didn't; after a Mosael restart it waits for the run in progress and then runs the rest. A graph without a seed (upscaling) would produce the same image N times, so it gets no image count |
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

## Model library (1.8.0)

The connection's **Model library** on the Plugins page: every model file on this ComfyUI, with a tab per folder, a
base-model filter and search. Files with a preview (a png / jpg / webp of the same name, or a cover inside the
safetensors) show it; the others get a per-folder placeholder. Open one for its full metadata, trigger words and the
workflows that use it. See ADR 0034 in the Mosael repository for the decisions.

**How the base model is recognised** (first match wins, and the interface says which; the rules live in
`tools/families.py`):

1. `ss_base_model_version` in the file header (written by kohya's training scripts; the most specific). For base models
   the training script doesn't know (anima, seen on a real server), `modelspec.architecture` defaults to
   `stable-diffusion-v1`, so this one is read first;
2. otherwise `modelspec.architecture`;
3. once it is known to be SDXL, a training base model name (`ss_sd_model_name`) or file name containing illustrious /
   noob / pony narrows it to that branch;
4. otherwise keywords in the file name (including subfolders): `illustrious` / a standalone `IL` → Illustrious, `noob` →
   NoobAI, `pony` → Pony, `kontext` → Flux Kontext, `flux` → Flux, `wan2.2` → Wan 2.2, `wan2.1` → Wan 2.1, `qwen_image` →
   Qwen-Image, `z_image` → Z-Image, `hunyuan` → HunyuanVideo, `ltx` → LTX-Video, `sdxl` / a standalone `xl` → SDXL,
   `sd15` / `v1-5` → SD 1.5, and so on. Names are only read in folders holding things made for a base model
   (checkpoints, loras, diffusion_models, controlnet, embeddings, vae…), never for text encoders, upscalers or detectors;
5. values written in the metadata but not in the table (anima, krea2) are shown as they are; with nothing to go on it
   stays empty.

**Trigger words**: the ones the author wrote into the header (`modelspec.trigger_phrase` / `ss_trigger_words`);
otherwise the most frequent training tags (`ss_tag_frequency`), marked as "not necessarily trigger words".
**Used by**: saved workflows whose node inputs name the file. **Missing for workflows**: models a workflow declares a
download link for (node `properties.models`, or the newer top-level `models`), that a node currently uses, and that
aren't on this server; only `https://huggingface.co/` and `https://civitai.com/` links (ComfyUI's own frontend's
allow-list) and ModelScope's `https://modelscope.cn/` and `https://modelscope.ai/` (1.10.0) count. Civitai's other
domains (`civitai.red`, `civitai.green`) are the same site: pasted links and links in workflows are rewritten to
`civitai.com` before resolving and downloading, and the token only goes to `civitai.com` (1.9.1); ModelScope's `www.`
hosts are rewritten the same way.

Metadata read file by file is remembered in the plugin's data folder by server, folder, name, size and modification
time: the first look at a few hundred files takes seconds, later ones only list the folders.

**Downloading**: paste a link (a HuggingFace file, `/blob/` or `/resolve/`; a Civitai model page, with or without
`modelVersionId`, or download link; a ModelScope model page or file; any other direct link). It is looked up first (file
name, size and a suggested folder: from the model type on Civitai and for models in ModelScope's AIGC section, from a
folder name in a HuggingFace / ModelScope file path, otherwise you pick), then downloaded onto **that ComfyUI**.

**ModelScope** (1.10.0): model pages `/models/{repo}` (and tabs such as Files), folder pages `/tree/{revision}/{folder}`,
file pages `/file/view/{revision}/{path}`, direct links `/resolve/{revision}/{path}`, and the official SDK's download URL
`/api/v1/models/{repo}/repo?FilePath=` are understood. For a model or folder page, a single model file inside
(`.safetensors`, `.ckpt`, `.gguf`, `.pt`, `.pth`, `.bin`) is the one; with several, the candidates are listed and you're
asked to paste that file's address. Models in the AIGC section: type Checkpoint / LoRA / VAE → checkpoints / loras / vae,
the registered base model type (`VisionFoundation`) and base model repository (`BaseModel`) go through the same family
table as above, and the author's trigger words and display name come along; ordinary repositories get no guessed family.
The international site `modelscope.ai` is a separate site (same API, its own models and accounts), asked on its own and
never rewritten to `.cn`. Downloads use the `/resolve/` link (large files redirect to a signed CDN address, which gets no
token).

Downloads take the first route that works:

1. ComfyUI's own download API: 0.38.0 has none;
2. **ComfyUI-Manager (V4)**: that machine downloads it, without byte progress and without a way to stop it once started
   (the Manager can't stop a single task; cancelling only stops Mosael waiting). Its security policy only allows this when
   ComfyUI listens on a local address or `network_mode = personal_cloud` in `user/__manager/config.ini`; a LAN ComfyUI
   started with `--listen 0.0.0.0` refuses by default, so the plugin turns the reason in the log into plain words,
   remembers it and warns in the model library next time;
3. **ComfyUI runs on this computer** (its model folders exist here and the files match what it reports): written
   straight in, first as `name.mosael-part` and then given the real name; with byte progress and cancel (only its own
   partial file is removed), and a free-space check before starting;
4. none of these: it says so and gives the step you can take (install the Manager, change `network_mode`, or put the
   direct link into `models/<folder>/` yourself).

**Nothing existing is overwritten**: a name already taken must be changed first (a `name (1).ext` suggestion is
offered), and it is checked again when writing (a hard link gives the file its real name and fails if the name exists).
Model files are never deleted, renamed or moved; no custom nodes are installed and the Manager's settings are not
changed.

**Picking model files in generation forms** (1.9.0): the parameter for a workflow input that picks a checkpoint, LoRA,
VAE, text encoder… says which model folder its files are in (`x-model-folder`, recognised by input name and by node for
shared names: CLIPLoader's `clip_name` is text_encoders, CLIPVisionLoader's is clip_vision). AI Studio, boards and the
workflow node use it to read this connection's model library: each item in the list has a thumbnail (or a per-folder
placeholder), its base model and first trigger words, which can also be searched; after picking a LoRA with trigger
words, a line below lists them and "Add to prompt" appends them to the prompt (skipping ones already there).

**When downloading through ComfyUI-Manager**, the download dialog says up front that a Civitai token, when one is
needed, goes into the download URL and stays in that machine's Manager task history; that HuggingFace and ModelScope
tokens can't be passed at all (the Manager takes no request headers, and neither site has a way to put the token in the
URL), so files that need one fail; that there is no byte progress; and that cancelling after it starts doesn't stop the
download on that machine. Manager V4 doesn't restrict model downloads by site (only by its security policy), so
ModelScope links work through it too. Civitai and ModelScope links are looked up without the token first (public models
need no login) and only retried with it when the site asks for a login (ModelScope answers 404 for private models it
won't show, so a 404 is retried with the token too).

**Credentials**: enter a "HuggingFace token" on the connection for gated or private HuggingFace repositories, a
"Civitai token" for Civitai models that need a login, and a "ModelScope token" for private or restricted ModelScope
models (get one at modelscope.cn/my/myaccesstoken; it is sent both as `Authorization: Bearer` and as the `m_session_id`
session cookie, like the official SDK; the international site has separate accounts and tokens). Each token goes only to
its own site (ModelScope's to modelscope.cn / modelscope.ai; never to the storage a download redirects to) and never
into results or errors; a Civitai download through the Manager can only carry it in the URL, so it stays in that
machine's Manager task history.

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
- `library.py` / `families.py` / `model_files.py`: the model library (model files, metadata, base-model
  families, which workflows use a file and which models they miss);
- `sources.py` / `install.py`: resolving HuggingFace / Civitai / ModelScope / direct links and downloading via the
  Manager → same machine → explain order;
- `comfy_http.py` / `ws.py`: talking to ComfyUI.

For the protocol, see `docs/PLUGIN_MANIFEST.md` in the Mosael repository: the sections on doing generation for the host,
streaming tools, and returning several results at once.
