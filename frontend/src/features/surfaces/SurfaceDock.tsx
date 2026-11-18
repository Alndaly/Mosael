import React from "react";
import { X } from "lucide-react";

import type { PageContext } from "@/app/pages";
import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { SurfaceHost } from "@/features/surfaces/SurfaceHost";
import type { StudioView } from "@/components/layout/navLabels";

/**
 * AI Studio 的侧栏 surface。它不是第二套页面：内容仍由 SurfaceHost 渲染，
 * 只是把同一个页面放进一个可关闭的停靠层里，聊天和会话列表不卸载。
 */
export function SurfaceDock({
  view,
  context,
  onClose,
}: {
  view: StudioView;
  context: PageContext;
  onClose: () => void;
}) {
  const t = useI18n();
  return (
    <aside
      data-surface-dock=""
      className="absolute inset-y-0 right-0 z-40 flex w-[min(540px,100%)] min-w-0 flex-col border-l border-divider bg-workspace-panel shadow-[var(--shadow-raised)]"
      aria-label={t("surfacePanel")}
    >
      <div className="flex min-h-14 shrink-0 items-center justify-between gap-2 border-b border-divider px-4">
        <Truncate as="h2" className="m-0 text-ui-sm font-semibold text-foreground">{t("homeProjectsTitle")}</Truncate>
        <IconButton variant="ghost" size="icon-sm" label={t("close")} onClick={onClose}>
          <X />
        </IconButton>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        <SurfaceHost view={view} context={context} loadingLabel={t("pageLoading")} />
      </div>
    </aside>
  );
}
