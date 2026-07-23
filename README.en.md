# Mibu

[简体中文](README.md) | **English**

An AI video creation studio = **NLE core + AI app center + creative agent workbench + social-media matrix publishing**.

A local-first desktop app: one Electron shell running a FastAPI backend (SQLite), a React frontend, and an embedded-browser publishing executor.
Import footage → transcript-based editing → export → publish to Douyin / Bilibili / Xiaohongshu / WeChat Channels, with workflows and scheduled triggers automating the whole chain.

![Demo: drag clips onto the timeline, position the playhead, split in one keystroke](docs/media/timeline-edit.gif)

> More walkthrough GIFs (workflow building, knowledge base, publishing matrix…) live in the [docs site](docs-site/) guides.

---

## Quick start

The built app lives at `release/mac-arm64/Mibu.app`. Double-click it, or:

```bash
open release/mac-arm64/Mibu.app
```

The app boots its bundled backend (on `127.0.0.1:8800`), loads the frontend, and starts the publishing executor — no manual services needed.

> If a healthy backend is already serving on port 8800 (e.g. your dev server), the app **reuses** it instead of starting another.

## Building from source

```bash
pnpm install                 # once, at the repo root
cd backend && uv sync && cd ..

pnpm build:mac               # frontend + publisher bundle + backend (PyInstaller) + package .app
open release/mac-arm64/Mibu.app
```

`pnpm dist:mac` is the same pipeline but produces a `.dmg` for distribution.

### App updates

Five seconds after launch, the packaged app silently compares the latest
[GitHub Release](https://github.com/Alndaly/mibu-cut/releases) tag with the current version and
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
| `pnpm build:backend` | PyInstaller backend → `backend/dist/mibu-backend` |
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
| `~/.mibu-cut/mibu.db` | Main SQLite DB (workspaces / projects / assets / sequences / jobs / accounts…) |
| `~/.mibu-cut/media/` | Imported and exported media files |
| `~/.mibu-cut/kb_vectors.db` | Knowledge-base vectors (Milvus Lite; remote configurable) |
| `~/Library/Application Support/mibu/logs/publisher.log` | Full publishing-executor trace (claim/goto/login/patrol/report) |
| `~/Library/Application Support/mibu/logs/backend.log` | Packaged-backend stdout/stderr |
| `~/Library/Application Support/mibu/Partitions/` | Persistent login sessions per publishing account |

For publishing issues, start with `publisher.log` — every step is recorded.

## Repository layout

```
backend/          FastAPI + SQLAlchemy 2.0 + Alembic
  app/domain/     Domain core: sequences (editing), render, workflows, publish, kb, agent,
                  scheduler, transcripts, generation, plugins, notifications
  app/api/routes/ HTTP routes
  tests/          pytest
frontend/         Vite + React 19 + TS + Tailwind v4 + Radix/shadcn
  src/features/   editor timeline monitor media ai-studio workflows batch
                  publish kb scheduler plugins settings
  src/design/     design tokens (tokens.css)
  src/app/        shell, routing, i18n (messages.ts), global styles (styles.css)
electron/         main.cjs (main process) + publish/ (embedded-browser publishing executor, TS)
agent-sidecar/    agent sidecar (pi runtime, Node)
docs/             architecture and subsystem docs (see below)
plugins/          local plugins (subprocess + MCP)
skills/           file-based agent skills (skills/<id>/SKILL.md)
```

## Deep-dive docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system architecture: three-stage bootstrap, domain core, data model, key patterns
- [docs/PUBLISHING.md](docs/PUBLISHING.md) — publishing & account matrix: embedded browser, worker protocol, **hard constraints & troubleshooting**
- [docs/MCP.md](docs/MCP.md) — the agent's MCP tools and confirmation cards
- [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md) — plugin manifest format and permissions
- [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) — implemented capabilities and frontend conventions

## Third-party sign-in (optional)

Google / Apple sign-in buttons appear only when credentials are configured (`backend/.env`):

```
MIBU_GOOGLE_CLIENT_ID=...        # Google Cloud "Web application" client
MIBU_GOOGLE_CLIENT_SECRET=...    # register redirect URI http://127.0.0.1:8800/api/auth/oauth/google/callback
MIBU_APPLE_CLIENT_ID=...         # Apple Services ID; Apple requires HTTPS callbacks (team deployments)
MIBU_APPLE_CLIENT_SECRET=...     # a JWT signed with your team key per Apple's spec
MIBU_OAUTH_REDIRECT_BASE=...     # override the callback base for team deployments (default http://127.0.0.1:8800)
```

The flow is a desktop-friendly authorization code flow: system browser completes auth → callback hits the local backend → the app polls and signs in automatically. First login creates a local account from the email's local part (same rights as password accounts, no local password).

## License

Source-available, **all rights reserved**: evaluation / learning / personal non-commercial use only; commercial use and redistribution require written permission. See [LICENSE](LICENSE).

## Teams / remote servers

The default backend is local. To use a team server: **"Backend server · switch" at the bottom of the login page** — it must be chosen before signing in, because the login request itself targets that server.
Enter the cloud address → health probe → switch and reload (sign in again). Settings → Local backend offers the same entry.
