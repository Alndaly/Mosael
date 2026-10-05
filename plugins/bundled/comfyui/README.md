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
Since 1.12.1 the plugin hands Mosael the failure reason in both Chinese and English, so the reason on the connection
card follows the interface language you are reading in, even when the refresh happened in the other language or in the
background (at startup, or when the workflow list changed).

## How a workflow becomes a model

| In the workflow | In Mosael |
| --- | --- |
| Nodes upstream of a sampler / guider that encode a prompt (CLIPTextEncode and its Flux and SDXL variants, conditioning nodes that carry the prompt on their own `prompt` like MiniMax H3, a text node wired into one of those) | Prompt and negative prompt |
| Without a sampler ComfyUI knows (partner API nodes: MiniMax / Hailuo, Kling, Veo…; packs with their own sampler such as WanVideoWrapper): a **multiline** `prompt` / `prompt_text` / `positive_prompt` on a node wired into an output (1.6.0) | Prompt; a `negative_prompt` on the same node is the negative prompt |
| The sampler's seed, RandomNoise's noise_seed | "Seed" (random on every run when left empty) |
| Width and height of the node that creates the canvas (EmptyLatentImage, the Wan / Hunyuan video latent nodes…) | "Size" (the workflow's own size when not set; that size and a few common ones are only suggestions: any width x height is accepted, each side rounded to the nearest multiple of 8 and at least 16, the same rule as the tool's width and height, 1.7.0) |
| The canvas node's batch_size | How many images one run makes, **as the workflow is saved**: a saved 4 makes 4 per run (since 1.12.3 the count no longer overwrites it) |
| An image workflow with a seed (with or without a canvas) | "Runs" (the parameter key is still `num_images`; up to 4, 1 when not set, 1.12.3): the plugin **submits it N times**, one after another, each run as the workflow is saved with a new seed (counting up from the given seed, or random when none is given); every output carries its run's seed (the generation record / the tool's `seeds`). What comes back is runs × images per run. Cancelling stops the run in progress and submits no more; when one run fails, what came out is still returned with a note saying how many of N runs came out and why the others didn't; after a Mosael restart it waits for the run in progress and then runs the rest. The form labels this field "Runs" and says below it how many images one run makes and how many this makes in total. A graph without a seed (upscaling) makes the same image every run, so it has no such field; neither do video graphs |
| The save nodes of that kind (the preview nodes when nothing is saved) | How many images one run returns (`outputs_per_run` = the batch each default output node receives, summed, counting 1 where the batch can't be told; the host multiplies it by the runs and lays out that many placeholders up front); with more than one, the parameters get a "Results from" choice (node titles): pick one to get only its output, and the other save nodes don't run (1.6.0); each choice's images per run are in `x-outputs-per-run`. "All" by default; "Final result" when some previews are an intermediate step or a control image (1.12.2, see below) |
| Any other tunable literal input | An entry in the parameter form: known inputs get plain names (`labels.py`: sampler, steps, LoRA…), and only on a name clash do they carry the node name or "KSampler #2"; unknown ones are called "node name · ComfyUI's name for the input"; the common ones come first and the rest (plus anything ComfyUI marks `advanced`) go under "Advanced", and inputs ComfyUI marks `hidden` are not listed; the raw "node · input name" is in the description |
| LoadImage nodes | Reference images; in a video graph, the ones wired to `start_image` / `first_frame` / `start_frame` / `first_frame_image`… are the first frame, `end_image` / `last_frame` / `end_frame`… the last frame (also when the image is resized or cropped first; an image-to-video graph's first frame is required, 1.6.1); when a role has several loader nodes (or a node is named), each slot is named in order (the node's title, or a node name plus number such as "Load Image #10" when unnamed) and the AI workbench, boards and workflow nodes show it (1.13.0) |
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

**Only the final result comes back by default** (1.12.2): in a workflow that only has preview nodes and contains a
decoder, "Results from" defaults to "Final result (node title)", so only the last result node comes back (the last one
of each branch when there are several), with as many images per run as the batch it receives. Two kinds of preview are
not the final result, and the choice marks them:

- **Intermediate**: what a preview shows is **worked on further** and becomes another output's image: the first
  pass of a two-pass workflow (latent upscale, or pixel upscale and re-sample), the image before a face detailer
  (FaceDetailer) or an upscale model, an image used as an IP-Adapter reference, a control image fed to ControlNet.
  For a decoded image, a second pass sampling the same latent counts too; decoding the same latent again with
  another decoder doesn't (it still shows the same pass).
- **Control images and masks**: what a ControlNet preprocessor (comfyui_controlnet_aux, category
  `ControlNet Preprocessors` in object_info) computes — skeleton, depth map, lineart; MeshGraphormer's hand depth
  map is all black when it finds no hand — and a mask (`MASK`) drawn as an image. They are never the result and never
  turn the finished image into an intermediate one: a mask or depth map computed from the finished image just to look
  at leaves the finished image as the result.

Only the wiring and the node definitions (category, socket types) decide, never node titles. Intermediate and
auxiliary previews don't run by default; pick "All" to get every one, or pick one node. The catalog's
`outputs_per_run` is the count for the default, and a request without "Results from" (AI Studio only sends the
parameters you changed, agents, workflow nodes) returns by the same rule, so placeholders and "N×" match what comes
back. **Save nodes are never narrowed down** (the workflow author asked to keep them, first pass included), and saved
files still win over previews; a graph with no decoder at all (upscaling, preprocessing tools, partner API nodes) is
left alone. The workflow tool ("Workflow · name") still returns every output node as-is.

There are two more models: **Built-in text-to-image** (when the server has at least one checkpoint) and **API template**
(when the connection config has the JSON from "Export (API)" pasted in; the `{{prompt}}` `{{negative}}` `{{seed}}`
`{{width}}` `{{height}}` `{{steps}}` placeholders work as before; this config field is `type: "json"`, so the Plugins
page gives it a code editor and validates it before saving).

## Tools

**One tool per workflow** (`wf_<id>`, "Workflow · name", see `tools/tooling.py`): the plugin reports them to the host in
`op: tools` (host capability `tools`, claimed by the same `comfyui_generation` as `generation`), and derives inputs and
outputs from that graph: the prompts, every node that loads an asset (`image_10`, `mask_11`, `video_1`…), every tunable
parameter (`steps_3`…, the same names as the generation parameters), and seed / size / runs (advanced; the input key is still `num_images`, one run by default, meaning the same as in
generation: each run as the workflow is saved, with a new seed, 1.12.3). Outputs
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

The connection's **Model library** on the Plugins page: every model file on this ComfyUI, with its folders down the left, a
base-model filter and search. Files with a preview (a png / jpg / webp of the same name, or a cover inside the
safetensors) show it; the others get a per-folder placeholder. Open one for its full metadata, trigger words and the
workflows that use it. See ADR 0034 in the Mosael repository for the decisions.

**How the base model is recognised** (the interface says which source it came from; the rules live in
`tools/families.py`, the weight-structure table in `tools/weights.py`):

1. **Metadata**: `ss_base_model_version` in the file header (written by kohya's training scripts; the most specific).
   For base models the training script doesn't know (anima and krea2, seen on a real server) it is written as is while
   `modelspec.architecture` defaults to `stable-diffusion-v1`, so it is read first; otherwise `modelspec.architecture`;
   with neither, old kohya LoRAs (with `ss_network_*`) only carry `ss_v2`: `False` means SD 1, `True` SD 2. Values are
   normalized to family names (`anima` → Anima, `krea2` → Krea 2, `qwen_image_2` → Qwen-Image 2);
2. **Weight structure** (shown as "recognized from the weights"): merged checkpoints and many LoRAs have no metadata at
   all, but the tensor names and shapes in the header give the network away. SD 1 / SD 2 / SDXL differ in the text width
   their cross-attention takes (768 / 1024 / 2048), Flux has double_blocks / single_blocks, Flux.2 shares one
   modulation, Krea 2's attention has a gate, Anima carries an llm_adapter, Wan's blocks hold `self_attn.q` and
   `ffn.0`, Z-Image and Lumina share a layout at different widths (3840 / 2304)… LoRAs copy their base model's layer
   names, in kohya, diffusers / peft, ComfyUI and LyCORIS spellings alike; GGUF files are read through their tensor
   table, falling back to `general.architecture`. When the metadata agrees (the same, or narrower: the weights only
   tell SDXL, the metadata says Pony) the metadata is used; **when it names a different architecture the weights win**
   (a real Flux LoRA claims sd_1.5). What can't be told apart is said less precisely: Wan 14B is the same network in 2.1
   and 2.2, so it is just Wan; diffusers-style AuraFlow (Pony V7's architecture) LoRAs also have
   single_transformer_blocks and are told apart from Flux;
3. once it is SDXL / Wan / Flux / AuraFlow, the training base model (`ss_sd_model_name`; Civitai's on-site trainer
   writes the base model's version number, and the official Illustrious, Pony and NoobAI versions are known), the
   title, then the file name narrow it: illustrious / `IL` / `ILL` → Illustrious, noob → NoobAI, pony → Pony,
   `wan2.2` / high noise / low noise → Wan 2.2, kontext → Flux Kontext, kolors → Kolors, pony v7 → Pony V7;
4. otherwise keywords in the **file name** (including subfolders, with camelCase split, so the XL and il in
   `novaAnimeXL_ilV160` count as words): `illustrious` / a standalone `IL` → Illustrious, `noob` → NoobAI, `pony` →
   Pony, `kontext` → Flux Kontext, `flux` → Flux, `krea2` → Krea 2, a standalone `anima` → Anima (not animagine),
   `minimax_h3` → MiniMax H3, `qwen_image_2` / `qwen21` → Qwen-Image 2, `qwen` → Qwen-Image, `kolors` → Kolors,
   `wan2.2` → Wan 2.2,
   `wan2.1` → Wan 2.1, `z_image` / a standalone `ZIT` → Z-Image, `hunyuan_video` → HunyuanVideo, `ltx` → LTX-Video,
   `sdxl` / a standalone `xl` → SDXL, `sd15` / `v1-5` → SD 1.5, and so on. Names are only read in folders holding things
   made for a base model (checkpoints, loras, diffusion_models, controlnet, embeddings, vae…);
5. values written in the metadata but in no table, with weights that say nothing either, are shown as they are; with
   nothing to go on it stays empty ("Unknown base model");
6. files in text encoder, CLIP vision, upscaler and detection / segmentation folders aren't made for one base model:
   they are not guessed and are marked "Not applicable" (`family_source` is `not_applicable`), apart from "unknown".

**Reading file headers**: through ComfyUI-Custom-Scripts' `/pysssss/view/`, reading only the start with a Range request
(a safetensors header is tens to hundreds of KB; anything over 8 MB is skipped), a few tens of milliseconds per file, a
few at a time. Without it (404), or on a server that ignores Range (answering 200 with the whole file), the first file
is the only one tried and the connection is dropped at once; the library falls back to ComfyUI's `/view_metadata` for
metadata only, so weights can't be recognized until it is installed, after which the next visit fills them in.

**Each file is listed once**: ComfyUI-GGUF registers `unet_gguf` / `clip_gguf` on the same folders as
`diffusion_models` / `text_encoders`, and Impact Pack's `ultralytics` contains `ultralytics_bbox` / `ultralytics_segm`.
Files are matched by their location on disk and kept under the folder registered first (ComfyUI's own come first);
files only an alias folder lists (`.gguf`) stay there.

**Trigger words**: the ones the author wrote into the header (`modelspec.trigger_phrase` / `ss_trigger_words`);
otherwise the most frequent training tags (`ss_tag_frequency`), marked as "not necessarily trigger words".
**Used by**: saved workflows whose node inputs name the file. **Missing for workflows**: models a workflow declares a
download link for (node `properties.models`, or the newer top-level `models`), that a node currently uses, and that
aren't on this server; only `https://huggingface.co/` and `https://civitai.com/` links (ComfyUI's own frontend's
allow-list) and ModelScope's `https://modelscope.cn/` and `https://modelscope.ai/` (1.10.0) count. Civitai's other
domains (`civitai.red`, `civitai.green`) are the same site: pasted links and links in workflows are rewritten to
`civitai.com` before resolving and downloading, and the token only goes to `civitai.com` (1.9.1); ModelScope's `www.`
hosts are rewritten the same way.

What is read file by file (the few metadata fields the base model, trigger words and title need, the family the weights
were recognized as, a GGUF's architecture) is remembered in the plugin's data folder by server, folder, name, size and
modification time: the first look at a few hundred files takes ten seconds or so, later ones only list the folders.
Families are worked out again on every listing, so changed rules apply at once; when the weight table changes, the
remembered results are dropped and read again.

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

### Model info: NSFW, source, finding on Civitai, preview videos (1.13.0)

Decision in the Mosael repository's ADR 0038 §9. The plugin hands over the raw facts; the host combines the verdict,
fetches and caches the media, and confirms before writing anything back.

- **NSFW signals** (`nsfw_signals`, `tools/nsfw.py`): **metadata** — adult tags make up at least a tenth of the training
  images in `ss_tag_frequency` (one or two stray images don't count), plus words in the file name and title (camelCase split);
  **Civitai** — the version matched by hash, or downloaded from Civitai through Mosael, has its model marked `nsfw`. The host
  adds the manual mark and local detection (both on the Mosael side): any signal saying yes counts, and a manual mark beats
  them all.
- **Source** (`source`, `tools/provenance.py`): the page recorded when Mosael downloaded the file (a HuggingFace / ModelScope
  file page, a Civitai version page), otherwise what the file's metadata says, or the Civitai version matched by hash. Kept in
  the persistent directory by server + folder + name + size; a changed file (different size) no longer counts. No link is ever
  guessed from a file name.
- **Find on Civitai** (`{"op": "lookup"}`, `tools/lookup.py`): with ComfyUI-Custom-Scripts installed, that machine computes the
  SHA256 (`GET /pysssss/metadata/<folder>%2F<name>`; the first time it reads the whole file and keeps the result in a `.sha256`
  next to the model) and Civitai is asked `/api/v1/model-versions/by-hash/{SHA256}` — a match is exact to the version. Without
  it, Civitai is searched by file name and only **exactly one** version whose original file name matches exactly and whose size
  is within 1 KB counts (marked `filename`; the user confirms before anything is saved back); several look-alikes count as none.
  A miss is recorded too, so a batch doesn't make that machine hash the file again for a while. A match brings the source page,
  the model's NSFW flag, the base model Civitai lists (refining a family only known as SDXL / Wan / Flux into Illustrious,
  Wan 2.2…, source `civitai`) and a few examples (`remote_previews`: 512-wide images; for versions whose examples are only
  videos, the `transcode=true,width=512` video). Civitai's public API needs no key; requests carry a browser-like User-Agent
  (the default one gets a 403).
- **Save as preview** (`{"op": "save_preview", "folder", "name", "path"}`, `tools/previews.py`): the host puts the picture
  (shrunk to a 512-wide PNG, or the 512-wide mp4) at `path`; the plugin uploads it to temp through `/upload/image`, then
  `POST /pysssss/save/<folder>%2F<name>` with `{"filename", "type": "temp"}` — pysssss copies it next to the model, named after
  the model with the uploaded file's extension (`x.png` / `x.mp4`). That route overwrites a file of the same name, so the host
  only calls it when the server has **no** preview yet. Without ComfyUI-Custom-Scripts, `preview_tools.save` is false and
  `save_note` says what's missing; the buttons are greyed out. Detection: `GET /extensions` lists its `betterCombos.js`
  (save, read by name) and `modelInfo.js` (hashing).
- **Preview files next to the model** (`sidecars`): `.mp4` / `.webm` preview videos named like the model, and for names with
  `[ ]` the image kinds ComfyUI's preview route can't find (it globs, and brackets break the pattern) — listed relative to
  `sidecar_base` (`/pysssss/view/`); the host reads them by exact name after the preview route says there's none. Not listed
  without pysssss.

## Workflow library (1.11.0)

The connection's "Workflow library" on the Plugins page: every workflow saved on this ComfyUI (ADR 0035), in the same
layout as the model library — subfolders on the left, search, kind filter, sorting and three view densities on top. Each
workflow gets a card: a thumbnail of its node graph (drawn from the nodes' positions and links in the workflow, not a
screenshot of ComfyUI; API-format graphs have no positions and are laid out by dependency), the inputs / parameters /
outputs it takes and produces, the model files it uses (present or not), missing node types (and the node pack each
comes from, when the Manager's mapping knows), and missing models whose download URL the workflow declares.

A node type counts as missing when it is not in this ComfyUI's object_info **and** is not a frontend-only node (Note,
Reroute, PrimitiveNode, KJNodes' Set / Get, rgthree's Fast Groups Bypasser / Label / Bookmark and the like never exist on
the backend); subgraph instances don't count either.

Mosael can change the workflow files on that machine directly, always through ComfyUI's own userdata API and **never
overwriting**:

- copy (the copy gets a new graph id — two graphs with the same id would get clashing tool names) and rename / move: if
  the target exists you're told so and offered a free name;
- delete is **not a hard delete** (ComfyUI's DELETE is, so the plugin never calls it): the file moves to
  `.mosael-trash/workflows/<deletion time UTC>/<original path>` in the user directory, outside `workflows/`, so neither
  ComfyUI's sidebar nor the plugin's model list shows it; Mosael's "Trash" can restore it, asking for another name if the
  original place is taken. To really delete it, remove that folder on the machine;
- after every change the host refreshes this connection's models and tools right away.

Folders (1.13.0): the left column is the tree of subfolders in `workflows/` — the same folders as ComfyUI's own workflow
sidebar, nothing kept on the side. The listing also reports `folders` (every subfolder, relative to `workflows/`;
`GET /api/v2/userdata?path=workflows` lists empty ones too, and an older ComfyUI without that endpoint only yields the
folders that hold files). Three ops change them, never overwriting and always checking the machine first:

- `make_folder`: ComfyUI has no "make a folder" call, so the plugin writes a hidden placeholder file, `.mosael-folder`
  (ComfyUI creates the parent folders when writing a file; neither ComfyUI's sidebar nor the plugin lists hidden files).
  An existing name (compared ignoring case, the machine may run Windows) answers with a clash and a free name;
- `rename_folder`: one `move` of the whole folder (`shutil.move` on ComfyUI's side moves folders too), the workflows in it
  get new paths; an existing target answers with a clash and is never merged into; a folder can't move into itself; a
  case-only rename goes through a temporary name (on a case-insensitive disk the target "already exists");
- `trash_folder`: **only empty folders** (no visible file inside; empty subfolders don't count) move into the trash folder —
  ComfyUI can't delete folders and the plugin never hard-deletes; a folder that still holds files answers
  `{"not_empty": true, "count": n}` and nothing is touched. Move the workflows out or delete them one by one first (each
  confirmed, each restorable): taking a whole folder of workflows away at once is too easy to regret, and non-workflow files
  in it (archives) would land in the trash where Trash can't list them.

Moving a workflow to another folder is `rename_workflow` (a missing target folder is created); a workflow that is no longer
there (ComfyUI answers 404) is reported as such rather than as "HTTP 404".

"Open in editor" (1.11.1): the listing also reports this ComfyUI's web address. The Mosael desktop app opens its
interface in this connection's own embedded browser and, once the page is ready, opens that workflow through the ComfyUI
frontend's own workflow list (ComfyUI's URLs only understand templates, shares and graph ids, so they can't open a saved
workflow); the web version opens a new tab and tells you which workflow to open from the "Workflows" sidebar. Save in
ComfyUI, come back to Mosael, and the workflow library plus this connection's models and tools are fetched again. If
ComfyUI sits behind a reverse proxy that needs a login, sign in once in that embedded browser.

## Import and fill in (1.12.0)

"Import" in the workflow library: drop a file in, pick one, or paste JSON or a link.

- **What it understands**: the JSON from ComfyUI's Save / Export and from Export (API); PNG / WebP files saved by ComfyUI
  (the workflow is embedded in the image; the UI format is used when present, otherwise the API format); archives (the
  first workflow inside, the rest listed in a note); links only from HuggingFace, Civitai, ModelScope and this ComfyUI
  itself (the network permissions the plugin declares), and a web page instead of a file is called out.
- **The API format has no layout**: values are put back according to this ComfyUI's node definitions, links are rebuilt
  and nodes are placed left to right by dependency, then it is saved in the UI format, so ComfyUI's sidebar can open it
  and the plugin can read it; the preview says the positions were laid out automatically. Images produced through Mosael
  only carry the API format (the plugin doesn't send the UI workflow when it submits), so importing them works the same way.
- **Preview before saving**: the node graph, the parameters it takes, missing node types with their node packs, and
  missing models; it is saved into `workflows/` without overwriting (a free name is offered on a clash) and gets a new
  graph id (so its tool name doesn't clash with the original).
- **Missing node packs**: with ComfyUI-Manager (V4), after you confirm, they are installed one by one through it (registry
  packs at their latest version, git-only packs from git); ComfyUI must restart to load them, which also goes through
  the Manager (confirmed again; running tasks are interrupted). The Manager's security policy: installing node packs
  needs ComfyUI to listen only locally or `network_mode = personal_cloud`; restarting needs `security_level` no stricter
  than normal. When refused, you're told what to change or how to install by hand.
- **Missing models**: those with a declared download URL download from the model library in one click (same dialog,
  same route).

## App forms (1.13.0)

The counterpart of RunningHub's "AI apps" (ADR 0038, first slice): the author picks the few items others should fill in
from **everything a workflow can take**, names and orders them, narrows choices, marks which output node is the result,
and keeps that as a short form for the workflow. The AI workbench, boards and workflow nodes all use this form when
they pick the workflow; a workflow without an app form still lists everything automatically (the "default app").

- **Where to edit it**: Workflow library → a workflow's detail → "App" → "Edit app form". On the left, everything the
  workflow can take, grouped by node with its current value and a "+" to add it; in the middle, the form as cards (drag or
  ↑ ↓ to reorder, rename in place, settings for main prompt and narrowed choices, "Start with a suggested set" while
  empty) and "Results from"; on the right, a live preview drawn with the generation panel's own controls. It works in the
  web build too, without the embedded canvas; the workbench's App panel shows the same editor as Pick / Form / Preview tabs.
- **What a node is called** (`labels.node_name`, 1.13.0): the title the user gave it in ComfyUI; otherwise ComfyUI's own
  name for that kind of node — the per-language translation from `/i18n` (the locales custom node packs ship), the Chinese
  name of common core nodes (`CORE_NODE_ZH`; ComfyUI's API doesn't serve core nodes' Chinese names), the object_info
  `display_name` — and the class name only when there is nothing else. Reading object_info also fetches `/i18n` once and
  folds it in (`labels.with_i18n`), so fillable items, clash hints, input slots, "Results from" and tool output names all
  use the same name. Fillable items also carry `node_label` (the editor groups by it) and `hint` (ComfyUI's `tooltip` for
  the input, per language); node number and class only appear in the hover detail for troubleshooting.
- **What can be filled in** (`graph.items`): the derivation the generation catalog and the tool inputs used to do
  separately is now one. Each item is anchored on `<node id>.<input name>` (the graph-level seed, size and runs have no
  node), the same parameter keys as before, so values saved on boards and workflow nodes don't need migrating. Nodes
  inside a subgraph can't be on an app form yet.
- **How form items enter the catalog**: a text field marked "Main prompt" is Mosael's prompt box (several fields of the
  same role get the same text); other text, models, numbers, dropdowns and switches are entries in the parameter form
  with your names, in your order, all on the first screen; a narrowed dropdown only offers those choices; nodes that load
  inputs are input slots, **each slot named in order** (your name, or the node's name); seed, size and runs use Mosael's
  own controls. The app name replaces the model's name in the model picker.
- **Items you don't pick run as authored**: they are not on the form and are not written — a prompt field not marked as
  the main prompt keeps the text saved in the workflow, an unpicked seed follows the workflow's own setting (fixed stays,
  randomize changes), and stale keys saved on a board cell are no longer written into the graph. The tool
  ("Workflow · name") takes only the form's items as well.
- **Results**: output nodes marked as the result are the default of "Results from" ("Your result (node name)") instead of
  a guess; save nodes can be marked too (two save nodes, keep only the high-resolution one). "Results from" can still be
  changed every time. Every output a generation returns carries the node it came from (`source_node` in the output's
  parameters).
- **Where it is kept**: in the workflow's own JSON — `properties.mosael` on nodes (`expose`: name, order, main prompt,
  narrowed choices; `result`) and `extra.mosael` on the graph (`version`, app name, description, seed / size / runs).
  ComfyUI's frontend saves such extension data back as is, so the form travels with copies, renumbered nodes, exports and
  other ComfyUI servers, and a deleted node takes its marks with it; everyone using the same ComfyUI sees the same form.
- **Writing it back**: the **only place Mosael overwrites an existing workflow** (`annotate`): only the `mosael` marks
  change; other extensions' keys, nodes and links are left exactly as they are. Every save is confirmed first, naming the
  server and the file. It carries the modification time read with the workflow, and if the file changed in between
  (saved in ComfyUI) nothing is written: "it was just changed in ComfyUI, open it again". If the workflow is open in
  ComfyUI with unsaved changes, saving it there will undo this change.
- **Items that no longer match**: every description checks that the node is still in the part of the graph that runs
  (not muted, not bypassed, connected to an output), that the input is still a value to fill in (not turned into a link)
  and that narrowed choices are still in the dropdown. Items that don't match are left off the form, listed in the
  workflow's detail and can be removed in one go.
- **Version**: only `extra.mosael.version` `1` is read. Other versions are treated as having no app form, with a notice;
  when the shape changes later, the plugin will ship an operation that rewrites the workflow files on that machine after
  one confirmation — the reading side doesn't understand old versions. On a graph without `extra.mosael`, marks on nodes
  don't count (they came along with nodes copied from another workflow).

## Workbench (1.13.0)

The second slice of ADR 0038: the Mosael desktop app opens ComfyUI's own canvas full screen in the connection's built-in browser (every
custom node works as usual) and docks Mosael's panels on the right: models, missing items, app, run & results. The canvas is reached
through a hard-coded script the Mosael main process injects (pull-only); on the plugin side there are only a few ops, none of which
touches files on that machine:

- `node_folders`: which model folder each input of the node selected on the canvas (node type + input name) picks from — the same
  table as the generation form's `x-model-folder` (`labels.model_folder`), a lookup only.
- `search_sources`: when the workflow gives no download address for a missing model, search Civitai, HuggingFace and ModelScope by
  its file name (the full name → without the extension → without a precision suffix) and return candidates (site, repository, exact
  file name, size, base model, a link the download accepts); exact names come first and are marked `exact`, similar ones never are.
  A site that fails goes into `failed` and the rest still answer; results are kept for 10 minutes in the plugin's data directory.
  It doesn't touch the ComfyUI server.
- `app` with `content`: reads the graph on the canvas right now (unsaved changes included); the same answer as for a file, without a
  path or modification time.
- `app_marks`: what an app form / result marks change on the canvas (`properties.mosael` on each marked top-level node, `extra.mosael`
  on the graph). It is the same function `annotate` writes files with (`app_form.apply`), so the mark format lives in one place;
  changing the canvas and saving is ComfyUI's own save.
- `generate` with `graph` (`prompt` / `workflow` / `client_id`): runs the graph on the canvas right now, without reading the file or
  filling parameters; missing nodes and models are still checked before submitting; the frontend's `client_id` is used (the canvas
  highlights the running node as usual) and the UI-format graph goes into `extra_pnginfo.workflow` (outputs dragged back into ComfyUI
  keep their layout). It follows the run by polling the history only, **without opening a WebSocket**: ComfyUI keeps one connection
  per `client_id`, and a second one would push the canvas off. Every output of the kind comes back with the node it came from
  (`source_node`); the workbench groups them by node and offers “Only this node's images”. Resuming after a restart still goes by prompt id.

Tested frontend: ComfyUI 0.38.0 / frontend 1.53.10 (read-only checks: injecting the bridge, probing, selection, export, `graphToPrompt`,
the dirty flag, plus the trackpad / mouse setting's key and the two requests it tries to write back to the server; nothing was
queued or saved). If a frontend lacks something the bridge uses, that panel says it isn't supported and the canvas keeps working.

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
- `graph.py`: finds prompts / seeds / sizes / slots / output nodes, gathers them into one list of what can be filled in
  (`items`) and a form (`Form`), describes the graph as a model, fills the graph in and collects outputs;
- `app_form.py`: app forms: reads, checks and writes the `mosael` marks in a workflow;
- `workbench.py`: what the workbench asks the plugin: which model folder a selected node's input picks from, and the marks an app
  form changes on the canvas;
- `labels.py`: plain names for tunable inputs, their order, whether they are common, and the few that aren't tuned in
  Mosael;
- `models.py`: which models exist, which graph is behind a model id, and the list's fingerprint;
- `run.py`: uploading assets, submitting, following progress, cancelling and fetching results (shared by generation and
  the workflow tools);
- `workflows.py`: `list_workflows` / `import_outputs`, and the part that returns outputs;
- `tooling.py`: one tool per workflow: derives inputs and outputs from the graph and runs the current graph;
- `server.py`: `server_status` / `list_models` / `interrupt` / `clear_queue` / `free_memory`;
- `library.py` / `families.py` / `weights.py` / `model_files.py`: the model library (model files, file headers with
  metadata and tensor tables, base-model families from metadata, weights and file names, which workflows use a file
  and which models they miss);
- `sources.py` / `install.py`: resolving HuggingFace / Civitai / ModelScope / direct links and downloading via the
  Manager → same machine → explain order;
- `civitai.py` / `lookup.py` / `nsfw.py` / `provenance.py` / `previews.py`: model info: Civitai's API and answer shapes,
  finding by hash or file name, NSFW signals, source, preview files next to the model and saving a preview back;
- `comfy_http.py` / `ws.py`: talking to ComfyUI.

For the protocol, see `docs/PLUGIN_MANIFEST.md` in the Mosael repository: the sections on doing generation for the host,
streaming tools, and returning several results at once.
