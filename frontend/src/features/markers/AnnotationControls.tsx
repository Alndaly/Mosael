import { Eye, EyeOff, Flag, MessageSquarePlus } from "lucide-react";
import { Button } from "@/components/ui/button";
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
  return <div className="inline-flex h-8 items-center gap-0.5 border-r border-divider pr-1 mr-1" role="group" aria-label={mode}>
    <Button variant={active ? "secondary" : "ghost"} size="icon-sm" aria-label={mode} title={mode} aria-pressed={active} onClick={onMode}><Icon size={14} /></Button>
    <Button variant="ghost" size="icon-sm" aria-label={visibility} title={visibility} aria-pressed={visible} onClick={onVisible}>{visible ? <Eye size={12} /> : <EyeOff size={12} />}</Button>
  </div>;
}
