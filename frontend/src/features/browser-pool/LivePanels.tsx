import React from "react";
import { MonitorPlay, Volume2, VolumeX, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";

import { PanelResizeHandles } from "./PanelResizeHandles";
import { PanelTitle } from "./PanelTitle";

/** 指针离开后手柄再撑这么久才淡出。指针在卡片那圈边与网页之间穿过时,DOM 的悬停和主进程报的
 *  网页悬停会有几毫秒都是假 —— 不撑这一下,手柄会跟着闪。 */
const HANDLES_LINGER_MS = 300;

/**
 * 自动化任务悬浮卡片的**外壳**:圆角、边框、阴影、标题条,以及拖动 / 缩放 / 关闭。
 *
 * 内容本身是原生 `WebContentsView`(发布账号视图 / RPA 会话视图),由主进程挂在窗口里并叠成卡片堆。
 * 原生 View 画不了圆角与阴影(Electron 32 的 View 只有 setBackgroundColor / setBounds / setVisible),
 * 而子视图永远盖在宿主页面之上 —— 所以外壳只能画在**视图下方**:主进程把卡片外廓(含预留的标题条
 * 高度)经 publish:panels 下发,这里按同样的矩形铺一层圆角卡片,原生视图内缩 4px 嵌在里面,于是
 * 圆角边框在视图四周露出来。
 *
 * **交互只能放在网页以外的地方。** 视图盖住了卡片中间,鼠标事件到不了渲染层 —— 拖动、静音、关闭
 * 在 26px 的标题条上;缩放手柄在卡片四角四边那圈边上(见 PanelResizeHandles)。手柄平时不显示,
 * 指针停在这个浏览器上时才亮:卡片外壳上的悬停这里自己看得见,网页上的悬停由主进程随卡片报来
 * (`hovered`)。拖到哪、缩多大由主进程持有(layout() 要用)并落盘,重启后接着用。
 */
export function LivePanels() {
  const t = useI18n();
  const [cards, setCards] = React.useState<LivePanelCard[]>([]);
  // 步骤文案按会话 id 归档:几何走 publish:panels,文案走 browser:frame,两条流在这里按 id 合起来。
  const [labels, setLabels] = React.useState<Record<string, string>>({});
  // 指针在卡片外壳 / 手柄上(DOM 看得见的那部分)。
  const [pointerOver, setPointerOver] = React.useState(false);
  // 拖动或缩放进行中:手柄保持显示,全屏垫一层带对应光标的遮罩。
  const [dragCursor, setDragCursor] = React.useState<string | null>(null);

  React.useEffect(() => {
    const off = window.mosaelPublish?.onPanels?.((next) => {
      setCards(next);
      // 卡片全撤了,指针自然也不在上面了(卸载的元素不会补发离开事件)。
      if (!next.length) setPointerOver(false);
    });
    return () => off?.();
  }, []);

  React.useEffect(() => {
    const off = window.mosaelBrowser?.onFrame((frame) => {
      if (!frame.label) return;
      setLabels((prev) =>
        prev[frame.sessionId] === frame.label ? prev : { ...prev, [frame.sessionId]: frame.label! },
      );
    });
    return () => off?.();
  }, []);

  const handlesVisible = useLingering(
    pointerOver || dragCursor !== null || cards.some((card) => card.hovered),
    HANDLES_LINGER_MS,
  );

  /**
   * 指针拖拽的公共骨架。拖动期间在 window 上收事件(pointer capture 到 window),因为指针一旦移到
   * 原生视图上方,卡片自己就再也收不到 move 了 —— 视图是原生子视图,盖在渲染层之上。
   */
  const startDrag = (
    event: React.PointerEvent,
    cursor: string,
    onMove: (dx: number, dy: number) => void,
  ): void => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startY = event.clientY;
    setDragCursor(cursor);
    const move = (e: PointerEvent) => onMove(e.clientX - startX, e.clientY - startY);
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      setDragCursor(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  };

  if (!cards.length) return null;
  // 拖动/缩放作用于**整个卡片堆**(它们共享一个锚点与尺寸),所以用最上面那张的几何做基准。
  const top = cards[cards.length - 1];

  return (
    <div
      className="contents"
      onPointerEnter={() => setPointerOver(true)}
      onPointerLeave={() => setPointerOver(false)}
      // 卡片外壳、伸出卡片的手柄热区、拖动遮罩:按下与点击都不许漏到下面的工作流画布。
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
    >
      {cards.map((card) => {
        const isTop = card.id === top.id;
        return (
          <div
            key={card.id}
            // 原生视图只覆盖内容矩形。外壳若 pointer-events:none,标题间隙、圆角和 4px 内缩边框
            // 会直接点到下面的工作流画布。整个外壳承担命中屏障；内容区仍由上层原生视图接管。
            className="pointer-events-auto fixed z-[70] overflow-hidden border border-floating-border bg-panel shadow-[var(--shadow-raised)]"
            data-live-panel={card.id}
            style={{
              left: card.x,
              top: card.y,
              width: card.width,
              height: card.height,
              borderRadius: card.radius,
            }}
          >
            <div
              className="flex items-center gap-1 pl-1.5 pr-2 text-ui-xs text-muted-foreground"
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
                        startDrag(event, "grabbing", (dx, dy) =>
                          void window.mosaelPublish?.setPanelLayout?.({ x: top.x + dx, y: top.y + dy }),
                        )
                    : undefined
                }
              >
                <MonitorPlay size={12} className="shrink-0 text-primary" />
                <PanelTitle id={card.id} label={labels[card.id] ?? ""} />
                {card.pages > 1 && (
                  // 这个会话开着几个页面、当前在第几个(新窗口会进会话的页面列表并切过去)。
                  <Hint label={t("livePanelPages").replace("{page}", String(card.page)).replace("{pages}", String(card.pages))}>
                    <span data-live-panel-pages className="shrink-0 rounded bg-secondary px-1 tabular-nums text-muted-foreground">
                      {card.page}/{card.pages}
                    </span>
                  </Hint>
                )}
              </div>

              {isTop && (
                <IconButton
                  unstyled
                  type="button"
                  label={t(card.muted ? "livePanelUnmute" : "livePanelMute")}
                  aria-pressed={!card.muted}
                  className="pointer-events-auto grid h-5 w-5 shrink-0 place-items-center rounded border-0 bg-transparent text-muted-foreground transition-colors hover:text-foreground"
                  onClick={() => void window.mosaelPublish?.setPanelMuted?.(card.id, !card.muted)}
                >
                  {card.muted ? <VolumeX size={11} /> : <Volume2 size={11} />}
                </IconButton>
              )}

              <IconButton
                unstyled
                type="button"
                label={t("close")}
                className="pointer-events-auto grid h-5 w-5 shrink-0 place-items-center rounded border-0 bg-transparent text-muted-foreground transition-colors hover:text-foreground"
                onClick={() => void window.mosaelPublish?.closePanel?.(card.id)}
              >
                <X size={11} />
              </IconButton>
            </div>
          </div>
        );
      })}

      <PanelResizeHandles
        card={top}
        radius={top.radius}
        visible={handlesVisible}
        onResizeStart={startDrag}
        onResize={(handle, requested) => void window.mosaelPublish?.setPanelLayout?.({ handle, ...requested })}
      />

      {dragCursor && (
        // 拖动期间光标要一直是那个方向的样式,而不是随指针下面的画布元素变来变去。
        <div aria-hidden className="pointer-events-auto fixed inset-0 z-[71]" style={{ cursor: dragCursor }} />
      )}
    </div>
  );
}

/** `on` 一为真立刻为真;变假之后再撑 `ms` 才变假。 */
function useLingering(on: boolean, ms: number): boolean {
  const [lingering, setLingering] = React.useState(on);
  React.useEffect(() => {
    if (on) {
      setLingering(true);
      return;
    }
    const timer = window.setTimeout(() => setLingering(false), ms);
    return () => window.clearTimeout(timer);
  }, [on, ms]);
  return on || lingering;
}
