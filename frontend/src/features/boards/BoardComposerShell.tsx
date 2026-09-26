import React from "react";
import { NodeToolbar, Position } from "@xyflow/react";
import { ArrowUp, Loader2, SlidersHorizontal, type LucideIcon } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { CANVAS_WINDOW_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import { MODAL_SURFACE } from "@/components/ui/floating";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { BOARD_NODE_PANEL_OFFSET } from "@/features/boards/boardLayout";
import { cn } from "@/lib/utils";

/**
 * 画板上每一格的面板**共用的一个壳**:生成、写字、念、截一段、跑一个工具,长的都是这一个样子。
 *
 * 此前五块面板各写各的外框:宽度 400 / 420 / 560,内边距 p-2 / p-3,发送键有圆的、有带字的胶囊,
 * 工具格那块还是一列带大标签的表单 —— 同一张画布上并排着两种视觉语言,工具格看着像缩小的工作流节点。
 * 画板自己的语言照图片 / 视频格的面板(用户眼里「画板原生」的那一块)定:
 *
 *   ┌───────────────────────────────┐
 *   │ [上游芯片] [挂上的素材]          │  ← upstream(可选):连进来的东西,一排芯片
 *   │ 提示词 / 要念的字 / 剪辑轨 …      │  ← children:正文
 *   ├───────────────────────────────┤
 *   │ 模型▾ 目标语言▾  ⚙参数     (↑)  │  ← bar + settings + trailing + send:钉在底边
 *   └───────────────────────────────┘
 *
 * **正文滚、底栏钉住**(`grid-rows-[minmax(0,1fr)_auto]`,两个轴都声明 —— 见 design/gridAxes):展开得再多,
 * 发送键也不会被挤出面板。**正文真的会滚时才吞滚轮**(`nowheel`,见 canvasWheelPassthrough):一块内容没满的
 * 面板不该是画布上一片滚不动的死区。
 */
export type ComposerWidth = "md" | "lg";

/** 两档宽:带参考素材槽和一长串参数的生成面板要宽一些,别的都是一档。 */
const WIDTH: Record<ComposerWidth, string> = {
  md: "w-[440px]",
  lg: "w-[560px]",
};

/**
 * 底栏里一枚设置芯片的触发器(配 `size="sm"`,和「参数」、发送键同高):无边框、按内容取宽、
 * 悬停才有底色。模型、音色、目标语言都是这一枚 —— 一行里不混两种控件。
 */
export const BAR_PICKER =
  "w-auto min-w-0 max-w-[min(15rem,45%)] shrink gap-1 border-0 bg-transparent px-2 text-ui-xs text-muted-foreground shadow-none transition-colors hover:bg-secondary data-[state=open]:text-foreground";

export interface ComposerSend {
  /** 按钮说的那个动作(生成、写、念、截取、运行)—— 读屏和悬停都读它。 */
  label: string;
  onSend: () => void;
  disabled: boolean;
  /** 正在提交 / 正在跑:转圈。 */
  working: boolean;
  /** 默认是向上的箭头(发出去);截一段用剪刀这类「这一下做什么」更清楚的。 */
  icon?: LucideIcon;
  /** 悬停时多说的一句(每跑一次结果都新建在右边 ……)。 */
  hint?: string;
  /** 正文里按 ⌘↵ 也能发(提示词编辑器、要念的字)—— 悬停时说一声。 */
  shortcut?: boolean;
}

export function BoardComposerShell({
  nodeId,
  name,
  width = "md",
  upstream,
  children,
  bar,
  settings,
  trailing,
  send,
}: {
  /** 挂在哪一格下面。 */
  nodeId: string;
  /** 这是哪一块面板(`data-board-composer`)—— 测试和样式钩子。 */
  name: string;
  width?: ComposerWidth;
  /** 连进来的上游、挂上的素材:一排芯片,在正文最上面。 */
  upstream?: React.ReactNode;
  /** 正文。 */
  children?: React.ReactNode;
  /** 底栏左边的设置芯片:模型、音色、目标语言 ……(常用、必填的那几项)。 */
  bar?: React.ReactNode;
  /** 其余设置:收进「参数」弹层。`attention` = 里面有必填的还空着(按钮上一个点)。 */
  settings?: { content: React.ReactNode; attention?: boolean } | null;
  /** 发送键左边那一小格(一次几张)。 */
  trailing?: React.ReactNode;
  /** 圆形的发送键。不给 = 这会儿发不了(没有模型、工具用不了),底栏只留说明。 */
  send?: ComposerSend | null;
}) {
  const body = React.useRef<HTMLDivElement | null>(null);
  const scrolls = useOverflows(body);
  return (
    <NodeToolbar nodeId={nodeId} isVisible position={Position.Bottom} offset={BOARD_NODE_PANEL_OFFSET}>
      <div
        data-board-composer={name}
        data-width={width}
        className={cn(
          CANVAS_WINDOW_SURFACE_CLASS,
          "nodrag nopan grid max-h-[min(560px,70vh)] max-w-[calc(100vw-2rem)] grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)_auto] overflow-hidden",
          WIDTH[width],
        )}
      >
        <div
          ref={body}
          data-board-composer-body=""
          className={cn("grid min-h-0 content-start gap-2 overflow-y-auto px-3 pb-2 pt-3", scrolls && "nowheel")}
        >
          {upstream ? (
            <div data-board-composer-upstream="" className="flex min-w-0 flex-wrap items-center gap-1 border-b border-border pb-1.5">
              {upstream}
            </div>
          ) : null}
          {children}
        </div>
        <div data-board-composer-bar="" className="flex min-w-0 items-center gap-1 border-t border-divider px-3 py-2">
          {bar}
          {settings ? <SettingsButton attention={Boolean(settings.attention)}>{settings.content}</SettingsButton> : null}
          <span className="ml-auto flex shrink-0 items-center gap-1">
            {trailing}
            {send ? <SendButton {...send} /> : null}
          </span>
        </div>
      </div>
    </NodeToolbar>
  );
}

/** 正文此刻是不是真的装不下(会滚)。量不了(测试环境没有 ResizeObserver)就当不会滚。 */
function useOverflows(ref: React.RefObject<HTMLDivElement | null>): boolean {
  const [overflows, setOverflows] = React.useState(false);
  const measure = React.useCallback(() => {
    const element = ref.current;
    if (element) setOverflows(element.scrollHeight > element.clientHeight + 1);
  }, [ref]);
  //: 内容变了(展开了一段、挂上一张图)在每次渲染后量;面板被视口压矮了由 ResizeObserver 报。
  React.useLayoutEffect(measure);
  React.useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, measure]);
  return overflows;
}

/** 「参数」:底栏放不下的那些设置。和图片 / 视频格那块面板同一个按钮、同一种弹层。 */
function SettingsButton({ attention, children }: { attention: boolean; children: React.ReactNode }) {
  const t = useI18n();
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("boardGenerationSettings")}
          data-board-composer-settings=""
          data-attention={attention ? "true" : undefined}
          className="relative flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-md px-2 text-ui-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <SlidersHorizontal size={14} />
          <span>{t("boardGenerationSettings")}</span>
          {attention ? <span aria-hidden className="absolute right-1 top-1.5 size-1.5 rounded-full bg-primary" /> : null}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        side="top"
        className={cn(MODAL_SURFACE, "nodrag nopan nowheel grid max-h-[min(440px,calc(100dvh-32px))] w-[360px] gap-3 overflow-y-auto rounded-xl p-4")}
      >
        <span className="text-ui-sm font-medium">{t("boardGenerationSettings")}</span>
        {children}
      </PopoverContent>
    </Popover>
  );
}

/** 圆形的发送键 —— 每一块面板都是这一枚。 */
function SendButton({ label, onSend, disabled, working, icon: Icon = ArrowUp, hint, shortcut = false }: ComposerSend) {
  const off = disabled || working;
  const title = [hint ? `${label} · ${hint}` : label, shortcut ? "⌘↵" : ""].filter(Boolean).join("  ");
  return (
    <button
      type="button"
      data-board-composer-send=""
      aria-label={label}
      title={title}
      disabled={off}
      onClick={onSend}
      className={cn(
        "grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors",
        off ? "cursor-not-allowed bg-secondary text-muted-foreground" : "cursor-pointer bg-action text-action-foreground hover:opacity-90",
      )}
    >
      {working ? <Loader2 size={13} className="animate-spin" /> : <Icon size={13} />}
    </button>
  );
}
