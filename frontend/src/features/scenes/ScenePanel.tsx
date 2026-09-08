import type React from "react";

/** Independent, always-visible object and property panes. */
export function ScenePanel({ id, title, count, actions, children }: {
  id: string; title: string; count?: number; actions?: React.ReactNode; children: React.ReactNode;
}) {
  return <section className="scene-panel" data-open="true" aria-labelledby={`scene-panel-${id}`}>
    <header><div className="scene-panel-toggle"><h2 id={`scene-panel-${id}`}>{title}{count === undefined ? null : <span>{count}</span>}</h2></div>{actions}</header>
    <div className="scene-panel-body">{children}</div>
  </section>;
}
