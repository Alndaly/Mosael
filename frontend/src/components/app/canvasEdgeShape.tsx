import { BaseEdge, Position, getBezierEdgeCenter, getBezierPath, getSmoothStepPath, type EdgeProps } from "@xyflow/react";
import { Spline, Waypoints, type LucideIcon } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { usePersistentTab } from "@/lib/usePersistentTab";

/**
 * 画布连线的走线方式。**工作流和创意画板共用这一份。**
 *
 * 值直接就是 React Flow 的内置边类型,不另建一层映射 —— 多一层枚举只会在加一种时要改两处。
 *
 * 走线方式是**看图习惯**而不是图的数据:同一张图,有人要贝塞尔的流畅,有人要直角好对齐。
 * 所以存本地偏好,不写进 graph / canvas —— 写进去会让同一张图在两个人眼里长得不一样,
 * 还会让"换了个线型"变成一次图变更、触发自动保存和脏状态。
 *
 * 此前这一套(选项、图标、文案、那排切换键)只长在工作流里,主图和循环体各抄一遍;画板要同样的
 * 开关时再抄第三遍,三处迟早分叉 —— 加一种走线方式时漏改的那一处不会报错,只会少一个按钮。
 *
 * 这里只管**怎么走**;线**长什么样**(颜色、线宽、箭头、各种语义变体)在 components/app/canvasEdges。
 *
 * **同一对节点之间的多条边也让开**(见下面 CANVAS_PARALLEL_EDGE_GAP 那一段)。规范化不再折掉「同一对节点
 * 间的控制边」之后,一对节点上会同时挂着「实线顺序」和「虚线值」两根线;React Flow 不做平行边错开,
 * 两根在中段重合,看着像一根粗线 —— 而这两根的意思完全不同,糊在一起等于没画。分组只看**两头是谁**
 * (不认 `d-` / `e-` 前缀:那是 id 的叫法,不是边的性质),组内第几条按边的 **id** 排 —— 同一份图
 * 每次渲染算出来是同一个序,线才不会跳。
 */
export const EDGE_SHAPES = ["default", "smoothstep"] as const;
export type EdgeShape = (typeof EDGE_SHAPES)[number];

const EDGE_SHAPE_ICON: Record<EdgeShape, LucideIcon> = {
  default: Spline,
  smoothstep: Waypoints,
};

/** 走线方式对应的 i18n key。`as const` 不能去掉:t() 只接受字面量键的联合,
 *  标成 Record<EdgeShape, string> 会把值放宽成 string,当场编译不过。 */
const EDGE_SHAPE_LABEL = {
  default: "wfEdgeBezier",
  smoothstep: "wfEdgeSmoothStep",
} as const;

/**
 * 读写某块画布的走线偏好。`storageKey` 按画布**种类**分(工作流一份、画板一份),不按某一张图 ——
 * 这是人的看图习惯,换一张图不该换一种线。
 */
export function useEdgeShape(storageKey: string) {
  return usePersistentTab<EdgeShape>(storageKey, "default", EDGE_SHAPES);
}

/**
 * 把走线方式写到**每一条**边上,而不是只靠 defaultEdgeOptions —— 后者的语义是"新建边的默认值",
 * 指望它去改已存在的边是碰运气。已经是这个类型的边原样返回,不换引用。
 */
export function shapeEdges<E extends { type?: string }>(edges: E[], shape: EdgeShape): E[] {
  return edges.map((edge) => (edge.type === shape ? edge : { ...edge, type: shape }));
}

/**
 * 一对节点之间,相邻两条线在中段让开多少(画布坐标里的 px,跟着缩放)。
 *
 * 24 ≈ 卡片上一个接点直径的两倍多:缩到 0.8 看全图时两根线之间也还剩十来个设备像素,分得开;
 * 又不至于让一条直连的线看起来像绕了个弯。
 */
export const CANVAS_PARALLEL_EDGE_GAP = 24;

/**
 * 一对节点之间让开的**总跨度上限**(两根 gap)。第 4 条起不再等距往外扩,而是挤进同一个跨度里 ——
 * 道次仍旧各不相同,线的弯却不会随条数无限变大(否则最外面那根会绕出卡片)。
 */
export const CANVAS_PARALLEL_EDGE_SPAN = 48;

/**
 * 一对节点之间的第 `index` 条(共 `count` 条)偏离中线多少:**居中分布,单条为 0**。
 *
 *  · 单条 → 0(常态:线一个像素都不动,见 laneEdges 连对象都不换);
 *  · 两条 → ∓12;三条 → -24 / 0 / 24;四条 → ∓24 / ∓8;
 *  · 再多就压在 CANVAS_PARALLEL_EDGE_SPAN 这个跨度里(相邻两条挤近一点,道次两两不同)。
 */
export function parallelEdgeLane(index: number, count: number): number {
  if (count <= 1) return 0;
  const span = Math.min(CANVAS_PARALLEL_EDGE_GAP * (count - 1), CANVAS_PARALLEL_EDGE_SPAN);
  return (index - (count - 1) / 2) * (span / (count - 1));
}

/** 算道次要看的那两个头。 */
export interface ParallelEdgeEnds {
  id: string;
  source: string;
  target: string;
}

/**
 * 一条边在这对节点里**天生**排在多高(越小的越靠上)。不给就是不分先后(纯按 id 排)。
 *
 * 为什么非要这个:道次是**从中间往外**分的,顺序错了两根线会互相插过去 —— 实测过:工作流卡片上
 * 控制口在标题层(中段 ≈ 29),数据口在页脚第一行(≈ 78),两条**数据线**之间只差 19。按 id 排的话
 * 「控制线往下一道、数据线往上一道」正好把控制线送进数据线那一格里(49 的天然间隔撞上 48 的跨度,
 * 实测差 0.8px)。按天生高低排,相邻两根的间距只会**变大**,永远不会变小。
 */
export type EdgeHeightRank = (edge: ParallelEdgeEnds) => number;

/**
 * 每条边该让开多少:`同一对节点`一组,组内**先按天生高低、再按 id** 排,最后照居中分布算第几条。
 *
 * 为什么按 id 断平:它是这份图里**边自己的名字**,和数据边/控制边怎么生成、数组怎么排、对象是不是同一份
 * 都无关 —— 同一份图每次渲染算出来一样(按数组顺序算的话,提示线排在真连线前面、运行状态一更新就换一次序,
 * 线会跳)。不用 localeCompare:那看语言环境,同一个 id 在两台机器上可能排出不同的序。
 *
 * 只有一条的那组不写进表(没有"第几条"可言):调用方据此保持那条边原样。
 *
 * 一对是**有向**的一对(source → target):`a→b` 和 `b→a` 各算一对 —— 它们说的是两件事,各自只有一条
 * 时都不让开。折边回来的那些对全是有向的同一对(控制线 + 数据线挂在同两个头上、同一个方向)。
 */
export function parallelEdgeLanes(edges: readonly ParallelEdgeEnds[], heightOf?: EdgeHeightRank): Map<string, number> {
  const groups = new Map<string, ParallelEdgeEnds[]>();
  for (const edge of edges) {
    //: 两头合成一把钥匙。中间那个 \0 不可能出现在节点 id 里(id 是 `llm-1` 这种),拼不出歧义。
    const key = `${edge.source}\u0000${edge.target}`;
    const group = groups.get(key);
    if (group) group.push(edge);
    else groups.set(key, [edge]);
  }
  const lanes = new Map<string, number>();
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    const height = heightOf ?? (() => 0);
    const ordered = [...group].sort((a, b) => height(a) - height(b) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    ordered.forEach((edge, index) => lanes.set(edge.id, parallelEdgeLane(index, ordered.length)));
  }
  return lanes;
}

/** 一条边身上要带的道次 —— 放在 `data` 上(React Flow 只把 data 交给边组件)。 */
export interface ParallelEdge extends ParallelEdgeEnds {
  data?: Record<string, unknown>;
}

/**
 * 把道次贴到每条边上(经 `data.lane` 交给渲染器),别的一概不动。
 *
 * **道次 0 的边原样返回、引用都不换**:单条边(以及三条里正中那条)从对象到画出来的路径都和以前
 * 一模一样 —— "不做这一步的老图/老观感"不靠自觉,靠这里不给它们贴东西。
 */
export function laneEdges<E extends ParallelEdge>(edges: E[], heightOf?: EdgeHeightRank): E[] {
  const lanes = parallelEdgeLanes(edges, heightOf);
  return edges.map((edge) => {
    const lane = lanes.get(edge.id);
    if (!lane) return edge;
    return { ...edge, data: { ...edge.data, lane } } as E;
  });
}

/** 一条边的两头和两个方向 —— React Flow 交给边组件的就这几项。 */
export interface CanvasEdgeEnds {
  sourceX: number;
  sourceY: number;
  sourcePosition: Position;
  targetX: number;
  targetY: number;
  targetPosition: Position;
}

/** 走线自己的那几个数(React Flow 的 `pathOptions`);不给就用它内置的默认值。 */
export interface CanvasPathOptions {
  curvature?: number;
  offset?: number;
  borderRadius?: number;
  stepPosition?: number;
}

//: React Flow 内置那两种线的默认值(见 @xyflow/system 的 getBezierPath / getSmoothStepPath)。
const BEZIER_CURVATURE = 0.25;
const SMOOTHSTEP_OFFSET = 20;
const SMOOTHSTEP_BEND = 5;

/** 让开的方向 = 连线的垂直方向:左右一对就往上下让,上下那一对就往左右让。 */
function laneDirection(ends: CanvasEdgeEnds): [number, number] {
  const dx = ends.targetX - ends.sourceX;
  const dy = ends.targetY - ends.sourceY;
  const length = Math.hypot(dx, dy);
  //: 两头重在一个点上(接点重合的怪图)没有方向可言:退成竖直让开,至少两条还分得开。
  return length === 0 ? [0, 1] : [-dy / length, dx / length];
}

/** 接点朝哪边出线(和 xyflow 的 handleDirections 一致)。 */
function handleDirection(position: Position): [number, number] {
  switch (position) {
    case Position.Left:
      return [-1, 0];
    case Position.Right:
      return [1, 0];
    case Position.Top:
      return [0, -1];
    default:
      return [0, 1];
  }
}

/**
 * 贝塞尔的控制点。**和 xyflow 的 getControlWithCurvature 同一套算式**(距离的一半;反向时按曲率缩)。
 * 只在真的要让开时才用它 —— 道次 0 直接调 getBezierPath(见 canvasEdgePath)。
 */
function bezierControl(
  position: Position,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  curvature: number,
): [number, number] {
  const reach = (distance: number) => (distance >= 0 ? 0.5 * distance : curvature * 25 * Math.sqrt(-distance));
  switch (position) {
    case Position.Left:
      return [x1 - reach(x1 - x2), y1];
    case Position.Right:
      return [x1 + reach(x2 - x1), y1];
    case Position.Top:
      return [x1, y1 - reach(y1 - y2)];
    default:
      return [x1, y1 + reach(y2 - y1)];
  }
}

/**
 * 折线拐弯处那一段圆角 —— **和 xyflow 的 getBend 同一套画法**(先直线到切点,再用一段二次曲线转过弯),
 * 半径取两段长度的一半和 `size` 里最小的那个;三点共线时不画弯。
 */
function bendThrough(
  previous: { x: number; y: number },
  corner: { x: number; y: number },
  next: { x: number; y: number },
  size: number,
): string {
  const bend = Math.min(Math.hypot(previous.x - corner.x, previous.y - corner.y) / 2, Math.hypot(next.x - corner.x, next.y - corner.y) / 2, size);
  const { x, y } = corner;
  if ((previous.x === x && x === next.x) || (previous.y === y && y === next.y)) return `L${x} ${y}`;
  if (previous.y === y) {
    const xDir = previous.x < next.x ? -1 : 1;
    const yDir = previous.y < next.y ? 1 : -1;
    return `L ${x + bend * xDir},${y}Q ${x},${y} ${x},${y + bend * yDir}`;
  }
  const xDir = previous.x < next.x ? 1 : -1;
  const yDir = previous.y < next.y ? -1 : 1;
  return `L ${x},${y + bend * yDir}Q ${x},${y} ${x + bend * xDir},${y}`;
}

/**
 * 让开之后的那条贝塞尔:**两头端点不动**,只把两个控制点整体挪 `lane`(沿连线的垂直方向)。
 *
 * 控制点补一个 4/3:三次贝塞尔在 t = 0.5 处只走出控制点位移的 3/4((1·0 + 3·c + 3·c + 1·0)/8),
 * 乘回去中段才正好让开 `lane` —— 和平滑折线那一档是同一个口径,两种走线看起来一样开。
 */
function shiftedBezierPath(ends: CanvasEdgeEnds, lane: number, options?: CanvasPathOptions): [string, number, number] {
  const curvature = options?.curvature ?? BEZIER_CURVATURE;
  const [nx, ny] = laneDirection(ends);
  const shift = (lane * 4) / 3;
  const [sourceControlX, sourceControlY] = bezierControl(ends.sourcePosition, ends.sourceX, ends.sourceY, ends.targetX, ends.targetY, curvature);
  const [targetControlX, targetControlY] = bezierControl(ends.targetPosition, ends.targetX, ends.targetY, ends.sourceX, ends.sourceY, curvature);
  const from = { x: sourceControlX + nx * shift, y: sourceControlY + ny * shift };
  const to = { x: targetControlX + nx * shift, y: targetControlY + ny * shift };
  const [labelX, labelY] = getBezierEdgeCenter({
    sourceX: ends.sourceX,
    sourceY: ends.sourceY,
    targetX: ends.targetX,
    targetY: ends.targetY,
    sourceControlX: from.x,
    sourceControlY: from.y,
    targetControlX: to.x,
    targetControlY: to.y,
  });
  return [
    `M${ends.sourceX},${ends.sourceY} C${from.x},${from.y} ${to.x},${to.y} ${ends.targetX},${ends.targetY}`,
    labelX,
    labelY,
  ];
}

/**
 * 让开之后的那条平滑折线:两头各按 xyflow 那样先往外让出 `offset`,从那里起拐;让开的是**中段那一截**
 * (往垂直方向挪 `lane`),两头因此还钉在原来的接点上。拐角照旧是圆角(见 bendThrough)。
 */
function shiftedSmoothStepPath(ends: CanvasEdgeEnds, lane: number, options?: CanvasPathOptions): [string, number, number] {
  const offset = options?.offset ?? SMOOTHSTEP_OFFSET;
  const bend = options?.borderRadius ?? SMOOTHSTEP_BEND;
  const [sourceDirX, sourceDirY] = handleDirection(ends.sourcePosition);
  const [targetDirX, targetDirY] = handleDirection(ends.targetPosition);
  const start = { x: ends.sourceX, y: ends.sourceY };
  const end = { x: ends.targetX, y: ends.targetY };
  const a = { x: ends.sourceX + sourceDirX * offset, y: ends.sourceY + sourceDirY * offset };
  const b = { x: ends.targetX + targetDirX * offset, y: ends.targetY + targetDirY * offset };
  const [nx, ny] = laneDirection(ends);
  //: 让开竖着走(左右一对)还是横着走(上下那一对):中段是**一横**或**一竖**,由它带着进出两头。
  const sideways = Math.abs(nx) > Math.abs(ny);
  const middleX = (a.x + b.x) / 2 + (sideways ? lane : 0);
  const middleY = (a.y + b.y) / 2 + (sideways ? 0 : lane);
  const points = sideways
    ? [start, a, { x: middleX, y: a.y }, { x: middleX, y: b.y }, b, end]
    : [start, a, { x: a.x, y: middleY }, { x: b.x, y: middleY }, b, end];
  let path = `M${points[0].x} ${points[0].y}`;
  for (let index = 1; index < points.length - 1; index++) {
    path += bendThrough(points[index - 1], points[index], points[index + 1], bend);
  }
  path += `L${points[points.length - 1].x} ${points[points.length - 1].y}`;
  return [path, middleX, middleY];
}

/**
 * 一条边该怎么走(路径 + 线上那行字该摆在哪)。
 *
 * **`lane` 为 0 时原样交给 React Flow 那两个函数**:内置的 `default` / `smoothstep` 边就是这么算的
 * (见 @xyflow/react 的 BezierEdge / SmoothStepEdge,连 pathOptions 的传法都一样),所以单条边画出来
 * 的 `d`、标签位置和以前一个字符都不差 —— 常态观感不靠"差不多",靠走的是同一条代码路。
 */
export function canvasEdgePath(
  shape: EdgeShape,
  ends: CanvasEdgeEnds,
  lane: number,
  options?: CanvasPathOptions,
): [string, number, number] {
  if (lane !== 0) {
    return shape === "smoothstep" ? shiftedSmoothStepPath(ends, lane, options) : shiftedBezierPath(ends, lane, options);
  }
  const builtin =
    shape === "smoothstep"
      ? getSmoothStepPath({
          ...ends,
          borderRadius: options?.borderRadius,
          offset: options?.offset,
          stepPosition: options?.stepPosition,
        })
      : getBezierPath({ ...ends, curvature: options?.curvature });
  return [builtin[0], builtin[1], builtin[2]];
}

/**
 * 画布上的边组件。走线方式由 `type` 说(React Flow 按它找组件),道次由 `data.lane` 说(见 laneEdges)。
 *
 * **不往 path 上写 id**:内置那两种边也不写(它们给 BaseEdge 传的是 internal 版那个 undefined 的 id),
 * 这样"换了渲染器"在 DOM 上同样一个字符都不差。
 */
export function CanvasEdge({
  type,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition = Position.Bottom,
  targetPosition = Position.Top,
  label,
  labelStyle,
  labelShowBg,
  labelBgStyle,
  labelBgPadding,
  labelBgBorderRadius,
  style,
  markerEnd,
  markerStart,
  pathOptions,
  interactionWidth,
  data,
}: EdgeProps) {
  const [path, labelX, labelY] = canvasEdgePath(
    type === "smoothstep" ? "smoothstep" : "default",
    { sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition },
    typeof data?.lane === "number" ? data.lane : 0,
    pathOptions,
  );
  return (
    <BaseEdge
      path={path}
      labelX={labelX}
      labelY={labelY}
      label={label}
      labelStyle={labelStyle}
      labelShowBg={labelShowBg}
      labelBgStyle={labelBgStyle}
      labelBgPadding={labelBgPadding}
      labelBgBorderRadius={labelBgBorderRadius}
      style={style}
      markerEnd={markerEnd}
      markerStart={markerStart}
      interactionWidth={interactionWidth}
    />
  );
}

/**
 * 两种走线方式对应的渲染器(React Flow 的 `edgeTypes` 里那两项内置的换成本组件)。
 * **模块级常量** —— 每次渲染给一个新对象,React Flow 会警告并重挂所有边。
 *
 * 换成自己画只为一件事:同一对节点上的第二条边要让开(见 canvasEdgePath)。渲染出来的东西在
 * `data.lane` 缺省时和内置的一模一样,画板和工作流因此共用这一份。
 */
export const CANVAS_EDGE_TYPES = { default: CanvasEdge, smoothstep: CanvasEdge };

/** 工具条上那一排切换键:每种走线一颗,按下的那颗是当前的。 */
export function EdgeShapeToggle({ value, onChange }: { value: EdgeShape; onChange: (shape: EdgeShape) => void }) {
  const t = useI18n();
  return (
    <div className="flex items-center gap-1">
      {EDGE_SHAPES.map((shape) => {
        const Icon = EDGE_SHAPE_ICON[shape];
        return (
          <IconButton
            key={shape}
            variant="ghost"
            size="icon-sm"
            
            label={t(EDGE_SHAPE_LABEL[shape])}
            aria-pressed={value === shape}
            onClick={() => onChange(shape)}
          >
            <Icon size={13} />
          </IconButton>
        );
      })}
    </div>
  );
}
