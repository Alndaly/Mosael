import { Eye, EyeOff, Flag, MessageSquarePlus } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";
import { useI18n } from "@/app/preferences";

/** Editing mode and visibility are separate: hiding never mutates annotations. */
export function AnnotationControls({ kind, active, visible, onMode, onVisible }: {
  kind: "marker" | "comment"; active: boolean; visible: boolean;
  onMode: () => void; onVisible: () => void;
}) {
  const t = useI18n();
  const Icon = kind === "marker" ? Flag : MessageSquarePlus;
  const mode = t(kind === "marker" ? "markerMode" : "boardCommentMode");
  const visibility = t(kind === "marker" ? visible ? "markersHide" : "markersShow" : visible ? "commentsHide" : "commentsShow");
  return <div className="inline-flex h-8 shrink-0 items-center gap-0.5" role="group" aria-label={mode}>
    <IconButton variant={active ? "secondary" : "ghost"} size="icon-sm" label={mode} aria-pressed={active} onClick={onMode}><Icon size={14} /></IconButton>
    <IconButton variant="ghost" size="icon-sm" label={visibility} aria-pressed={visible} onClick={onVisible}>{visible ? <Eye size={12} /> : <EyeOff size={12} />}</IconButton>
  </div>;
}
