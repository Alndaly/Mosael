import React from "react";
import { X } from "lucide-react";
import { useI18n } from "@/app/preferences";

/** Shared hint and Escape behavior for both annotation modes and canvases. */
export function AnnotationModeHint({ kind, onExit }: { kind: "comment" | "marker"; onExit?: () => void }) {
  const t = useI18n();
  React.useEffect(() => {
    const exit = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault(); event.stopPropagation(); onExit?.();
    };
    window.addEventListener("keydown", exit, true);
    return () => window.removeEventListener("keydown", exit, true);
  }, [onExit]);
  const exitLabel = t(kind === "comment" ? "boardExitCommentMode" : "markerExitMode");
  return <div data-board-comment-mode-hint="" className="absolute left-1/2 top-16 z-30 flex h-[42px] max-w-[calc(100%-24px)] -translate-x-1/2 items-center rounded-full border border-primary/30 bg-panel/80 py-1 pl-3 pr-1.5 text-ui-xs text-foreground shadow-[var(--shadow-panel)] backdrop-blur-xl"
    onPointerDown={event => event.stopPropagation()} onMouseDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}>
    <span className="shrink-0 font-semibold text-primary">{t(kind === "comment" ? "boardCommentMode" : "markerMode")}</span>
    <span className="mx-1.5 text-muted-foreground">·</span>
    <span className="truncate text-muted-foreground">{t(kind === "comment" ? "boardCommentModeHint" : "markerModeHint")}</span>
    <kbd className="ml-2 text-ui-2xs text-muted-foreground">Esc</kbd>
    <button type="button" className="ml-1 grid size-7 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground" title={exitLabel} aria-label={exitLabel} onClick={onExit}><X size={14} /></button>
  </div>;
}
