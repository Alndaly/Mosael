# ADR 0023: Plugin tools declare their effects; the agent asks before the ones that have any

## Status

Accepted — 2026-09-26. Amends ADR 0021 decision 2 (board tool cells now read the same declaration) and
[AGENT_PERMISSION_MODES.md](../AGENT_PERMISSION_MODES.md) §4.2 / §4.12.

## Context

Plugin tools reach the agent as first-class tools (`plugin__<connection>__<tool>`, ADR 0005). Until now they
all ran directly when the agent called them; the only per-tool flag was `read_only`, which decides whether a
sub-agent may have the tool. That was fine for "list my bucket", but not for the tools that followed:

- the Manim plugin's `manim_animation` / `manim_still` execute model-written Python on the host — the same
  thing the built-in `run_host_code` only does behind an `external` card;
- the object-storage plugins' `*_upload` send the user's files to a third-party server;
- ComfyUI's `clear_queue` / `interrupt` / `free_memory` act on a shared GPU server;
- TikHub's MCP endpoints spend API credits per call.

Meanwhile the board (ADR 0021 P3) had grown its own rule for the very same tools: when the agent runs a tool
cell, `effects` is `none` if the plugin says `read_only`, else `external`, and non-`none` needs a card. So one
tool asked first on the board and ran silently in chat, and neither place could tell "costs money" from
"runs code on your machine".

## Decision

1. **One vocabulary, one module.** `backend/app/domain/effects.py` (a leaf, no imports) defines
   `none | paid | external | local-code`, the tier each maps to (`paid → ai-cost`, `external` and
   `local-code → external`; `none` opens no card), the card's warning line, and how a plugin tool's value is
   resolved. Board producers, the plugin registry, the agent manifest, the confirmation card and the market
   index generator all call it.
2. **The manifest declares it per tool.** `tools.declare[].effects`, `tools.overrides.<tool>.effects` (the only
   place an MCP plugin can say it), and a package default `tools.default_effects` (TikHub: dozens of paid
   endpoints). Runtime-reported tools (`provides: ["tools"]`) may carry it too. Resolution: override >
   declared > package default > **`external`**. `read_only` implies `none`.
3. **Mistakes fail at install, not at run time.** An unknown value, or `read_only: true` with a non-`none`
   effect, is a `ManifestError`: silently treating a typo as "ask" hides the author's intent, and a read-only
   tool is handed to sub-agents, which cannot wait for a card. Runtime-reported tools have no install moment,
   so they are cleaned conservatively: unknown values are dropped (→ default), and a read-only/effect clash
   drops `read_only`.
4. **The agent path opens a card named after the tool.** `POST /api/agent/tools/plugin__…` (the sidecar) and
   the MCP meta-tool `invoke_plugin_tool` (which now goes through the same route instead of the plugin page's
   "try it" endpoint) run `none` tools directly and otherwise open a confirmation whose `tool` is the concrete
   agent tool name. The confirmation kernel resolves that name through a registered *family*
   (`confirmable_family("plugin__", bind)`), so:
   - "always allow in this session" is per tool, not per "any plugin";
   - `validate` re-derives the tool, connection and effects for the requester and overwrites the payload
     (caller-supplied `effects` does not count);
   - `needs_card` / `escalate` read the same `effects`, so autopilot (bypass, auto tiers, `no-card`) applies
     exactly as for built-in tools; auto mode still sends `external` / `local-code` back to a person because
     no rule gate exists for them;
   - approval runs the same `plugins.tools.invoke`, as the **approver**, only on a connection the approver owns.
   The manifest (`GET /api/agent/tools`) marks those tools `confirmation: true`, so the sidecar blocks on the
   card with no special case.
5. **People clicking do not get cards.** The plugin page's "try it", workflow plugin nodes (the user started
   the run) and the user pressing Run on a board are unchanged.
6. **Visible before use.** `effects` is in `GET /api/plugins` (tools), `GET /api/plugins/tools` (so MCP
   `list_plugin_tools` shows it) and the market index; the plugin page and market detail badge non-`none`
   tools 「需确认」/ "Asks first".

First-party declarations: Manim `manim_animation` / `manim_still` and Remotion `remotion_animation` →
`local-code`; storage `*_upload`, Baidu `pan_upload`, ComfyUI `interrupt` / `clear_queue` / `free_memory` →
`external`; ComfyUI `run_workflow` and every per-workflow tool → `paid` (GPU time, often rented);
imports into the library (`*_fetch`, `pan_import`, `import_outputs`) and the setup / explainer tools →
`none`; TikHub → `default_effects: "paid"`.

## Consequences

- A non-read-only plugin tool that declares nothing now asks first in chat (it already did on the board). This
  is the intended tightening; authors opt out per tool with `effects: "none"`.
- TikHub calls ask in manual mode and auto-run (up to the paid run limit) in auto mode.
- No stored data changes shape: cards are ordinary `tool_confirmations` rows; the new manifest keys are
  optional. Existing installs of first-party plugins pick up the declarations with their version bump; until
  then their tools fall back to `external` (still asking).
- The board warning keys `confirm_boardRunPaid` / `confirm_boardRunExternal` (unreleased) became the shared
  `confirm_effect*` keys.
