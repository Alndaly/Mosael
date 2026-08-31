# Open Studio

**English** | [简体中文](README.zh-CN.md)

An AI video studio that runs on your own machine: **an NLE core, an AI app center, a creative
agent workbench, and matrix publishing to social platforms** — in one desktop app.

Everything is one Electron shell running a FastAPI backend (SQLite), a React frontend, and an
embedded-browser publishing executor. Import footage → edit against the transcript → export →
publish to TikTok / YouTube / Douyin / Bilibili / Xiaohongshu / WeChat Channels. Workflows and
scheduled triggers can automate that whole chain, and every persistent browser login lives in
one **Browser Pool** that publishing, workflow RPA, and the agent all reuse.

![Drag clips onto the timeline, position the playhead, split in one keystroke](docs/media/timeline-edit.gif)

---

## Quick start

Grab a build from [Releases](https://github.com/Alndaly/OpenStudio/releases) — macOS `.dmg`
(Apple silicon) and a Windows installer — or run one you built yourself:

```bash
open "release/mac-arm64/Open Studio.app"
```

The app boots its bundled backend on `127.0.0.1:8800`, loads the frontend, and starts the
publishing executor. No services to start by hand.

> If a healthy backend already answers on port 8800 (your dev server, say), the app **reuses**
> it rather than starting a second one.

Nothing is required beyond that to look around. To actually generate or transcribe you'll want
at least one provider configured — Settings → Providers, where a provider is *one endpoint plus
one credential* and models hang underneath it.

---

## What's inside

### Editing

A timeline NLE with transcript-based editing: cut by deleting words, and the clips follow.
Subtitles, dubbing, and speech recognition sit on the same panel rather than in separate tools.

Each subtitle line carries its own dubbing entry point, and you can dub a whole batch at once.
Output lands on a dedicated dub track — the original audio is untouched, so deleting the track
returns you to where you started, and re-dubbing replaces that track instead of stacking up a
pile of them. "Scale to segment length" uses the clip's own speed factor and resolves to an
`atempo` change at render time, so it stays lossless, undoable, and adjustable afterwards.

![Per-line dubbing, output on a dedicated track](docs/media/subtitle-dub.png)

The thing that matters most on this path: **when the language doesn't match, TTS engines don't
error**. They sound out your text with whatever pronunciation rules they know and report
success. Open Studio says so at the moment you pick the engine, rather than after you've
listened to forty seconds of nonsense. The check only trusts writing systems — kana, hangul,
Cyrillic, Arabic, Devanagari are hard evidence; Latin script proves nothing, so for those
languages you state the language yourself in the weights dropdown.

F5-TTS language support lives **on the weights, not the engine**: the engine supports anything,
and the weights decide the range. Ten languages (Chinese/English, Japanese, French, German,
Spanish, Italian, Russian, Hindi, Finnish) download on demand, with a download button offered
in the dubbing popover when one is missing — cloning your own voice into Japanese is one extra
weights file, nothing more.

### Media

Paste a video or playlist URL and you get a **listing first, download second**. That order is
deliberate: one link might be a single video or several hundred of them across tens of
gigabytes. Audio-only versus video is chosen before the download starts (someone who only wants
the transcript shouldn't pay for hundreds of megabytes and a transcode), and the quality menu
**only lists tiers this link actually has** — probing already knows the ceiling, and offering a
tier that turns out to be unavailable is letting the UI lie on the site's behalf.

For content that needs a login, borrow an identity straight from the Browser Pool instead of
exporting cookies from somewhere else. YouTube makes the difference obvious: 360p without a
session, 1440p with one.

![URL import: probe listing, multi-select, quality and audio/video choice](docs/media/url-import.png)

Right-click a video and choose **Convert to GIF** to create a derived GIF asset. The video is never
overwritten; the same conversion is available as a workflow node for repeatable pipelines.

### Agent

A chat workbench whose tools reach the whole app — the timeline, media, workflows, publishing,
the browser pool — over MCP, with a confirmation card for anything that has consequences.

Images and videos already in the media library are analyzed with the **model selected for the
current conversation**, not a hidden global vision model. Images are normalized before visual
input; video uses the session's Auto / Native / Frames setting and includes any existing speech
transcript. Subscription/OAuth models need no Base URL: their tool-free Gateway analyzes sampled
frames, while native whole-video input remains available only to API-backed adapters that support
it. Asking an OAuth model for Native mode fails clearly instead of switching models or modes.

The main agent can hand a self-contained investigation to a **subagent**: read-only tools, its
intermediate steps stay in its own context, and only the conclusion comes back. What that saves
is context, not compute. Dispatch is **non-blocking by default** — the agent gets a receipt
immediately and keeps working, deciding for itself whether and when to wait. Several dispatched
in one message run concurrently, and reports it never waited for are delivered at wrap-up, so
none are lost. Every subagent is **a session you can open** with the same interface as the main
conversation, reachable from the right-hand panel or the header, live while it runs. Agents in
different sessions can also **@-notify each other**: idle recipients start immediately, busy
ones queue, and the message carries a "from another agent" badge.

The **trace view** answers a different question than the transcript does. The transcript says
what the agent said; the trace says **what it did and where the time went** — three swimlanes
(input / model / tools) compressing the session into color, with a step-by-step execution flow
beneath it that opens up to show arguments, returns, and duration per step. The system prompt is
recorded only on the turns where it **changed** (cross-session memory and the task plan are
spliced into it, so it can differ every turn), and context injection is a separate entry — the
prompt you see is the one the model actually received.

![Trace view: three swimlanes plus a step-by-step execution flow](docs/media/agent-trace.png)

Context level is shown right in the composer's session settings. Past eighty percent of the
window, earlier conversation is handed to the model for summarizing while recent turns are kept
verbatim; "compact now" does it on demand. Either way it stays in the transcript as a record.

### Workflows

A node canvas in the lineage of ComfyUI and Dify, with nesting as a first-class idea. Marquee a
group of nodes and **collapse them into a subgraph** in one action — references crossing the
boundary reconnect themselves. Subgraphs nest arbitrarily, `call workflow` reuses an entire
flow as a single tool, and loop bodies share the same parallel engine as the top level.

![Marquee → collapse into a subgraph](docs/media/collapse-subgraph.gif)

### Browser Pool

Every persistent login in one place, as **profiles**: publishing accounts bound to a platform,
plus general-purpose logins for any site. Publishing, workflow RPA, and the agent all reuse
those sessions.

Agent reuse takes **explicit per-use authorization** — the confirmation card names the identity
being borrowed — so it cannot touch an account you didn't hand over.

![Browser Pool: one place for login identities](docs/media/browser-pool.png)

![The authorization gate: reusing an identity is approved one use at a time](docs/media/agent-authorize.png)

### Publishing

Platform-specific properties are declared once and the form assembles itself per platform:
visibility (private / unlisted / public), YouTube's "made for kids", Xiaohongshu's originality
declaration. Automated publishing is verified end-to-end on real accounts for TikTok and
YouTube. Bilibili and WeChat Channels have no visibility control in practice, so Open Studio
doesn't pretend they do.

### Providers, plugins, and the rest

Providers and models are two levels: a **provider** is one endpoint plus one credential, and any
number of models hang beneath it. Capabilities (chat / image / video / audio), context length,
and the reasoning and vision switches all belong to the **model**. Subscription-based providers
report remaining quota and reset windows.

Evolink is available as one image/video gateway provider: configure one Evolink API key, then add
Seedance, Kling, Veo, Hailuo, WAN, Sora, GPT Image, Gemini or Seedream model rows under that
connection. Local reference images are uploaded through Evolink's Files API; completed results are
downloaded immediately into the local media library because gateway URLs expire.

Plugins run as subprocess scripts or connect to MCP servers, declaring their permissions in a
manifest. Install one from the built-in market or any zip URL — the package is fetched and its
manifest read *before* anything lands, so the permissions it declares and the tools it brings are
laid out for you first. Files move both ways: a plugin can hand one **back** (too big for the JSON channel, so it either
writes to a scratch dir or hands over a download URL and lets the host fetch it), and it can
**receive** one — mark an input `"format": "asset"` and the caller's asset id arrives as a local
path, so a plugin can upload or transcode without ever knowing the media library exists. It can
also **remember** something across calls (a refreshed OAuth token, say — the host persists it into
the keys the manifest declared and injects them back next run). The backend speaks your language too — job messages, engine catalogs, and progress
strings are returned per the request's `Accept-Language`. What's stored is a key plus
arguments, translated on the way out: a job record outlives the request that made it, so
translating at write time would freeze the language at that moment.

> Browser Pool is a real screenshot; the collapse animation and the authorization card are
> renderings from the brand design system.

---

## Documentation

Full guides live at **[openstudio.team](https://openstudio.team)** (source in
`website/content/docs/`). For the internals:

| Document | What it covers |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture: three-stage bootstrap, domain core, data model, key patterns |
| [docs/PUBLISHING.md](docs/PUBLISHING.md) | Publishing and the account matrix: embedded browser, worker protocol, **hard constraints and troubleshooting** |
| [docs/MCP.md](docs/MCP.md) | The agent's MCP tools and confirmation cards |
| [docs/AGENT_PERMISSION_MODES.md](docs/AGENT_PERMISSION_MODES.md) | What the agent may do without asking, and how the modes differ |
| [docs/PERMISSION_MODEL.md](docs/PERMISSION_MODEL.md) | The three principals and how authorization is decided |
| [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md) | Plugin manifest format and permissions |
| [docs/PLUGIN_ARCHITECTURE.md](docs/PLUGIN_ARCHITECTURE.md) | How plugins are packaged, instantiated, and granted capabilities |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | Coding conventions, and the 38 **ratchet tests** the repo enforces on itself |
| [docs/MAINTENANCE_HOTSPOTS.md](docs/MAINTENANCE_HOTSPOTS.md) | Known risk areas, and **what to run after touching them** |
| [docs/adr/](docs/adr/) | Architecture decisions, with the reasoning that produced them |

---

## Development

Backend and frontend run separately so the frontend hot-reloads:

```bash
pnpm install                 # once, at the repo root
cd backend && uv sync && cd ..
```

```bash
# Terminal 1 — backend
cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8800
```

```bash
# Terminal 2 — frontend
cd frontend && pnpm dev      # http://localhost:5173
```

`http://localhost:5173` covers most of the app. The **exception** is the embedded publishing
browser (login, upload, the address-bar toolbar), which only exists inside Electron; the web
build says "desktop required" there.

### Hot-debugging the desktop shell

For the Electron-only features, one command brings up Vite and Electron together, no packaging:

```bash
pnpm dev
```

Three things run in parallel behind color-coded prefixes:

- `vite` — frontend HMR, with `--strictPort` so a taken 5173 fails loudly instead of silently
  moving to 5174 and leaving Electron pointed at the wrong server;
- `bundle` — `esbuild --watch`, rebuilding `publish.bundle.cjs` when `electron/publish/**` changes;
- `electron` — waits for 5173, then loads it; the dev branch of `main.cjs` reuses or starts the
  `uvicorn` backend on 8800.

The publish bundle rebuilds itself, but **the main process does not hot-reload** — restart
`pnpm dev` after editing `main.cjs` or `preload.cjs`. DevTools for the main window is
`Cmd+Option+I`; for an embedded account view, right-click the account on the publish page →
"Inspect page".

### Tests and checks

```bash
cd backend && uv run pytest -q
```

```bash
cd frontend && pnpm vitest run
```

```bash
cd frontend && pnpm exec tsc -b --noEmit
```

```bash
cd frontend && pnpm gen:api
```

1,698 backend cases and 536 frontend cases at the time of writing. `tsc` must run from the
`frontend` directory. `gen:api` regenerates the TypeScript types after the backend's OpenAPI
schema changes.

### Troubleshooting

**`Electron failed to install correctly`** — pnpm occasionally skips its install script:

```bash
pnpm rebuild electron
```

**`bad interpreter: .../.venv/bin/python3: No such file or directory`** — a venv's console
scripts hard-code the interpreter path in their shebang, so renaming the repo directory (or
moving it to another machine) breaks all of them at once. Rebuild:

```bash
cd backend && uv venv --clear && uv sync
```

> The two places that start the backend (`dev:backend` and `main.cjs`) use
> `.venv/bin/python -m uvicorn` — `python` is a symlink and doesn't go through a shebang, so
> they survive a path change. What breaks is calling console scripts like `uvicorn` or `pytest`
> directly.

---

## Building and releasing

```bash
pnpm build:mac               # frontend + publisher + system bundle + sidecar + backend + .app
```

```bash
pnpm dist:mac                # same, producing a .dmg
```

| Script | What it does |
| --- | --- |
| `pnpm build:frontend` | Vite build → `frontend/dist` |
| `pnpm build:publisher` | esbuild the embedded publishing executor → `electron/publish.bundle.cjs` |
| `pnpm build:system` | esbuild the system-integration bundle → `electron/system.bundle.cjs` |
| `pnpm build:sidecar` | Build the agent sidecar in `agent-sidecar/` |
| `pnpm fetch:tts-python` | Fetch the standalone CPython shipped for voice cloning → `build/python` (~48 MB) |
| `pnpm build:backend` | PyInstaller → `backend/dist/open-studio-backend` |
| `pnpm build:mac` / `pnpm dist:mac` | All of the above, then electron-builder |

⚠️ **Changing the frontend means re-running `build:frontend`** (`build:mac` includes it).
Running only `build:publisher` and repackaging leaves the frontend at the previous build — a
mistake worth naming, because the symptom is a CSS change that "didn't take" and half an hour
of looking in the wrong place.

**Releasing is a tag:**

```bash
git tag v0.20.0 && git push origin v0.20.0
```

`.github/workflows/release.yml` builds the macOS `.dmg` (arm64) and the Windows NSIS installer
and attaches both to a GitHub Release with generated notes; it is only promoted once both
platforms succeed. The version comes from the tag, so there's no need to edit `package.json`
first, and build output goes to Releases and **never into the repository**. Triggering the same
workflow by hand from the Actions tab is a dry run — workflow artifacts only, Releases
untouched.

### App updates

Packaged builds compare the latest release tag against the running version five seconds after
launch and point you at the download page when there's a newer one. Settings → Local backend →
Version has a "check for updates" button.

> **Silent auto-install on macOS** needs a Developer ID signature plus notarization (Squirrel's
> validation always fails on an unsigned package), so today's path is the degraded
> check-and-prompt one. `build.publish` already has the GitHub provider configured; once
> signing is in place, swapping in electron-updater is a drop-in upgrade with no change to the
> renderer interface. When the repo has no releases or can't be reached, the check fails
> silently rather than interrupting you.

---

## Data and logs

| Location | Contents |
| --- | --- |
| `~/.open-studio/open-studio.db` | SQLite main database (workspaces, projects, media, sequences, jobs, accounts…) |
| `~/.open-studio/media/` | Imported and exported media files |
| `<userData>/logs/publisher.log` | The publishing executor end to end (claim, goto, login, inspection, report) |
| `<userData>/logs/backend.log` | Packaged backend stdout/stderr |
| `<userData>/Partitions/` | Persistent login sessions, one per publishing account |
| `<userData>/custom.css` | Your own CSS, applied over the app's styles (Settings → Appearance) |

`~/.open-studio` sits under `Path.home()`, which on Windows means
`C:\Users\<name>\.open-studio`. `<userData>` is Electron's user-data directory:
`~/Library/Application Support/Open Studio` on macOS, `%APPDATA%\Open Studio` on Windows.
Plugin directories follow the same pattern — no need to assemble the path from this table, the
plugins page shows the **real path** the backend resolved.

When publishing misbehaves, `publisher.log` is the first place to look; every step is recorded.

---

## Repository layout

```
backend/          FastAPI + SQLAlchemy 2.0 (schema via create_all + _migrate_*, see ARCHITECTURE)
  app/domain/     Domain core: sequences (editing), render, workflows, publish, browser, agent,
                  scheduler, transcripts, generation, plugins, notifications, assets, sandbox,
                  providers and provider_models, provider_quota, ai_retry
  app/api/routes/ HTTP routes
  tests/          pytest
frontend/         Vite + React 19 + TS + Tailwind v4 + Radix/shadcn
  src/features/   editor, media, ai-studio, workflows, browser-pool, publish, scheduler,
                  plugins, settings, admin, auth, home
  src/design/     Design tokens (tokens.css)
  src/app/        Shell, routing, i18n (messages.ts), global styles
electron/         main.cjs (main process) + publish/ and system/ (TS sources, bundled by esbuild)
agent-sidecar/    Agent sidecar (pi runtime, Node)
contracts/        Executable cross-implementation specs — frontend and backend run the same
                  corpus; see contracts/README.md
plugins/          Local plugins (subprocess scripts / MCP server connections)
website/          The documentation site (Next.js), source of openstudio.team
docs/             Architecture and subsystem docs
scripts/          Build and maintenance scripts
```

---

## Teams and remote servers

The default backend is the local one. To point at a team server, use **"Backend server ·
switch" at the bottom of the login page** — it has to be chosen before signing in, because the
login request itself goes to that server. Enter the address → health probe → switch and reload
(sign in again). Settings → Local backend is the same entry point.

### Third-party sign-in (optional)

Google and Apple buttons appear only when credentials are configured in `backend/.env`:

```
OPEN_STUDIO_GOOGLE_CLIENT_ID=...        # a Google Cloud "Web application" client
OPEN_STUDIO_GOOGLE_CLIENT_SECRET=...    # register http://127.0.0.1:8800/api/auth/oauth/google/callback
OPEN_STUDIO_APPLE_CLIENT_ID=...         # an Apple Services ID; Apple requires HTTPS callbacks
OPEN_STUDIO_APPLE_CLIENT_SECRET=...     # a JWT signed with your team key, per Apple's spec
OPEN_STUDIO_OAUTH_REDIRECT_BASE=...     # override the callback base for team deployments
```

It's a desktop-friendly authorization code flow: the system browser completes authorization, the
callback hits the local backend, and the app polls until it's signed in. A first login creates a
local account from the email's local part — same rights as a password account, no local
password.

---

## License

Source-available, **all rights reserved**: evaluation, learning, and personal non-commercial use
only. Commercial use and redistribution require written permission. See [LICENSE](LICENSE), and
contact the author for commercial licensing.
