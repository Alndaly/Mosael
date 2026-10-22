import React from "react";
import { CircleStop, Hand, ShieldAlert } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Computer Use 的「被控制中」提示条(ADR 0075 安全 2/3)。
 *
 * 那件事发生在**渲染层看不见的地方**(Electron 主进程在替模型点 Mosael 自己的窗口),所以
 * 这里必须有一个一眼看得见的状态:屏幕四角描边与托盘换色是环境里的,这一条是窗口里的。
 * 急停的第二个出口也在这儿(第一个是全局热键 ⌘⇧Esc,不依赖 App 在前台)。
 *
 * 状态来自主进程的一条事件(见 computerUseGuard.cjs):`active` = 正在被操作,`stopped` = 已急停
 * (之后再来的动作全被挡住,直到用户点「恢复」)。
 */
export function ComputerUseBanner() {
  const t = useI18n();
  const [state, setState] = React.useState<{ active: boolean; stopped: boolean } | null>(null);

  React.useEffect(() => {
    const bridge = window.mosaelDesktop;
    if (!bridge?.onComputerUseState) return;
    return bridge.onComputerUseState(setState);
  }, []);

  if (!state || (!state.active && !state.stopped)) return null;

  const running = state.active && !state.stopped;
  const stop = () => void window.mosaelDesktop?.stopComputerUse?.();
  const resume = () => void window.mosaelDesktop?.resumeComputerUse?.();

  return (
    <div
      role="status"
      aria-live="polite"
      data-computer-use-banner={running ? "active" : "stopped"}
      className={cn(
        // 左下角:提示条在右下、悬浮面板也在右下,这里错开;整条不挡操作(只有按钮可点)。
        "fixed bottom-4 left-4 z-[80] flex max-w-[min(420px,calc(100vw-32px))] items-center gap-2 rounded-lg border px-3 py-2 text-ui-sm shadow-[var(--shadow-raised)] backdrop-blur",
        running
          ? "border-destructive/40 bg-[color-mix(in_srgb,var(--destructive)_12%,var(--panel))] text-destructive"
          : "border-warning/40 bg-[color-mix(in_srgb,var(--warning)_14%,var(--panel))] text-warning",
      )}
    >
      {running ? <ShieldAlert size={15} className="shrink-0" aria-hidden /> : <Hand size={15} className="shrink-0" aria-hidden />}
      <span className="min-w-0 flex-1">
        {running ? t("computerUseActive") : t("computerUseStopped")}
        <span className="ml-1.5 text-ui-xs opacity-70">{running ? t("computerUseHint") : ""}</span>
      </span>
      {running ? (
        <Button variant="outline" size="xs" className="shrink-0" onClick={stop}>
          <CircleStop size={13} /> {t("computerUseStopAction")}
        </Button>
      ) : (
        <Button variant="outline" size="xs" className="shrink-0" onClick={resume}>
          {t("computerUseResumeAction")}
        </Button>
      )}
    </div>
  );
}
