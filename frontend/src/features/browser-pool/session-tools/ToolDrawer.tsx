import React from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { useI18n } from "@/app/preferences";
import { APP_CHROME } from "@/components/ui/appChrome";
import { HintRegion } from "@/components/ui/tooltip";

const DRAWER_REGION = {};

/** 侧栏宽度。开着侧栏时网页右侧让出这么宽(主进程 setShellInset)。 */
export const DRAWER_WIDTH = 360;

/**
 * 顶栏页面工具的侧栏(视频清单、图片网格)。
 *
 * 网页是原生视图,永远盖在 DOM 上面 —— 侧栏画在网页「旁边」而不是「上面」:开着的时候主进程把网页右侧让出
 * DRAWER_WIDTH 这么宽(setInset),网页照常排版、照常能点,只是窄一点;关上就还回去。
 *
 * **挂到 body 上**(portal),不留在顶栏里:顶栏带 backdrop-filter,而带滤镜的元素会成为 fixed 子元素的
 * 定位容器 —— 侧栏的 top/bottom 于是按 56px 高的顶栏去算,只剩一条标题露在外面(真 Electron 里实测如此)。
 */
export function ToolDrawer({
  top,
  title,
  onClose,
  actions,
  footer,
  children,
}: {
  /** 顶栏多高:侧栏从顶栏下沿开始,和网页同一个上沿。 */
  top: number;
  title: string;
  onClose: () => void;
  actions?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  const t = useI18n();
  React.useEffect(() => {
    void window.mosaelPageTools?.setInset(DRAWER_WIDTH);
    return () => void window.mosaelPageTools?.setInset(0);
  }, []);
  // 侧栏也是窗口外壳(见 APP_CHROME):底下的弹窗不因为点它而关掉,它点得动、拿得到焦点。
  return createPortal(
    <HintRegion.Provider value={DRAWER_REGION}>
    <aside
      {...APP_CHROME}
      data-page-tools-drawer=""
      aria-label={title}
      style={{ top, width: DRAWER_WIDTH }}
      className="fixed bottom-0 right-0 z-[200] flex flex-col border-l border-border bg-panel"
    >
      <header className="flex h-11 flex-none items-center gap-2 border-b border-border px-3">
        <Truncate as="h2" className="m-0 flex-1 text-ui-sm font-semibold">{title}</Truncate>
        {actions}
        <IconButton size="icon-xs" onClick={onClose} label={t("browserToolsClose")}>
          <X />
        </IconButton>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">{children}</div>
      {footer && <footer className="flex flex-none items-center justify-end gap-2 border-t border-border p-3">{footer}</footer>}
    </aside>
    </HintRegion.Provider>,
    document.body,
  );
}
