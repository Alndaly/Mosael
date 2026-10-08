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
    <IconButton variant="ghost" size="icon-sm" label={mode} aria-pressed={active} onClick={onMode}><Icon size={14} /></IconButton>
    {/* 名字说的是点了会怎样(「隐藏评论」/「显示评论」),所以它是个动作按钮,不带 aria-pressed:此前两样都带,
        评论正显示着时读屏念「隐藏评论,已按下」,意思正相反。眼睛的开合给看得见的人说现在的状态。 */}
    <IconButton variant="ghost" size="icon-sm" label={visibility} onClick={onVisible}>{visible ? <Eye size={12} /> : <EyeOff size={12} />}</IconButton>
  </div>;
}
