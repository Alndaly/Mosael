# Current interface captures

Documentation targets **1.9.3**. Every screenshot and video under [`website/public/media`](../../website/public/media) was recaptured on 2026-10-04 from the running 1.8.3 app, in Chinese and English, light and dark, against an isolated demo environment that a script builds from scratch. On 2026-10-05, ahead of 1.9.0, the scenes whose interface had changed since were recaptured from the current main (the package version still reads 1.8.3): `notes` and `plugins`, plus five new scenes — `note-history`, `model-library`, `workflow-library`, `generation-models` and `pricing`; each file's own source commit and capture time are in the manifest. The captures are real browser screenshots and real browser video of real clicks — not reconstructed UI or generated mockups. Historical design-review attachments elsewhere in `docs` are not current product documentation.

Which interface views have changed since they were captured, release by release, is tracked in [RECAPTURE.md](RECAPTURE.md) — the list to work through at the next recapture. Views this batch could not show truthfully stay listed there, each with the reason.

## Source and credit

Sample footage, excerpts and frames: **Big Buck Bunny**, © 2008 Blender Foundation / www.bigbuckbunny.org, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). [Film and license](https://peach.blender.org/about/); [source trailer](https://media.w3.org/2010/05/bunny/trailer.mp4). The seed script trims picture-only excerpts from the trailer, resizes them to 1280 × 720 and lays them out as an editing exercise; the stills are taken with the app's own "save this frame" and the demo library's GIF asset with its own "convert to GIF", so their source chains in the asset library are real. The model previews in the demo ComfyUI (below) are 4:5 stills cut from the same excerpts. Narration is synthesized locally with the macOS Samantha (English) and Tingting (Chinese) voices; subtitle cues follow the synthesized sentences. The two-page shot-list PDF is printed locally from the same excerpts.

## What is real and what is a placeholder

- The demo backend has its own data directory, its own demo account and its own ports. It never touches a personal backend, `~/.mosael` or the 8800 / 5173 development servers.
- **No AI results, tool successes, sign-ins or platform posts are fabricated.** Pages that need a provider to produce something show their real empty or not-yet-run state.
- One generation connection exists so that generation panels can be shown in their *configured, not run* state (model picker, "N×", 3D-reference chip, talking-photo model): it is named **「演示占位 · Placeholder」**, points at a closed local port and holds a placeholder string instead of a key. Nothing was ever generated through it, and it cannot generate anything.
- The agent scene uses a **real local model** — `qwen3.5` served by Ollama on the capturing machine (seed flag `--local-chat`). Its tool calls and replies are genuine output of that model, captured as they happened, so the wording differs between the four sets. The script types a request to delete one asset (the English one adds "Please reply in English", since the model otherwise answers in Chinese); the model looks the asset up and calls the delete tool, which stops on the confirmation card; the script declines, so nothing is deleted. The conversation is removed after each recording.
- **The ComfyUI plugin's connection points at the test suite's fake ComfyUI** (`backend/tests/fake_comfyui.py`, started by the seed script as [`demo-comfyui.py`](../../website/scripts/demo-comfyui.py) on 127.0.0.1:8813), not at a real ComfyUI. It implements only the endpoints the plugin uses. Its model files are invented, generically named entries (`demo-sdxl-base.safetensors`, `storybook-style-lora.safetensors`, …) with a size and made-up safetensors header metadata (base model, trigger words, training tags); there are no model weights anywhere. Their previews are Big Buck Bunny stills. Its five workflows are written for the demo, some in folders next to two empty folders (the workflow library shows the folder tree); one uses a node type the server lacks (from a fictional node pack, "Frame Tools", known to the fake ComfyUI-Manager) and two model files it lacks, one with a `huggingface.co` address declared in the workflow. **Nothing was generated, downloaded or installed**: the recordings open the download dialog for the missing file that has no address (it resolves nothing) and never press Download, Install or Save; the pasted workflow in the import scene stops at the preview. Both ComfyUI connections send anything that is not loopback through a closed local port (their own network setting), so not even a mistake could reach HuggingFace, Civitai or ModelScope. The second connection points at a closed local port and shows the real "can't reach this ComfyUI" state.
- `notes-agent` opens the note page's assistant with a selected sentence attached; nothing is sent. Its model picker shows the local Ollama model this batch was seeded with (`qwen3.8`).
- The brief note's version history was saved version by version through the note page's own endpoints (create → edit → "save to note" → edit → restore version 2 → edit) while seeding, so every version carries the seeding time; nothing in it is back-dated. The seed then opens the note once on the note page, whose editor re-saves Markdown in its own layout; that save folds into the last version (see `open_note` in the seed script).
- The cost rules in `pricing` are prefilled with the page's own "Prefill" for the placeholder connection: its model catalog is on the closed port, so they come from the built-in price list. They are deleted again after each recording.
- The scheduled task, the workflow run history and the "to-edit" tags on the videos come from one real run of a small workflow that only uses local nodes (asset query, tag, text template, save note), started with the scheduler's own "run now".
- The custom-CSS editor and the in-app browser windows exist only in the desktop shell; these captures come from the web build, which shows the custom-CSS section's real "needs the desktop app" note.

## Inventory

- `screens/`: full-resolution native screenshots (2880 × 1800, a 1440 × 900 viewport at 2×), quantized with
  `pngquant --quality=80-100 --speed 1 --skip-if-larger --strip` — same resolution, about 40% of the size. The upper bound is
  100 on purpose: with 80-95 pngquant uses fewer colours once the target is met, and small areas of unique colour got merged
  away (the gold sphere in the 3D scene turned grey, a red badge lost its colour, gradient swatches banded). Compared block by
  block with the originals and checked by eye in both themes and languages, there is no visible difference at 80-100.
- `videos/`: the browser recordings as 1280 × 800 H.264 MP4s without audio. The website plays them as muted loops
  (`<Loop>`: loads and plays only while in view, never autoplays under reduced motion) or with controls (`<Recording>`).
- There are **no GIFs**: the same recording as a GIF was five to six times the size of the MP4. The media tests fail if a GIF
  appears under `website/public/media` or a page references one.
- Chinese light files are at each directory root; `dark/` holds Chinese dark; `en/` and `en/dark/` hold English light and dark. Chinese recordings use the Chinese demo workspace and English recordings the English one, with the same content in each language.
- `homepage/{zh,en}/`: the three feature windows on the website's homepage (below).
- `docs/media/mosael-promo.mp4` (the "watch the tour" link in the repository READMEs) is a plain concatenation of the Chinese dark `home`, `media-preview`, `timeline-edit`, `boards` and `workflows` recordings, re-encoded once, with nothing added.
- `capture-manifest.json` records per-file source commit, capture version and time, scene, locale, theme, byte count and SHA-256. The website's media tests reject files missing from it or whose bytes no longer match.

### Scenes

Each scene is one recording (`videos/<scene>.mp4`) plus the screenshots taken along the way, in all four language/theme sets.

| Scene | Screenshots |
| --- | --- |
| `home` | `home` |
| `media-preview` | `media`, `url-import`, `media-video`, `media-audio`, `media-image` (source chain "From: … (frame)", source labels) |
| `documents` | `media-documents` (Document filter), `document-reader` (parsed text / original pages / details) |
| `timeline-edit` | `editor`, `editor-inspector` |
| `timeline-tools` | `editor-linked`, `editor-overwrite` (cut-out preview while dragging), `editor-in-out`, `editor-clip-menu`, `editor-shortcuts` |
| `subtitle-dub` | `subtitles`, `subtitle-dub`, `transcript` |
| `subtitle-panel` | `subtitle-bilingual` (two tracks in one box), `subtitle-timing`, `subtitle-import`, `subtitle-files` |
| `export` | `export-dialog` (loudness normalization) |
| `ai-studio` | `ai-chat`, `agent-trace`, `ai-generate`, `ai-audio` |
| `generation-models` | `ai-generate-models` (a demo ComfyUI workflow's LoRA field: previews, base model, trigger words) |
| `agent` | `agent-confirm` (card under the tool row), `agent-decided` (the one-line outcome) |
| `workflows` | `workflow-list`, `workflows`, `workflow-add-node`, `workflow-node` |
| `workflow-editor` | `workflow-references` (dotted reference lines), `workflow-reference-tags`, `workflow-start-params`, `workflow-readiness`, `workflow-runs` |
| `workflow-templates` | `workflow-templates`, `workflow-template-check`, `workflow-start-options`, `workflow-readiness-blocked`, `workflow-full-video` |
| `boards` | `boards`, `board-form`, `board-mention` |
| `board-cells` | `board-add-menu`, `board-abilities`, `board-selection` (shared exit), `board-generate` ("N×"), `board-picker`, `board-scene-cell`, `board-scene-reference`, `board-timeline` |
| `annotations` | `annotations`, `marker-editor` |
| `notes` | `notes` (top bar), `notes-hint` (name and shortcut), `notes-insert-menu`, `notes-selection` (selection toolbar), `notes-ai-actions`, `notes-agent` (selection attached, nothing sent), `notes-markdown` |
| `note-history` | `notes-history` (versions by day, how each came about, what changed), `notes-history-compare` (against the previous version) |
| `scenes` | `scenes`, `scene-add`, `scene-camera`, `scene-observation`, `scene-keyframes` |
| `entities` | `entities`, `entity-detail`, `entity-speak` |
| `plugins` | `plugins` (opens on ComfyUI), `plugin-detail` (Baidu Netdisk connection), `plugin-connection`, `plugin-collapsed` (two ComfyUI connections collapsed; the title row expands) |
| `plugin-market` | `plugin-market` (filter by capability) |
| `model-library` | `model-library`, `model-detail` (a LoRA: base model and why, trigger words, workflows using it, metadata), `model-library-error` (closed port, details open) |
| `workflow-library` | `workflow-library`, `workflow-import` (pasted JSON, preview step), `workflow-library-detail` (missing node and models), `model-download` (for the missing file without an address) |
| `publishing` | `publish`, `publish-form`, `browser-pool`, `browser-account` |
| `scheduler` | `scheduler`, `scheduler-runs`, `scheduler-form` |
| `providers` | `settings`, `settings-models`, `settings-capabilities` |
| `appearance` | `settings-appearance`, `settings-fonts`, `settings-background`, `appearance-glass` |
| `admin` | `admin`, `admin-members`, `admin-engines`, `admin-deployment`, `statistics` |
| `pricing` | `admin-pricing` (prefilled rules; video models per resolution tier, base tier first) |
| `login` | `login` |

## The demo environment

[`website/scripts/seed-doc-demo.py`](../../website/scripts/seed-doc-demo.py) builds everything with one command. Give it a private directory outside the repository (or a git-ignored one):

```bash
pnpm install && pnpm --dir agent-sidecar build        # frontend and the agent sidecar
backend/.venv/bin/python website/scripts/seed-doc-demo.py up --fresh \
  --dir /private/path/mosael-demo --local-chat qwen3.5:latest
# … record …
backend/.venv/bin/python website/scripts/seed-doc-demo.py down --dir /private/path/mosael-demo
```

`up` downloads the trailer once (proxy variables cleared, direct from media.w3.org), cuts the excerpts and synthesizes the narration into `<dir>/media`, starts a backend on **127.0.0.1:8812** with `MOSAEL_DATA_DIR=<dir>/data`, builds the frontend into `<dir>/dist` and serves that build on **127.0.0.1:5274** (`vite preview`; the packaged app loads the same bundle, whereas the dev server's first-visit compiling would show up in recordings as "Loading…"), starts the demo ComfyUI on **127.0.0.1:8813** (the test suite's fake ComfyUI with the content in [`demo-comfyui.py`](../../website/scripts/demo-comfyui.py); its model previews are cut into `<dir>/media/previews`), signs up the demo administrator through the app's own sign-up flow, and creates through the backend's HTTP API:

- a Chinese and an English workspace, each with a project whose timeline has linked picture and music, narration, two subtitle tracks (bilingual) and an outlined title, plus a 9:16 vertical cut;
- the asset library: trailer, excerpts, narration, stills, a GIF, the shot-list PDF (parsed locally), and asset-library characters, a location and a prop with reference images;
- notes (the brief saved version by version, so its version history has one entry of each kind), the app's own three-hall example scene (created by clicking its button), three boards (story study; gallery with a note document, the 3D scene cell and markers; rough cut with a timeline cell);
- the official templates (speech cleanup, topic to finished video, the three analysis templates) and the local-only roundup workflow, two scheduled tasks and one real run;
- example plugins from `plugins/examples` placed in the demo plugins directory and picked up by the app's scan, a Baidu Netdisk connection without credentials, two ComfyUI connections (the demo ComfyUI, and a closed local port) granted every permission the plugin's manifest asks for and given no token, a browser-pool profile;
- the placeholder generation connection, and — with `--local-chat` — the local Ollama chat model (only the named model is enabled; Ollama `:cloud` models stay off).

It writes `<dir>/token.json` (the session token as a JSON string), `<dir>/credentials.json` and `<dir>/fixture.json` (workspace, project, sequence, board, workflow, scene, note, entity, asset and ComfyUI connection IDs), all `0600`. **None of them, nor the demo database, may be committed.** The script refuses the 8800 / 5173 ports and any data directory inside `~/.mosael`, and checks that the backend answering on 8812 is the one using `<dir>/data`. `up` without `--fresh` reuses an existing demo; `--fresh` wipes the database (downloaded media are kept). `down` stops the backend, the frontend and the demo ComfyUI (their process IDs are in `<dir>/pids.json`). Every demo title lives in the script's `TEXT` table; the capture script reads them from there.

## Re-record

```bash
backend/.venv/bin/python website/scripts/record-doc-media.py \
  --demo-dir /private/path/mosael-demo --clock 2026-10-04T10:30
backend/.venv/bin/python website/scripts/capture-homepage.py --demo-dir /private/path/mosael-demo
python3 scripts/compose-readme-showcase.py
```

Requires Playwright Chromium, ffmpeg and pngquant (`brew install pngquant`); every screenshot is quantized as it is saved, before its hash goes into the manifest. `--only scene,scene` retries scenes; `--locale zh|en` and `--theme light|dark` narrow the sets; `--out <dir>` makes a trial run elsewhere without touching `website/public/media` or the manifest. `--clock` fixes the wall-clock time only for the scenes that show the Home greeting, so all four sets read the same time of day. Interface labels are written in Chinese in the script and looked up in the app's own message tables for English; ambiguous ones are given explicitly. A failed selector stops the run instead of substituting an old image (a failure screenshot lands in the system temp directory). The script performs real clicks, typing, hovering and dragging and records real browser video; it does not replace UI text or DOM content. Where a recording moves to another page, that page is opened once before the recording starts, so the take shows a page already loaded this session rather than the first-visit "Loading…". Edits a scene makes for the camera are undone before it ends (a dragged clip is cancelled with Esc, a typed prompt is put back, 3D keyframes are undone, the agent conversation is deleted, the prefilled cost rules are deleted, the pasted workflow is never saved), so every set starts from the same seeded data. The notes list is set 20 px narrower than its default (a per-device layout setting): at 1440 px the English labels on the right of a note's top bar would otherwise fold the Insert / link / table group into "More formatting". The ComfyUI scenes refresh the offline connection first with its own refresh button: the reason a connection failed is stored in the language of whoever refreshed it last.

Rebuild `docs/media/mosael-promo.mp4` from the five Chinese dark videos with ffmpeg's concat demuxer (libx264, CRF 24, `+faststart`, no audio).

After recording, review the screenshots and a few frames of each recording (no misalignment, half-loaded panels, debug overlays or personal data), remove any file no longer produced and no longer referenced, run `pnpm --dir website test` and `pnpm --dir website build`, and check both themes on desktop and narrow screens. The media tests reject stale or untracked captures, wrong-language references and missing light/dark pairs.

## README showcase

`readme-showcase.zh.png` and `readme-showcase.en.png` are composed by `scripts/compose-readme-showcase.py` from the three unaltered homepage captures the website uses (`website/public/media/homepage/{zh,en}/{boards,editor,scenes}.png`). The script reproduces the homepage's own layout — boards behind left at -2°, the editor behind right at +2°, the 3D scene in front — reading the percentages from `website/src/components/home-showcase.tsx`. Only rounded corners, a hairline border and a drop shadow are added; the screenshots themselves are untouched, and the result is quantized the same way as the screenshots. Regenerate it after re-capturing the homepage images.

The same script also writes the website's share cards, `website/public/og/mosael-{zh,en}.png` (1200 × 630, used for Open Graph and Twitter previews on every page): the composed image is scaled into the card and padded with the same warm background, nothing else is added. `--only og` regenerates just the cards, `--only readme` just the README images.

## Homepage feature windows

`website/public/media/homepage/{zh,en}/` contains six unaltered 2× browser captures (1440 × 940 viewport, quantized like the screenshots) from the same demo environment:

- `boards.png`: the story-study board; light, WenKai (Chinese) / Caveat (English).
- `editor.png`: the Big Buck Bunny timeline with linked music, narration, bilingual subtitles and the outlined title; dark, Newsreader.
- `scenes.png`: the three-hall example scene in the overview camera; dark, Space Grotesk.

The homepage composes these screenshots as overlapping windows in HTML; phones show one complete window at a time. The surrounding site follows its own light/dark theme while the captures deliberately keep different supported app appearances. No app controls, content or generation results were fabricated; the footage attribution above applies. `capture-homepage.py` records source commit, version, language, theme, font, timestamp, dimensions and SHA-256 in `capture-manifest.json`.
