import React from "react";

export function TimelineClip({
  trackKind,
  name,
  left,
  width,
  selected,
  dragging,
  onPointerDown,
  onTrimPointerDown,
  onSelect,
}: {
  trackKind: string;
  name: string;
  left: number;
  width: number;
  selected: boolean;
  dragging: boolean;
  onPointerDown: (event: React.PointerEvent) => void;
  onTrimPointerDown: (event: React.PointerEvent, edge: "start" | "end") => void;
  onSelect: () => void;
}) {
  const className = [
    "tl-clip",
    `tl-clip-${trackKind}`,
    selected ? "selected" : "",
    dragging ? "dragging" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={className}
      style={{ left, width }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        onSelect();
        onPointerDown(event);
      }}
      role="button"
      tabIndex={-1}
      title={name}
    >
      <span
        className="tl-clip-handle left"
        onPointerDown={(event) => {
          if (event.button === 0) onTrimPointerDown(event, "start");
        }}
      />
      <span className="tl-clip-name">{name}</span>
      <span
        className="tl-clip-handle right"
        onPointerDown={(event) => {
          if (event.button === 0) onTrimPointerDown(event, "end");
        }}
      />
    </div>
  );
}
