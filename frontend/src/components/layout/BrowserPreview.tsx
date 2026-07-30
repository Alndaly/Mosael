import React from "react";
import { Loader2, MonitorPlay, Square, X } from "lucide-react";

import { useI18n } from "@/app/preferences";

/**
 * **没挂上悬浮面板**的自动化任务的进度条子。
 *
 * 挂上了面板的任务由 LivePanels 负责:那是真实渲染的页面 + 卡片标题条上的步骤名。而面板有数量上限
 * (见 accountViews 的 MAX_PANELS),超额的会话、以及宿主窗口不在时的任务,一个像素都拿不到 ——
 * 那种情况下这个条子是唯一的进度来源,所以留着。已挂面板的会话在这里会被跳过,免得和卡片堆重叠。
 * dataUrl 因此通常是空的(取像需要视图参与合成,而没挂面板就不合成)。
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
  // 已挂面板的会话交给 LivePanels;这里只补它覆盖不到的那些。
  const [panelled, setPanelled] = React.useState<Set<string>>(new Set());

  React.useEffect(() => {
    const off = window.openStudioPublish?.onPanels?.((cards) =>
      setPanelled(new Set(cards.map((card) => card.id))),
    );
    return () => off?.();
  }, []);

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

  if (!frame || frame.sessionId === dismissedSession || panelled.has(frame.sessionId)) return null;
  const settled = frame.settled === true;
  return (
    <div style={{ bottom: panelled.size ? 16 + 244 + 12 : 16 }}
      className="fixed right-4 z-[80] w-[320px] max-w-[calc(100vw-32px)] overflow-hidden rounded-lg border border-border-strong bg-panel shadow-[var(--shadow-raised)]">
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
