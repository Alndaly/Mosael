import React from "react";
import { Loader2, MonitorPlay, Square, X } from "lucide-react";

import { useI18n } from "@/app/preferences";

/**
 * 自动化浏览器实时预览:RPA / 智能体的会话视图是离屏的,发布任务的账号视图跑任务时也不在窗口里,
 * 用户否则完全看不到它在做什么。两者都经 window.openStudioBrowser.onFrame 把帧推来(~1–2fps),
 * 这里在右下角浮现镜像画面。发布任务还会带 label(「B站 · 上传视频」)——光看画面分不清「正在上传」
 * 和「卡住了」,步骤名才是这个窗口真正的价值。
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
