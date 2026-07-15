# Mibu New

Clean-room rewrite of Mibu Video Studio.

Current milestone: Phase 1/2 skeleton with a real SQLite domain model, FastAPI backend,
Vite/React frontend shell, and Electron desktop shell.

## Run backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8800
```

## Run frontend

```bash
cd frontend
pnpm install
pnpm dev
```

## Data

Default data dir: `~/.mibu-new`.

