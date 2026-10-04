import React from "react";
import { RefreshCw, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";

import { restartForStaleMain, useMainStale } from "./mainStale";

/**
 * 开发时主进程过期的提示:「主进程代码已更新,重启后生效」,带「重启」。不打扰 —— 窗口底部正中一条小提示,不抢
 * 焦点、不挡操作,「先不重启」就收起,之后又有产物变了再出。没法替用户重启(不是经 pnpm dev 拉起的)时只说要
 * 重启。正式打包的应用永远不出(见 mainStale)。
 */
export function MainStaleNotice() {
  const t = useI18n();
  const { files, canRestart } = useMainStale();
  const [dismissed, setDismissed] = React.useState("");
  const key = files.join(",");
  if (!files.length || key === dismissed) return null;
  return (
    <div
      role="status"
      data-main-stale=""
      className="fixed bottom-4 left-1/2 z-[210] flex max-w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 items-center gap-2 rounded-lg border border-border bg-popover px-3 py-2 text-ui-sm text-popover-foreground shadow-[var(--shadow-raised)]"
    >
      <RefreshCw size={14} className="flex-none text-muted-foreground" />
      <Truncate hint={t("mainStaleFiles").replace("{files}", files.join("、"))}>
        {t(canRestart ? "mainStaleText" : "mainStaleManual")}
      </Truncate>
      {canRestart && (
        <Button size="xs" onClick={() => restartForStaleMain()}>
          {t("mainStaleRestart")}
        </Button>
      )}
      <IconButton size="icon-xs" label={t("mainStaleDismiss")} onClick={() => setDismissed(key)}>
        <X />
      </IconButton>
    </div>
  );
}
