import React from "react";
import { Loader2, MonitorPlay, X } from "lucide-react";

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
  const [frame, setFrame] = React.useState<BrowserFrame | null>(null);
  const [dismissed, setDismissed] = React.useState(false);
  const hideTimer = React.useRef<number | null>(null);

  React.useEffect(() => {
    const bridge = window.openStudioBrowser;
    if (!bridge) return;
    const off = bridge.onFrame((next) => {
      setFrame(next);
      setDismissed(false);
      if (hideTimer.current) window.clearTimeout(hideTimer.current);
      hideTimer.current = window.setTimeout(() => setFrame(null), 3000);
    });
    return () => {
      off?.();
      if (hideTimer.current) window.clearTimeout(hideTimer.current);
    };
  }, []);

  if (!frame || dismissed) return null;
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
          onClick={() => setDismissed(true)}
        >
          <X size={12} />
        </button>
      </div>
      {frame.dataUrl ? (
        <img src={frame.dataUrl} alt="" className="block w-full bg-black" />
      ) : (
        // 后台视图取不到像素是常态(见 worker.ts LiveMirror),此时面板退化成「步骤 + 地址」。
        // 整块消失反而更糟:那正是用户以为「卡死了」的时刻,更需要看到它还在跑。
        <div className="grid gap-1 px-2.5 py-3">
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <Loader2 size={12} className="animate-openstudio-spin" />
            <span>{t("browserPreviewNoPixels")}</span>
          </div>
          {frame.url && <div className="truncate text-[11px] text-muted-foreground/80">{frame.url}</div>}
        </div>
      )}
    </div>
  );
}
