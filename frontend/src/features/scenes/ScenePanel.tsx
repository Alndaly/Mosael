import React from "react";
import { ChevronDown } from "lucide-react";

/** Collapse whole panes while keeping their property groups expanded. */
export function ScenePanel({ id, title, count, actions, children }: {
  id: string; title: string; count?: number; actions?: React.ReactNode; children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(true);
  return <section className="scene-panel" data-open={open} aria-labelledby={`scene-panel-${id}`}>
    <header>
      <h2 id={`scene-panel-${id}`} className="scene-panel-title">
        <button className="scene-panel-toggle" aria-expanded={open} aria-controls={`scene-panel-body-${id}`} onClick={() => setOpen(!open)}>
          <ChevronDown size={14} /><span>{title}{count === undefined ? null : <small>{count}</small>}</span>
        </button>
      </h2>
      {actions}
    </header>
    <div id={`scene-panel-body-${id}`} className="scene-panel-body" hidden={!open}>{children}</div>
  </section>;
}
