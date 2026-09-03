# Design QA

## 2026-09-04 — 官方工作流数据连接

- Scope: replace exact upstream-output literals in official workflows with native data bindings.
- Functional evidence: the installed transcript workflow migrated to revision 12 with
  `source_video.asset_id → verbatim_transcript.asset_id` as a data edge; the target config literal
  is empty and the target input handle is declared.
- Regression evidence: workflow template and engine suites pass; normalization is copy-safe and
  idempotent.
- Visual verification: blocked — the in-app Browser renderer is not available in this session, and
  the design workflow forbids silently switching to a second browser.
- final result: blocked

## 2026-09-04 — 满铺画布与停靠窗口

- Reference: user screenshots for the board/workflow full-bleed canvas, right dock, resize handle,
  fit-to-content action, and agent session header.
- Implemented: both detail canvases fill their page without an outer card radius or gutter; dock
  edges and resize-handle edges share one geometry contract; right-side dragging uses the right-dock
  direction; fit-to-content measures only the unobscured canvas rectangle; the session chevron now
  stays attached to the title as one compact trigger. Canvas utility windows, title pills, and action
  capsules share a translucent surface with backdrop blur instead of an opaque fill. Floating mode no
  longer inserts an empty layout row, the remaining header area is draggable, and board nodes no longer
  repeat run-state copy above their top-right corner.
- Automated evidence: shared panel geometry and visible-viewport calculations have unit coverage;
  the complete frontend test suite and production build pass.
- Visual verification: blocked — the in-app Browser renderer is not available in this session, and
  the design workflow forbids silently switching to a second browser.
- final result: blocked
