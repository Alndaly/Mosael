---
title: What is Mibu
description: A video studio that folds editing, AI generation, orchestration and publishing into one desktop app.
sidebar:
  order: 1
---

Mibu is a **local-first desktop app** that folds the four legs of content creation into a single window:

1. **Editing** — a professional multi-timeline, multi-track editor: ripple editing, speed ramps, transcript-driven cuts, color grading (curves / presets / LUT / scopes), subtitles and filters, one-click export.
2. **AI generation** — a conversational agent operates your project through tools; text-to-image / text-to-video results land in the media library.
3. **Orchestration** — visual workflows chain retrieval, generation, transcription, export and publishing into one graph, triggered manually, on a schedule, or via webhook.
4. **Publishing** — push a finished cut to a local folder, webhook, or Douyin / RedNote / WeChat Channels / Bilibili with persistent multi-account logins.

![Mibu home: workspace overview, 14-day task / publish / AI cost stats and project list](../../../../assets/screens/home.png)

**Home to editor in one step** — "New project" drops you straight into the editor, no intermediate dialogs:

![Demo: create a project from home and land in the editor](../../../../assets/gifs/home.gif)

## Architecture at a glance

- **Frontend**: Vite + React + TypeScript single-page app, packaged into Electron.
- **Backend**: FastAPI (Python) + SQLite, the single source of truth for projects, rendering, AI, workflows and publish jobs.
- **Executor**: a publish executor built into the Electron main process drives embedded browser views for logins and uploads.
- **AI agent**: hosts an external coding-agent CLI (opencode-style) with Mibu's MCP server as its tool surface; changes go through confirmation cards.
- **Data**: everything lives in `~/.mibu-cut` on your machine — no cloud dependency, works offline.

## Who it's for

Independent creators and small teams who want to go from editing to multi-platform publishing in one place, automate repetitive work with AI and workflows, and keep their footage off third-party clouds.

The source code is available on [GitHub](https://github.com/Alndaly/mibu-cut) (proprietary license — see [About the project](/en/about/project/)).

Next: [Quick start](/en/start/quickstart/).
