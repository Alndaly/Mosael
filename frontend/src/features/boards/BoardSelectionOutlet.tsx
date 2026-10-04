import React from "react";
import { Position, getBezierPath, getSmoothStepPath, useReactFlow, useStore } from "@xyflow/react";
import { Plus } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { type EdgeShape } from "@/components/app/canvasEdgeShape";
import { CANVAS_DRAFT_LINE_CLASS } from "@/components/app/canvasEdges";
import { IconButton } from "@/components/ui/icon-button";
import { listenKeys } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";
import { selectionDraft, type PlacedCell, type Rect, type SelectionDraft, type XY } from "@/features/boards/selectionLink";

/**
 * 选区框和它的**统一出口**(多选之后一次连线,用户选定的方案):选中两格以上,整组外面一圈虚线框,框右侧中点一个 `+`。
 * 从它拉线 —— 松在一格上,选中的几格都连过去;松在空白处,弹「新建一格,连上选中的 N 格」。拖着的时候从每一格的
 * 出口各画一根预览线汇到指针,悬在一格上时每一根按规矩标出连不连得上。
 *
 * **为什么另起一个出口,不借格子自己的。** 此前(1.8.1)从选中的任一格的出口拉线就把整组带上:同一个 `+`,
 * 选没选中意思不一样,只想从其中一格单拉一根的时候得先取消多选。现在格子自己的出口永远只连它自己,批量只走这里。
 *
 * **为什么自己画、不用 React Flow 的连线。** xyflow 一次只拖一根线(connection line 只有一根,onConnect 只给一对),
 * 而这里要从好几格同时画、按每一根判;框也一样 —— 它自带的 NodesSelection 只在框选之后出现,按住 ⇧ 点选的没有。
 * 这一层叠在画布上面,在屏幕坐标里摆框和 `+`(边框和按钮不跟着缩放,和格子的 `+` 一样永远这么大),预览线在流坐标里画
 * (线宽跟着缩放,和真线一样)。
 *
 * **多选时格子自己的 `+` 收起来,悬停那一格才露出**(QuietPortsContext):不然一组格子四周挂满 `+`,框得放宽把它们圈进去,
 * 框上的出口还会和最右那一格的 `+` 挤在一起 —— 两个长得差不多的东西挨着,分不清拖的是哪一个。
 */

/** 框离格子多远(屏幕 px):贴着格子,上面让开格子的类型标签,又不碰到操作条(BOARD_NODE_PANEL_OFFSET = 24)。 */
const PAD = { x: 24, top: 22, bottom: 16 } as const;
/**
 * 统一出口离框线多远(屏幕 px):浮在框外,像格子的 `+` 浮在格子边外那样。
 *
 * 这个距离保证悬停最右那一格、它自己的 `+` 露出来时,两个圆之间还隔着一截:格子的 `+` 伸到格子边外 10 + 24 = 34px,
 * 统一出口的圆从格子边外 PAD.x + OUTLET_GAP = 40px 才开始。
 */
const OUTLET_GAP = 16;
const OUTLET_SIZE = 28;

/** 悬在一格上时,那一格外面的那一圈(和查找节点的圈同一个手法)。连得上是主色,一根都连不上是警示色的虚线。 */
export const LINK_TARGET_CLASS = {
  link: "rounded-[10px] outline outline-2 outline-offset-4 outline-primary",
  refused: "rounded-[10px] outline outline-2 outline-dashed outline-offset-4 outline-destructive/70",
} as const;

/**
 * 挂在画布容器上:React Flow 自己的那块「已选区域」(框选之后才出现,拖它整组挪)**只留功能、不画样子** —— 框由这里画,
 * 两个框套在一起只会让人以为是两样东西;框选时拖出来的那块橡皮筋走令牌(xyflow 默认是写死的蓝,暗色下发灰)。
 */
export const BOARD_SELECTION_SKIN = [
  "[--xy-selection-background-color:color-mix(in_oklab,var(--primary)_6%,transparent)]",
  "[--xy-selection-border:1px_solid_color-mix(in_oklab,var(--primary)_55%,transparent)]",
  String.raw`[&_.react-flow\_\_nodesselection-rect]:border-transparent`,
  String.raw`[&_.react-flow\_\_nodesselection-rect]:bg-transparent`,
].join(" ");

function draftPath(shape: EdgeShape, from: XY, to: XY): string {
  const ends = { sourceX: from.x, sourceY: from.y, sourcePosition: Position.Right, targetX: to.x, targetY: to.y, targetPosition: Position.Left };
  return (shape === "smoothstep" ? getSmoothStepPath(ends) : getBezierPath(ends))[0];
}

/**
 * 拖统一出口的那一下:按下开始,指针每动一下换成流坐标交给 `selectionDraft`,松手交出「落在哪一格(或空白处)、哪个点」,
 * Esc 取消。监听挂在 window 上 —— 指针早就离开了那个 `+`。
 */
function useSelectionLinkDrag({
  toFlow,
  onRelease,
}: {
  toFlow: (point: XY) => XY;
  onRelease: (point: XY) => void;
}) {
  const [point, setPoint] = React.useState<XY | null>(null);
  const stop = React.useRef<(() => void) | null>(null);
  const latest = React.useRef({ toFlow, onRelease });
  latest.current = { toFlow, onRelease };

  const begin = React.useCallback((event: React.PointerEvent) => {
    if (event.button !== 0) return;
    //: 不让画布接到这一下(不平移、不框选、不取消选中),也不选中字。
    event.preventDefault();
    event.stopPropagation();
    stop.current?.();
    const at = (one: { clientX: number; clientY: number }) => latest.current.toFlow({ x: one.clientX, y: one.clientY });
    setPoint(at(event));
    const move = (next: PointerEvent) => setPoint(at(next));
    const end = () => {
      stop.current?.();
      setPoint(null);
    };
    const up = (next: PointerEvent) => {
      end();
      latest.current.onRelease(at(next));
    };
    //: Esc 取消:捕获阶段先接住,别让它再去收面板、取消选中 —— 用户只是不想连了。
    const unkey = listenKeys(window, (key) => {
      if (key.key !== "Escape") return;
      key.preventDefault();
      key.stopPropagation();
      end();
    }, true);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", end);
    stop.current = () => {
      stop.current = null;
      unkey();
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", end);
    };
  }, []);
  React.useEffect(() => () => stop.current?.(), []);

  return { point, begin };
}

export function BoardSelectionOutlet({
  frame,
  sources,
  cells,
  edges,
  shape,
  onHover,
  onRelease,
}: {
  /** 选中的几格合起来的那块(流坐标)。 */
  frame: Rect;
  /** 统一出口连出去的那几格(boardLinks.selectionSources:连得出线的、从左到右)。空的话只画框、不给出口。 */
  sources: readonly PlacedCell[];
  /** 画布上的格子 —— 找指针底下是哪一格。 */
  cells: readonly PlacedCell[];
  edges: readonly { source: string; target: string }[];
  shape: EdgeShape;
  /** 悬在哪一格上、整体连不连得上(画布给那一格画圈);离开格子、松手、取消时给 null。 */
  onHover: (hover: { id: string; verdict: "link" | "refused" } | null) => void;
  /** 松手:落在 `target` 那一格上,或空白处(null);`at` 是松手点(流坐标)。 */
  onRelease: (target: string | null, at: XY) => void;
}) {
  const t = useI18n();
  const [tx, ty, zoom] = useStore((state) => state.transform);
  const { screenToFlowPosition } = useReactFlow();
  const model = React.useRef({ sources, cells, edges });
  model.current = { sources, cells, edges };
  const judge = React.useCallback(
    (point: XY): SelectionDraft => selectionDraft(model.current.sources, model.current.cells, model.current.edges, point),
    [],
  );
  const { point, begin } = useSelectionLinkDrag({
    toFlow: screenToFlowPosition,
    onRelease: (at) => onRelease(judge(at).target, at),
  });
  const draft = point ? judge(point) : null;

  //: 悬着的那一格换了(或连不连得上变了)才告诉画布 —— 指针每动一下都报的话,整块画布跟着每帧重画。
  const hover = React.useRef({ onHover, value: null as { id: string; verdict: "link" | "refused" } | null });
  hover.current = { onHover, value: draft?.target && draft.verdict ? { id: draft.target, verdict: draft.verdict } : null };
  const hoverKey = hover.current.value ? `${hover.current.value.id}:${hover.current.value.verdict}` : "";
  React.useEffect(() => {
    hover.current.onHover(hover.current.value);
  }, [hoverKey]);
  //: 拖到一半框没了(选中被撤销、服务端那份换进来):画在那一格上的圈也收掉,别留一个悬空的高亮。
  React.useEffect(() => {
    const latest = hover;
    return () => {
      if (latest.current.value) latest.current.onHover(null);
    };
  }, []);

  const left = frame.x * zoom + tx - PAD.x;
  const top = frame.y * zoom + ty - PAD.top;
  const width = frame.width * zoom + PAD.x * 2;
  const height = frame.height * zoom + PAD.top + PAD.bottom;
  const label = t("boardSelectionOutlet").replace("{n}", String(sources.length));

  return (
    <div data-selection-outlet-layer="" className="pointer-events-none absolute inset-0 z-[5] overflow-hidden">
      <div
        data-selection-frame=""
        aria-hidden
        className={cn(
          "absolute rounded-2xl border border-dashed transition-colors duration-150",
          point ? "border-primary/70" : "border-primary/45",
        )}
        style={{ left, top, width, height }}
      />
      {draft && (
        <svg aria-hidden className="absolute inset-0 h-full w-full overflow-visible">
          <g transform={`translate(${tx} ${ty}) scale(${zoom})`}>
            {draft.lines.map((line) => (
              <path
                key={line.id}
                data-selection-draft-line={line.id}
                data-tone={line.tone}
                d={draftPath(shape, line.from, line.to)}
                className={CANVAS_DRAFT_LINE_CLASS[line.tone]}
              />
            ))}
          </g>
        </svg>
      )}
      {sources.length > 0 && (
        <IconButton
          unstyled
          type="button"
          data-selection-outlet=""
          label={label}
          onPointerDown={begin}
          className={cn(
            "nodrag nopan pointer-events-auto absolute grid size-7 -translate-x-1/2 -translate-y-1/2 cursor-crosshair place-items-center rounded-full border shadow-sm transition-colors",
            point
              ? "border-primary bg-primary text-primary-foreground"
              : "border-primary/70 bg-panel text-primary hover:border-primary hover:bg-primary hover:text-primary-foreground",
          )}
          style={{ left: left + width + OUTLET_GAP + OUTLET_SIZE / 2, top: top + height / 2 }}
        >
          <Plus size={15} strokeWidth={2.25} />
          {/* 这一根会连出去几格 —— 和格子自己那个只连一格的 `+` 区分开。 */}
          <span
            aria-hidden
            className="absolute -right-2 -top-2 grid h-4 min-w-4 place-items-center rounded-full border border-panel bg-primary px-1 text-ui-2xs font-semibold leading-none text-primary-foreground tabular-nums"
          >
            {sources.length}
          </span>
        </IconButton>
      )}
    </div>
  );
}
