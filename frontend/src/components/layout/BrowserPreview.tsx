import React from "react";
import { MonitorPlay, X } from "lucide-react";

import { useI18n } from "@/app/preferences";

/**
 * 自动化浏览器实时预览:RPA / 智能体驱动的浏览器是离屏的,用户否则看不到。Electron 的浏览器 worker
 * 把「最近操作的会话」定时截帧(~2fps)经 window.mibuBrowser.onFrame 推来,这里在右下角浮现镜像画面。
 * 停帧 ~3s 无新帧就淡出;可手动关掉。非 Electron 环境 window.mibuBrowser 不存在,组件自然什么都不渲染。
 */
export function BrowserPreview() {
  const t = useI18n();
  const [frame, setFrame] = React.useState<BrowserFrame | null>(null);
  const [dismissed, setDismissed] = React.useState(false);
  const hideTimer = React.useRef<number | null>(null);

  React.useEffect(() => {
    const bridge = window.mibuBrowser;
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
        <MonitorPlay size={13} className="text-primary" />
        <span className="min-w-0 flex-1 truncate text-[12px] font-semibold">{t("browserPreviewTitle")}</span>
        <button
          type="button"
          className="grid h-5 w-5 shrink-0 place-items-center rounded border-0 bg-transparent text-muted-foreground transition-colors hover:text-foreground"
          aria-label={t("close")}
          onClick={() => setDismissed(true)}
        >
          <X size={12} />
        </button>
      </div>
      <img src={frame.dataUrl} alt="" className="block w-full bg-black" />
    </div>
  );
}
