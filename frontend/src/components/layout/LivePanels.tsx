import React from "react";
import { GripVertical, MonitorPlay, X } from "lucide-react";

import { useI18n } from "@/app/preferences";

/**
 * 自动化任务悬浮卡片的**外壳**:圆角、边框、阴影、标题条,以及拖动 / 缩放 / 关闭。
 *
 * 内容本身是原生 `WebContentsView`(发布账号视图 / RPA 会话视图),由主进程挂在窗口里并叠成卡片堆。
 * 原生 View 画不了圆角与阴影(Electron 32 的 View 只有 setBackgroundColor / setBounds / setVisible),
 * 而子视图永远盖在宿主页面之上 —— 所以外壳只能画在**视图下方**:主进程把卡片外廓(含预留的标题条
 * 高度)经 publish:panels 下发,这里按同样的矩形铺一层圆角卡片,原生视图内缩 4px 嵌在里面,于是
 * 圆角边框在视图四周露出来。
 *
 * **交互只能放在标题条上。** 视图盖住了卡片的其余部分,鼠标事件到不了渲染层 —— 所以拖动手柄、
 * 缩放手柄、关闭按钮全在这 26px 里。拖到哪、缩多大由主进程持有(layout() 要用)并落盘,重启后接着用。
 */
export function LivePanels() {
  const t = useI18n();
  const [cards, setCards] = React.useState<LivePanelCard[]>([]);
  // 步骤文案按会话 id 归档:几何走 publish:panels,文案走 browser:frame,两条流在这里按 id 合起来。
  const [labels, setLabels] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    const off = window.openStudioPublish?.onPanels?.((next) => setCards(next));
    return () => off?.();
  }, []);

  React.useEffect(() => {
    const off = window.openStudioBrowser?.onFrame((frame) => {
      if (!frame.label) return;
      setLabels((prev) =>
        prev[frame.sessionId] === frame.label ? prev : { ...prev, [frame.sessionId]: frame.label! },
      );
    });
    return () => off?.();
  }, []);

  /**
   * 指针拖拽的公共骨架。拖动期间在 window 上收事件(pointer capture 到 window),因为指针一旦移到
   * 原生视图上方,卡片自己就再也收不到 move 了 —— 视图是原生子视图,盖在渲染层之上。
   */
  const startDrag = (
    event: React.PointerEvent,
    onMove: (dx: number, dy: number) => void,
  ): void => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startY = event.clientY;
    const move = (e: PointerEvent) => onMove(e.clientX - startX, e.clientY - startY);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  if (!cards.length) return null;
  // 拖动/缩放作用于**整个卡片堆**(它们共享一个锚点与尺寸),所以用最上面那张的几何做基准。
  const top = cards[cards.length - 1];

  return (
    <>
      {cards.map((card) => {
        const isTop = card.id === top.id;
        return (
          <div
            key={card.id}
            // 卡片是外壳,默认不抢点击;只有标题条上的手柄打开 pointer-events。
            className="pointer-events-none fixed z-[70] overflow-hidden border border-border-strong bg-panel shadow-[var(--shadow-raised)]"
            style={{
              left: card.x,
              top: card.y,
              width: card.width,
              height: card.height,
              borderRadius: card.radius,
            }}
          >
            <div
              className="flex items-center gap-1 pl-1.5 pr-1 text-[11px] text-muted-foreground"
              style={{ height: card.header }}
            >
              {/* 拖动:整条标题条都可拖(不只手柄图标),手感更好 */}
              <div
                className={
                  isTop
                    ? "pointer-events-auto flex min-w-0 flex-1 cursor-grab items-center gap-1 active:cursor-grabbing"
                    : "flex min-w-0 flex-1 items-center gap-1"
                }
                onPointerDown={
                  isTop
                    ? (event) =>
                        startDrag(event, (dx, dy) =>
                          void window.openStudioPublish?.setPanelLayout?.({ x: top.x + dx, y: top.y + dy }),
                        )
                    : undefined
                }
              >
                <MonitorPlay size={12} className="shrink-0 text-primary" />
                <span className="min-w-0 flex-1 truncate">{labels[card.id] ?? ""}</span>
              </div>

              {isTop && (
                /* 缩放:标题条右端的手柄。卡片其余边缘都被原生视图盖住,收不到鼠标,只能放这儿。 */
                <button
                  type="button"
                  aria-label={t("livePanelResize")}
                  className="pointer-events-auto grid h-5 w-4 shrink-0 cursor-nwse-resize place-items-center rounded border-0 bg-transparent text-muted-foreground hover:text-foreground"
                  onPointerDown={(event) =>
                    startDrag(event, (dx, dy) =>
                      void window.openStudioPublish?.setPanelLayout?.({
                        width: top.width + dx,
                        height: top.height + dy,
                      }),
                    )
                  }
                >
                  <GripVertical size={11} />
                </button>
              )}

              <button
                type="button"
                aria-label={t("close")}
                className="pointer-events-auto grid h-5 w-5 shrink-0 place-items-center rounded border-0 bg-transparent text-muted-foreground transition-colors hover:text-foreground"
                onClick={() => void window.openStudioPublish?.closePanel?.(card.id)}
              >
                <X size={11} />
              </button>
            </div>
          </div>
        );
      })}
    </>
  );
}
