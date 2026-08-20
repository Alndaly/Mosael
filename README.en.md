# Open Studio

[简体中文](README.md) | **English**

An AI video creation studio = **NLE core + AI app center + creative agent workbench + social-media matrix publishing**.

A local-first desktop app: one Electron shell running a FastAPI backend (SQLite), a React frontend, and an embedded-browser publishing executor.
Import footage → transcript-based editing → export → publish to Douyin / Bilibili / Xiaohongshu / WeChat Channels, with workflows and scheduled triggers automating the whole chain.
Workflows nest (subgraphs / call-workflow / marquee-collapse), and every persistent browser login lives in one **Browser Pool**, reusable by publishing, workflow RPA, and the agent.

![Demo: drag clips onto the timeline, position the playhead, split in one keystroke](docs/media/timeline-edit.gif)

> More walkthrough GIFs (workflow building, knowledge base, publishing matrix…) live in the [docs](https://openstudio.team) guides (source in `website/content/docs/`).

### Recently added

**Subagents & multi-agent collaboration** — the main agent can hand a self-contained
investigation to a **subagent** (read-only tools; the intermediate steps stay in its own context
and only the conclusion comes back — it saves context, not compute). Dispatch is
**non-blocking by default**: the agent gets a receipt immediately and keeps working, deciding for
itself whether and when to wait; multiple dispatches in one message run concurrently, and any
un-collected reports are delivered automatically at the end of the turn — none are ever lost.
Every subagent is a **session you can click into** (the exact same UI as the main conversation),
reachable from the header and the inspector panel, with every step visible live. Agents in
different sessions can also **@-notify each other**: an idle target starts a turn immediately, a
busy one queues the message, and it arrives wearing a "from another agent" badge.


**Import media from a link** — paste a video or playlist URL, look at what is behind it, then decide
what to download. **Probing before downloading is deliberate**: a link may be one video or a whole
playlist (hundreds of items, tens of gigabytes). Audio or video is chosen *before* downloading
(someone who only wants the voice for transcription should not pay for hundreds of megabytes and a
transcode), and the quality ceiling lists only the steps this link **actually has** — probing already
knows what it tops out at, and offering a step that does nothing is letting the UI lie for the site.

For content that needs a sign-in, **borrow an identity from the browser pool** instead of exporting a
cookie jar from somewhere else. YouTube makes this obvious: anonymously it now tops out at 360p
(measured), and 1440p with a session.

![Import from a link: the listing, multi-select, quality and audio/video choice](docs/media/url-import.png)

**Subtitle dubbing, and engines split from models** — every cue in the subtitle panel carries its own
dub button, and you can also dub a batch. The audio lands on a dedicated dub track (the original audio
is untouched; delete the track and you are back where you started), and dubbing again returns to that
same track rather than stacking up a pile. "Fit to cue length" is optional — it uses the clip's own
speed, so the render applies atempo: lossless, undoable, still adjustable afterwards.

The thing that matters most on this path: **when the language does not match, the engine does not
error**. It reads the text with the pronunciation rules it knows, hands back something that sounds
almost-but-not-quite Chinese, and reports success. Now it is said at the moment you pick the engine,
not after you listen to it. The test uses writing systems only (kana, hangul, Cyrillic, Arabic and
Devanagari are hard evidence; Latin letters prove nothing, so those languages are chosen explicitly
in the "Weights" dropdown).

Following that thread, F5-TTS's **language support moved from the engine onto the weights**: the engine
speaks anything, the weights decide what. Ten languages (Chinese+English / Japanese / French / German /
Spanish / Italian / Russian / Hindi / Arabic / Finnish) download on demand, and whichever one is missing
gets a download button right there in the dub popover — reading Japanese in your own cloned voice is
just one more checkpoint away.

![Subtitle dubbing: a per-cue entry point, landing on a dedicated dub track](docs/media/subtitle-dub.png)

**A "Trajectory" view for agent sessions** — the conversation answers "what it said"; the trajectory
answers **"what it did, and where the time went"**: three lanes (input / model / tools) compress the
whole session into blocks, with a step-by-step ledger below and per-step arguments, results and timing.
The system prompt is recorded **only on the turns where it changed** (cross-session memory and the task
plan are both baked into it, so it differs almost every turn), and context injection is its own row —
the prompt you see is the one the model actually received.

![Trajectory view: three lanes, a step ledger, and session totals](docs/media/agent-trace.png)

**Per-platform publish options** — visibility (private / unlisted / public), YouTube's "made for kids",
Xiaohongshu's originality declaration; declared in one place, and the form follows the platform.
TikTok and YouTube automated publishing are verified end-to-end on real accounts; Bilibili and WeChat
Channels were checked and have no visibility control, so we do not pretend they do.

**The backend speaks your language too** — job messages, engine catalogs and download progress lines
all follow the request's `Accept-Language`. Keys and params are stored, translation happens at the exit:
a job record outlives the request that created it, and translating on write freezes the language forever.

**Type scale follows the screen** — 673 hardcoded pixel sizes collapsed into four tokens.

**Providers and models are two levels** — a "provider" is **one endpoint plus one credential** and can
hold any number of models; capabilities, context window and the reasoning/vision switches live on the
**model**.

**Context headroom and auto-compaction** — the session settings show what is left; past 80% of the
window the earlier turns are summarised and the recent ones kept. Compaction stays visible as a record.

**Thinking levels / subscription quota / desktop residency / approving from Feishu** — per-session
thinking budget; quota and reset windows for subscription providers; closing the window means the tray,
not exit (scheduled jobs run in the local backend); confirmation cards can be approved in Feishu.

**Workflow nesting (à la ComfyUI / dify)** — marquee-select nodes on the canvas and collapse them into a subgraph in one click; boundary references rewire automatically. Subgraphs nest arbitrarily, `call_workflow` reuses a whole flow as a tool, and loop bodies run on the same parallel engine as the top level.

![Marquee → collapse to subgraph](docs/media/collapse-subgraph.gif)

**Browser pool** — every persistent login becomes a reusable "profile": publish accounts (platform-bound) and generic logins for any site, managed in one place; publishing, workflow RPA, and the AI agent all reuse them. Agent reuse requires **explicit per-request approval** (a card that names the identity) — it can't touch a profile you didn't grant.

![Browser pool: unified logins, safely reused by workflows and the agent](docs/media/browser-pool.png)

![Agent authorization gate: reusing a login requires explicit approval each time](docs/media/agent-authorize.png)

> The browser pool is a live screenshot; the collapse animation and authorization card are illustrations generated from the brand design system.

---

## Quick start

The built app lives at `release/mac-arm64/Open Studio.app`. Double-click it, or:

```bash
open "release/mac-arm64/Open Studio.app"
```

The app boots its bundled backend (on `127.0.0.1:8800`), loads the frontend, and starts the publishing executor — no manual services needed.

> If a healthy backend is already serving on port 8800 (e.g. your dev server), the app **reuses** it instead of starting another.

## Building from source

```bash
pnpm install                 # once, at the repo root
cd backend && uv sync && cd ..

pnpm build:mac               # frontend + publisher bundle + backend (PyInstaller) + package .app
open "release/mac-arm64/Open Studio.app"
```

`pnpm dist:mac` is the same pipeline but produces a `.dmg` for distribution.

### App updates

Five seconds after launch, the packaged app silently compares the latest
[GitHub Release](https://github.com/Alndaly/OpenStudio/releases) tag with the current version and
shows a prompt linking to the release page when a new version exists. There is also a
"Check for updates" button under Settings → Local backend → Version.
**Shipping a release is just pushing a tag**:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

CI (`.github/workflows/release.yml`) builds the macOS `.dmg` (arm64) and the Windows
installer (NSIS), attaches them to a GitHub Release with auto-generated notes, and only
publishes the release once both platforms succeed. The app version is taken from the tag —
no need to bump `package.json` first. Build artifacts go to Releases only, **never into the
repository**. Triggering the same workflow manually from the Actions page is a dry run
(workflow artifacts only, Releases untouched).

> Silent auto-install on macOS requires a Developer ID signature + notarization (Squirrel's
> signature check always fails on unsigned builds), so the current behavior is check-and-prompt.
> `build.publish` is already configured for the GitHub provider; once signing is available,
> swapping in electron-updater upgrades this to fully automatic installs with no renderer changes.

⚠️ **Any frontend change requires re-running `build:frontend`** (`build:mac` includes it). Packaging after only `build:publisher` ships a stale frontend — we've been bitten by "CSS changes not applying" this way.

### Build scripts

| Script | Purpose |
| --- | --- |
| `pnpm build:frontend` | Vite build → `frontend/dist` |
| `pnpm build:publisher` | esbuild bundle of the embedded publishing executor → `electron/publish.bundle.cjs` |
| `pnpm build:backend` | PyInstaller backend → `backend/dist/open-studio-backend` |
| `pnpm build:mac` | All three + electron-builder `.app` |
| `pnpm dist:mac` | Same, producing a `.dmg` |

## Development mode

Run backend and frontend separately (frontend hot-reloads):

```bash
# Terminal 1 — backend
cd backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8800

# Terminal 2 — frontend
cd frontend
pnpm dev            # http://localhost:5173
```

Almost everything can be developed in a browser at `http://localhost:5173`.
**Exception**: the embedded publishing browser (login/upload/address-bar toolbar) only exists in Electron; the web build shows a "desktop required" notice.

### Desktop hot-debugging (embedded browser and other Electron features)

No packaging needed — one command starts vite + Electron:

```bash
pnpm dev            # at the repo root; equivalent to frontend's pnpm electron:dev
```

It builds the publisher bundle first, then runs three things in parallel (color-prefixed `vite` / `bundle` / `electron`):
- `vite`: frontend HMR (`--strictPort` — if 5173 is taken it fails loudly instead of silently moving to 5174 and pointing Electron at the wrong server);
- `bundle`: `esbuild --watch=forever`, TS changes under `electron/publish/**` rebuild `publish.bundle.cjs` automatically;
- `electron`: waits for 5173, then loads it; the dev branch of `main.cjs` reuses or spawns the `uvicorn` backend on 8800.

The bundle updates automatically after `electron/publish/**` changes, but **the main process does not hot-reload** — restart `pnpm dev`. Same for `main.cjs`/`preload.cjs`. Main window DevTools: `Cmd+Option+I`; embedded account view: right-click an account on the publish page → "Inspect page (DevTools)".

If Electron reports `Electron failed to install correctly` (pnpm occasionally skips its install script): `pnpm rebuild electron`.

### Tests and checks

```bash
cd backend  && uv run pytest -q          # backend suite
cd frontend && pnpm vitest run           # frontend suite
cd frontend && pnpm exec tsc -b --noEmit # type check (must run inside frontend/)
cd frontend && pnpm gen:api              # regenerate TS types after backend OpenAPI changes
```

## Data and logs

| Location | Contents |
| --- | --- |
| `~/.open-studio/open-studio.db` | Main SQLite DB (workspaces / projects / assets / sequences / jobs / accounts…) |
| `~/.open-studio/media/` | Imported and exported media files |
| `<userData>/logs/publisher.log` | Full publishing-executor trace (claim/goto/login/patrol/report) |
| `<userData>/logs/backend.log` | Packaged-backend stdout/stderr |
| `<userData>/Partitions/` | Persistent login sessions per publishing account |

`~/.open-studio` lives under `Path.home()`, which on Windows is `C:\Users\<name>\.open-studio`.
`<userData>` is Electron's user-data directory: `~/Library/Application Support/Open Studio` on
macOS, `%APPDATA%\Open Studio` on Windows. The plugin directory follows the same rule — you never
need to assemble it by hand, the Plugins page shows the **actual resolved path** reported by the
backend.

For publishing issues, start with `publisher.log` — every step is recorded.

## Repository layout

```
backend/          FastAPI + SQLAlchemy 2.0 (schema via create_all + _migrate_*, see ARCHITECTURE)
  app/domain/     Domain core: sequences (editing), render, workflows, publish, browser, kb, agent,
                  scheduler, transcripts, generation, plugins, notifications,
                  provider_models, provider_quota, ai_retry
  app/api/routes/ HTTP routes
  tests/          pytest
frontend/         Vite + React 19 + TS + Tailwind v4 + Radix/shadcn
  src/features/   editor timeline monitor media ai-studio workflows browser-pool
                  publish kb scheduler plugins settings
  src/design/     design tokens (tokens.css)
  src/app/        shell, routing, i18n (messages.ts), global styles (styles.css)
electron/         main.cjs (main process) + publish/ (embedded-browser publishing executor, TS)
agent-sidecar/    agent sidecar (pi runtime, Node)
docs/             architecture and subsystem docs (see below)
plugins/          local plugins (subprocess + MCP)
```

## Deep-dive docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system architecture: three-stage bootstrap, domain core, data model, key patterns
- [docs/PUBLISHING.md](docs/PUBLISHING.md) — publishing & account matrix: embedded browser, worker protocol, **hard constraints & troubleshooting**
- [docs/MCP.md](docs/MCP.md) — the agent's MCP tools and confirmation cards
- [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md) — plugin manifest format and permissions
- [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) — implemented capabilities and frontend conventions
- [docs/MAINTENANCE_HOTSPOTS.md](docs/MAINTENANCE_HOTSPOTS.md) — known maintenance risk areas, and **what to run after touching them**

## Third-party sign-in (optional)

Google / Apple sign-in buttons appear only when credentials are configured (`backend/.env`):

```
OPEN_STUDIO_GOOGLE_CLIENT_ID=...        # Google Cloud "Web application" client
OPEN_STUDIO_GOOGLE_CLIENT_SECRET=...    # register redirect URI http://127.0.0.1:8800/api/auth/oauth/google/callback
OPEN_STUDIO_APPLE_CLIENT_ID=...         # Apple Services ID; Apple requires HTTPS callbacks (team deployments)
OPEN_STUDIO_APPLE_CLIENT_SECRET=...     # a JWT signed with your team key per Apple's spec
OPEN_STUDIO_OAUTH_REDIRECT_BASE=...     # override the callback base for team deployments (default http://127.0.0.1:8800)
```

The flow is a desktop-friendly authorization code flow: system browser completes auth → callback hits the local backend → the app polls and signs in automatically. First login creates a local account from the email's local part (same rights as password accounts, no local password).

## License

Source-available, **all rights reserved**: evaluation / learning / personal non-commercial use only; commercial use and redistribution require written permission. See [LICENSE](LICENSE).

## Teams / remote servers

The default backend is local. To use a team server: **"Backend server · switch" at the bottom of the login page** — it must be chosen before signing in, because the login request itself targets that server.
Enter the cloud address → health probe → switch and reload (sign in again). Settings → Local backend offers the same entry.
