import { RefreshCw } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";

import { restartForStaleMain, useMainStale } from "./mainStale";

/**
 * 浏览器会话顶栏里的「需要重启」小标记(带点的重启图标)。窗口底部那条「主进程代码已更新」的提示在浏览器会话
 * 里被原生网页视图盖住了,顶栏得常驻一个看得见的记号。主进程过期才出,悬停说明为什么;能替你重启(经 pnpm dev
 * 的 dev-loop 拉起)时点一下就重启,不能时点不了、只给说明。正式打包的应用永远不出(见 mainStale)。
 */
export function MainStaleBadge() {
  const t = useI18n();
  const { files, canRestart } = useMainStale();
  if (!files.length) return null;
  return (
    <IconButton
      unstyled
      type="button"
      data-main-stale-badge=""
      className="relative inline-flex h-7 w-7 flex-none cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-muted-foreground [-webkit-app-region:no-drag] enabled:hover:bg-secondary enabled:hover:text-foreground disabled:cursor-default"
      label={t(canRestart ? "mainStaleText" : "mainStaleManual")}
      hint={canRestart ? t("mainStaleBadgeHint") : undefined}
      disabled={!canRestart}
      disabledReason={canRestart ? undefined : t("mainStaleCannotRestart")}
      onClick={() => restartForStaleMain()}
    >
      <RefreshCw size={14} />
      <span aria-hidden className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-warning" />
    </IconButton>
  );
}
