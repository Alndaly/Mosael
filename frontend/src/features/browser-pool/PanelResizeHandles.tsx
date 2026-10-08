import React from "react";

import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";

/**
 * 悬浮浏览器卡片四角、四边的缩放手柄。
 *
 * **为什么在边沿上**:卡片内容是原生视图(WebContentsView),盖在渲染层之上,落在网页上的鼠标事件
 * 渲染层一个也收不到。原生视图在卡片四周内缩了 4px(为了让圆角边框露出来),那圈边和卡片外侧几
 * 像素是渲染层收得到事件的地方 —— 热区就压在这里:里面一半落在那圈边上,外面一半伸出卡片。网页
 * 区域本身不让出任何一像素,照常可点可滚。
 *
 * 四角是可聚焦的按钮:有名字,聚焦后方向键缩放;角上画一段贴着卡片圆角的弧做角标。四边只是细热区
 * + 对应方向的光标 —— 键盘用四个角就够了,八个 Tab 停靠点太多。
 *
 * **缩放语义不在这里。** 这里只报「指针要的矩形」(起手时的卡片 + 指针位移,不带约束);尺寸是一个
 * 标量(宽高按页面比例联动)、拖角锚定对角、拖边锚定对边中点、上下限与窗口边界,都由主进程的
 * panelGeometry 定 —— 规则只有一份。
 */

type Corner = "nw" | "ne" | "sw" | "se";
type Edge = "n" | "e" | "s" | "w";
interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 边的热区:伸出卡片外几像素,再压进卡片那圈边几像素(= 原生视图的内缩,网页从这里往里开始)。 */
const EDGE_OUTSIDE = 4;
const EDGE_INSIDE = 4;
/** 角的热区比边大一圈,好抓。压进卡片的那部分在底部两角会被网页盖住一角,不影响:网页盖住的地方本来就该归网页。 */
const CORNER_OUTSIDE = 10;
const CORNER_INSIDE = 8;
/** 角标弧线:离卡片圆角多远、多粗。 */
const ARC_GAP = 3;
const ARC_STROKE = 3;
/** 方向键一步缩放多少(按住 Shift 走大步)。 */
const KEY_STEP = 16;
const KEY_STEP_LARGE = 64;

const CORNERS: Corner[] = ["nw", "ne", "sw", "se"];
const EDGES: Edge[] = ["n", "e", "s", "w"];

const RESIZE_CURSOR: Record<LivePanelHandle, string> = {
  n: "ns-resize",
  s: "ns-resize",
  e: "ew-resize",
  w: "ew-resize",
  nw: "nwse-resize",
  se: "nwse-resize",
  ne: "nesw-resize",
  sw: "nesw-resize",
};

const CORNER_LABEL: Record<Corner, MessageKey> = {
  nw: "livePanelResizeTopLeft",
  ne: "livePanelResizeTopRight",
  sw: "livePanelResizeBottomLeft",
  se: "livePanelResizeBottomRight",
};

const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

/** 起手时的卡片 + 指针位移 → 指针要的矩形:被拖的那条边 / 那两条边跟着指针走,其余不动。 */
function requestedRect(handle: LivePanelHandle, from: Rect, dx: number, dy: number): Rect {
  const rect = { x: from.x, y: from.y, width: from.width, height: from.height };
  if (handle.includes("w")) {
    rect.x += dx;
    rect.width -= dx;
  }
  if (handle.includes("e")) rect.width += dx;
  if (handle.includes("n")) {
    rect.y += dy;
    rect.height -= dy;
  }
  if (handle.includes("s")) rect.height += dy;
  return rect;
}

/** 这个角朝外的方向:东/南为正。 */
const outward = (corner: Corner): [number, number] => [corner.includes("e") ? 1 : -1, corner.includes("s") ? 1 : -1];

function edgeZone(edge: Edge, card: Rect): React.CSSProperties {
  const band = EDGE_OUTSIDE + EDGE_INSIDE;
  switch (edge) {
    case "n":
      return { left: card.x + CORNER_INSIDE, top: card.y - EDGE_OUTSIDE, width: card.width - CORNER_INSIDE * 2, height: band };
    case "s":
      return { left: card.x + CORNER_INSIDE, top: card.y + card.height - EDGE_INSIDE, width: card.width - CORNER_INSIDE * 2, height: band };
    case "w":
      return { left: card.x - EDGE_OUTSIDE, top: card.y + CORNER_INSIDE, width: band, height: card.height - CORNER_INSIDE * 2 };
    case "e":
      return { left: card.x + card.width - EDGE_INSIDE, top: card.y + CORNER_INSIDE, width: band, height: card.height - CORNER_INSIDE * 2 };
  }
}

function cornerZone(corner: Corner, card: Rect): React.CSSProperties {
  const [east, south] = outward(corner).map((sign) => sign > 0);
  return {
    left: east ? card.x + card.width - CORNER_INSIDE : card.x - CORNER_OUTSIDE,
    top: south ? card.y + card.height - CORNER_INSIDE : card.y - CORNER_OUTSIDE,
    width: CORNER_OUTSIDE + CORNER_INSIDE,
    height: CORNER_OUTSIDE + CORNER_INSIDE,
  };
}

/**
 * 角标:一段与卡片圆角同心、贴在卡片外侧的四分之一圆弧(iPadOS 窗口角那种)。整段都在卡片外,
 * 原生视图盖不到它。坐标以角热区按钮的左上角为原点。
 */
function CornerArc({ corner, radius }: { corner: Corner; radius: number }) {
  const [sx, sy] = outward(corner);
  // 卡片这个角的圆角圆心,换算到按钮坐标里。
  const cx = sx > 0 ? CORNER_INSIDE - radius : CORNER_OUTSIDE + radius;
  const cy = sy > 0 ? CORNER_INSIDE - radius : CORNER_OUTSIDE + radius;
  const r = radius + ARC_GAP;
  const path = `M ${cx + sx * r} ${cy} A ${r} ${r} 0 0 ${sx * sy > 0 ? 1 : 0} ${cx} ${cy + sy * r}`;
  return (
    <svg aria-hidden className="pointer-events-none absolute inset-0 size-full overflow-visible" fill="none">
      {/* 底下垫一圈背景色,画布是什么颜色都看得清 */}
      <path d={path} className="stroke-background" strokeWidth={ARC_STROKE + 2} strokeLinecap="round" />
      <path d={path} stroke="currentColor" strokeWidth={ARC_STROKE} strokeLinecap="round" />
    </svg>
  );
}

export function PanelResizeHandles({
  card,
  radius,
  visible,
  onResizeStart,
  onResize,
}: {
  /** 卡片堆最上面那张的外廓 —— 缩放作用于整堆,以它为准。 */
  card: Rect;
  radius: number;
  /** 指针在这个浏览器上(含网页区域)、或正拖着:亮出手柄。键盘聚焦到角上时也亮(见 has-focus-visible)。 */
  visible: boolean;
  /** 指针按下某个手柄:由外层接管拖拽(window 级监听、拖动期间的光标),把位移交回来。 */
  onResizeStart: (event: React.PointerEvent, cursor: string, onMove: (dx: number, dy: number) => void) => void;
  onResize: (handle: LivePanelHandle, requested: Rect) => void;
}) {
  const t = useI18n();

  const startResize = (event: React.PointerEvent, handle: LivePanelHandle) => {
    const from = { x: card.x, y: card.y, width: card.width, height: card.height };
    onResizeStart(event, RESIZE_CURSOR[handle], (dx, dy) => onResize(handle, requestedRect(handle, from, dx, dy)));
  };

  /** 方向键沿这个角的对角线推一步:朝外放大、朝里缩小,横竖两种键一个效果。 */
  const keyResize = (event: React.KeyboardEvent, corner: Corner) => {
    const arrow = ARROWS[event.key];
    if (!arrow) return;
    event.preventDefault();
    const [sx, sy] = outward(corner);
    const grow = arrow[0] !== 0 ? arrow[0] === sx : arrow[1] === sy;
    const step = (event.shiftKey ? KEY_STEP_LARGE : KEY_STEP) * (grow ? 1 : -1);
    onResize(corner, requestedRect(corner, card, sx * step, (sy * step * card.height) / card.width));
  };

  return (
    <div data-live-panel-handles data-visible={visible} className="group/resize contents">
      {EDGES.map((edge) => (
        <div
          key={edge}
          aria-hidden
          data-resize-handle={edge}
          className="pointer-events-auto fixed z-[70]"
          style={{ ...edgeZone(edge, card), cursor: RESIZE_CURSOR[edge] }}
          onPointerDown={(event) => startResize(event, edge)}
        />
      ))}
      {CORNERS.map((corner) => (
        <IconButton
          unstyled
          key={corner}
          type="button"
          label={t(CORNER_LABEL[corner])}
          aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight"
          data-resize-handle={corner}
          className="pointer-events-auto fixed z-[70] rounded-full border-0 bg-transparent p-0 text-muted-foreground opacity-0 transition-[opacity,color] duration-160 hover:text-foreground focus-visible:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-data-[visible=true]/resize:opacity-100 group-has-[:focus-visible]/resize:opacity-100"
          style={{ ...cornerZone(corner, card), cursor: RESIZE_CURSOR[corner] }}
          onPointerDown={(event) => startResize(event, corner)}
          onKeyDown={(event) => keyResize(event, corner)}
        >
          <CornerArc corner={corner} radius={radius} />
        </IconButton>
      ))}
    </div>
  );
}
