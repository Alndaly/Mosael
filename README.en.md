# Open Studio

[简体中文](README.md) | **English**

An AI video creation studio = **NLE core + AI app center + creative agent workbench + social-media matrix publishing**.

A local-first desktop app: one Electron shell running a FastAPI backend (SQLite), a React frontend, and an embedded-browser publishing executor.
Import footage → transcript-based editing → export → publish to Douyin / Bilibili / Xiaohongshu / WeChat Channels, with workflows and scheduled triggers automating the whole chain.
Workflows nest (subgraphs / call-workflow / marquee-collapse), and every persistent browser login lives in one **Browser Pool**, reusable by publishing, workflow RPA, and the agent.

![Demo: drag clips onto the timeline, position the playhead, split in one keystroke](docs/media/timeline-edit.gif)

> More walkthrough GIFs (workflow building, knowledge base, publishing matrix…) live in the [docs site](https://openstudio.team) guides (source in `docs-site/`).

### Recently added

**Providers and models are now two levels** — a "provider" is **one endpoint plus one credential**,
and it can hold any number of models; capabilities (chat / image / video / audio), context window,
and the reasoning/vision switches all live on the **model**. A profile used to carry exactly one
model, so one endpoint's chat model and image model could never appear in two capability sections —
people ended up naming profiles after models and pasting the same key five times. Expanding a
provider now lists its models; adding one is a searchable input (DashScope's catalog has 233 entries,
which is neither scrollable nor findable as a flat list), and models missing from the catalog
(private deployments, aliases) can be typed by hand.

**Context meter and automatic compaction** — how much room is left is shown in the composer's session
settings; past 80% of the window, older turns are summarized by the model and the recent ones kept.
You can also compact on demand. Compaction is recorded in the conversation (how many messages moved
out, how many tokens freed) rather than happening silently. Each model's context window is editable,
defaulting to the vendor catalog.

**Thinking mode** — off / low / medium / high per session, streamed into a block that collapses when
done. "Off" only means we don't ask for it: models that think regardless (k3, DeepSeek reasoner) still
have their thinking shown.

**Subscription quota** — Claude, Codex, Kimi Code, xAI, OpenRouter and Copilot plans can report their
current quota and reset window on demand. Expired tokens refresh themselves; you're only asked to
re-authorize when a refresh actually fails.

**Runs in the tray** — closing the window no longer quits. Scheduled tasks run inside the local
backend, which is a child process of the app: on Windows/Linux, closing the window used to stop
them silently while users assumed they were still running. The tray icon is the visible proof the
app is alive; turn on **Launch at login** in Settings to have it standing by from boot. While a
task is running the app blocks system sleep (a laptop closing mid-render suspends ffmpeg with it),
and finished tasks raise a system notification — but **not while the window is focused**, so the
same event is never announced twice.

**Approve confirmation cards inside Feishu** — when a turn is driven from Feishu, changes that
need confirmation arrive as a card in that same chat; approve or reject without switching back to
the desktop app. Who may approve follows the account binding: the person tapping the button must
already be bound to an Open Studio account and still be a member of the workspace. Everyone in a
group chat can see the card; seeing it is not permission to approve it.

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
| `~/.open-studio/kb_vectors.db` | Knowledge-base vectors (Milvus Lite; remote configurable) |
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
