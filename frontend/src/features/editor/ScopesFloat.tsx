import React from "react";
import { GripHorizontal, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Scopes } from "@/features/editor/Scopes";

const POS_KEY = "mibu.scopes.pos";

function readPos(): { x: number; y: number } {
  try {
    const raw = JSON.parse(localStorage.getItem(POS_KEY) ?? "null");
    if (raw && typeof raw.x === "number" && typeof raw.y === "number") return raw;
  } catch {
    /* ignore */
  }
  return { x: window.innerWidth - 300, y: 120 };
}

/**
 * The scopes as a free, draggable floating window (position: fixed) instead of an overlay
 * pinned inside the preview frame — so it never covers the picture. Drag by the header;
 * position persists per device. Reads pixels from the same monitor <video> as before.
 */
export function ScopesFloat({
  videoRef,
  filter,
  onClose,
}: {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  filter: string;
  onClose: () => void;
}) {
  const t = useI18n();
  const [pos, setPos] = React.useState(readPos);
  const posRef = React.useRef(pos);
  posRef.current = pos;
  const dragRef = React.useRef<{ dx: number; dy: number } | null>(null);

  const clamp = React.useCallback((x: number, y: number) => {
    const w = 268;
    return {
      x: Math.min(Math.max(8, x), Math.max(8, window.innerWidth - w - 8)),
      y: Math.min(Math.max(8, y), Math.max(8, window.innerHeight - 80)),
    };
  }, []);

  // Keep the window on-screen: clamp the stored position on mount and whenever the viewport
  // shrinks, so a position saved on a wider window can't leave the panel (and its drag handle)
  // stranded off-screen.
  React.useEffect(() => {
    const reclamp = () => setPos((p) => clamp(p.x, p.y));
    reclamp();
    window.addEventListener("resize", reclamp);
    return () => window.removeEventListener("resize", reclamp);
  }, [clamp]);

  const onPointerDown = (event: React.PointerEvent) => {
    dragRef.current = { dx: event.clientX - pos.x, dy: event.clientY - pos.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: React.PointerEvent) => {
    if (!dragRef.current) return;
    const next = clamp(event.clientX - dragRef.current.dx, event.clientY - dragRef.current.dy);
    posRef.current = next; // keep the live value for persistence (state updates lag the event)
    setPos(next);
  };
  const onPointerUp = () => {
    if (!dragRef.current) return;
    dragRef.current = null;
    try {
      localStorage.setItem(POS_KEY, JSON.stringify(posRef.current));
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="fixed z-[80] w-[268px] select-none overflow-hidden rounded-lg border border-[rgb(255_255_255/0.14)] bg-[rgb(8_8_10/0.9)] backdrop-blur-[10px]" style={{ left: pos.x, top: pos.y }}>
      <div
        className="flex h-[26px] cursor-grab touch-none items-center gap-1.5 border-b border-[rgb(255_255_255/0.08)] bg-[rgb(255_255_255/0.05)] pl-2 pr-1.5 active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <GripHorizontal size={13} className="text-muted-foreground" />
        <span className="flex-1 text-[11px] font-medium text-foreground">{t("scopes")}</span>
        <button type="button" className="inline-flex h-[18px] w-[18px] items-center justify-center rounded text-muted-foreground hover:bg-[rgb(255_255_255/0.1)] hover:text-foreground" onClick={onClose} aria-label={t("close")}>
          <X size={13} />
        </button>
      </div>
      <div className="p-1.5">
        <Scopes videoRef={videoRef} filter={filter} />
      </div>
    </div>
  );
}
