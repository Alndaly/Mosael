import { toast } from "sonner";

import type { StudioView } from "@/components/layout/navLabels";
import { RailDivider } from "@/components/layout/RailDivider";
import {
  shortcutIcon,
  shortcutLabel,
  useSidebarShortcuts,
  type SidebarShortcut,
} from "@/components/layout/sidebarShortcuts";
import { IconButton } from "@/components/ui/icon-button";
import { useI18n } from "@/app/preferences";
import { openWorkbench, workbenchAvailable } from "@/features/plugins/workbench/workbenchSession";

/** 侧栏上那一组图标键。空着就不占位置。 */
export function SidebarShortcutButtons({
  workspaceId,
  onViewChange,
  compact = false,
}: {
  workspaceId: string;
  onViewChange: (view: StudioView) => void;
  compact?: boolean;
}) {
  const t = useI18n();
  const shortcuts = useSidebarShortcuts();
  if (shortcuts.length === 0) return null;
  const run = async (shortcut: SidebarShortcut) => {
    if (shortcut.kind === "view") {
      onViewChange(shortcut.view);
      return;
    }
    if (workbenchAvailable()) {
      const result = await openWorkbench(
        { instanceId: shortcut.instanceId, instanceName: shortcut.instanceName, workspaceId, url: shortcut.url },
        {},
      );
      if (!result.ok) {
        toast.error(t("sidebarShortcutOpenFailed").replace("{error}", result.error || t("workflowWorkbenchFailed")));
      }
      return;
    }
    if (shortcut.url) window.open(shortcut.url, "_blank", "noopener,noreferrer");
  };
  return (
    <>
    <div
      data-sidebar-shortcuts=""
      className={`grid shrink-0 gap-1 ${compact ? "grid-cols-1" : ""}`}
      style={compact ? undefined : { gridTemplateColumns: `repeat(${Math.min(shortcuts.length, 4)}, minmax(0, 1fr))` }}
    >
      {shortcuts.map((shortcut) => {
        const Icon = shortcutIcon(shortcut);
        return (
          <IconButton
            key={shortcut.id}
            variant="secondary"
            size="icon-sm"
            className="w-full bg-accent text-primary hover:bg-accent hover:text-primary"
            label={shortcutLabel(shortcut, t)}
            onClick={() => void run(shortcut)}
          >
            <Icon size={15} />
          </IconButton>
        );
      })}
    </div>
    {/* 和导航里的分隔线同一条(此前这里是贯穿整宽的 border-b) */}
    <RailDivider />
    </>
  );
}
