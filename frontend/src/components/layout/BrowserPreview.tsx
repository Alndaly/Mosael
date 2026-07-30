import React from "react";
import { Loader2, MonitorPlay, Square, X } from "lucide-react";

import { useI18n } from "@/app/preferences";

/**
 * 自动化任务的**步骤指示**。
 *
 * 画面本身不再由这里负责:发布任务与 RPA / 智能体会话的视图现在都挂成主窗口右下角的悬浮面板
 * (见 electron/publish/accountViews.ts 的 PANEL),用户看到的是**真实渲染的页面**,不是截图镜像。
 * 保留这个条子是因为画面看不出语义 —— 光看页面分不清「正在上传」和「卡住了」,步骤名才分得清;
 * 面板挂不上(超出上限 / 窗口没了)时它也是唯一的进度来源。dataUrl 因此现在通常是空的。
 * 停帧 ~3s 无新帧就淡出;可手动关掉。非 Electron 环境 window.openStudioBrowser 不存在,组件自然什么都不渲染。
 */
export function BrowserPreview() {
  const t = useI18n();
  const [frame, setFrame] = React.useState<LiveViewFrame | null>(null);
  // 关掉的是**哪一个会话**。此前存的是布尔值并在每帧 setDismissed(false),而发布任务是 1 帧/秒 ——
  // 于是点了 X 会在下一帧被撤销,面板根本关不掉。改成记住被关掉的 sessionId:同一条任务后续的帧
  // 一律不再弹出,换了别的会话(新任务)才重新出现。
  const [dismissedSession, setDismissedSession] = React.useState<string | null>(null);
  const hideTimer = React.useRef<number | null>(null);

  React.useEffect(() => {
    const bridge = window.openStudioBrowser;
    if (!bridge) return;
    const off = bridge.onFrame((next) => {
      setFrame(next);
      if (hideTimer.current) window.clearTimeout(hideTimer.current);
      hideTimer.current = window.setTimeout(() => setFrame(null), 3000);
    });
    return () => {
      off?.();
      if (hideTimer.current) window.clearTimeout(hideTimer.current);
    };
  }, []);

  if (!frame || frame.sessionId === dismissedSession) return null;
  const settled = frame.settled === true;
  return (
    <div className="fixed bottom-4 right-4 z-[80] w-[320px] max-w-[calc(100vw-32px)] overflow-hidden rounded-lg border border-border-strong bg-panel shadow-[var(--shadow-raised)]">
      <div className="flex items-center gap-1.5 border-b border-border px-2.5 py-1.5">
        <MonitorPlay size={13} className="shrink-0 text-primary" />
        <span className="shrink-0 text-[12px] font-semibold">{t("browserPreviewTitle")}</span>
        {frame.label && (
          <span className="min-w-0 flex-1 truncate text-[11.5px] tabular-nums text-muted-foreground">
            {frame.label}
          </span>
        )}
        {!frame.label && <span className="min-w-0 flex-1" />}
        <button
          type="button"
          className="grid h-5 w-5 shrink-0 place-items-center rounded border-0 bg-transparent text-muted-foreground transition-colors hover:text-foreground"
          aria-label={t("close")}
          onClick={() => setDismissedSession(frame.sessionId)}
        >
          <X size={12} />
        </button>
      </div>
      {frame.dataUrl ? (
        <img src={frame.dataUrl} alt="" className="block w-full bg-black" />
      ) : (
        // 后台视图取不到像素是常态(见 electron/publish/publishWorker.ts 的 LiveMirror),此时面板退化成「步骤 + 地址」。
        // 整块消失反而更糟:那正是用户以为「卡死了」的时刻,更需要看到它还在跑。
        <div className="grid gap-1 px-2.5 py-3">
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            {/* 终态(成功/失败)就别再转圈了 —— 之前「失败」配着「后台运行中」的正文自相矛盾。 */}
            {settled ? (
              <Square size={12} className="shrink-0" />
            ) : (
              <Loader2 size={12} className="animate-openstudio-spin" />
            )}
            <span>{settled ? t("browserPreviewNoPixelsDone") : t("browserPreviewNoPixels")}</span>
          </div>
          {frame.url && <div className="truncate text-[11px] text-muted-foreground/80">{frame.url}</div>}
        </div>
      )}
    </div>
  );
}
