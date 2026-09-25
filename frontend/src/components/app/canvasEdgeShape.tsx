import { MarkerType } from "@xyflow/react";
import { Spline, Waypoints, type LucideIcon } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

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
 * 连线**长什么样**。和走线方式一样,工作流和创意画板共用这一份。
 *
 * 画板此前没写任何连线样式,吃的是 xyflow 的默认值:#b1b1b7、1px、没有箭头 —— 深色主题下
 * 也是那一抹灰,和工作流那边按设计令牌画的线不是一个东西。于是「拉线松手时那根待定的线」
 * 该长得像谁都说不清。收成一处:线色、线宽、选中/悬停、箭头、拖线时和待定时的样子。
 */

/**
 * 挂在画布外层容器上:所有边照设计令牌画,选中变主色、悬停/选中加粗。
 *
 * 两个坑,都让「类名挂上了、规则也生成了,线还是 xyflow 默认的 #b1b1b7 / 1px」:
 *
 *  · **写 xyflow 的 CSS 变量,不直接写 stroke。** xyflow 的 style.css 不在任何 @layer 里,
 *    而 Tailwind 的工具类全在 `@layer utilities` —— 层外的声明无视选择器权重、永远压过层内的。
 *    xyflow 自己读 `--xy-edge-stroke*`,变量在祖先上设、往下继承,和它的规则不冲突。
 *    线帽和过渡 xyflow 没写,直接写属性就生效。
 *  · **选择器里的下划线要转义。** Tailwind 把任意值里的 `_` 换成空格,`.react-flow__edge`
 *    会变成 `.react-flow  edge`(一个选不中任何东西的后代选择器)。所以写成 `\_\_`,
 *    并用 String.raw —— 普通字符串里的 `\_` 会被 JS 吃掉反斜杠,运行时的类名就和生成的
 *    规则对不上了。
 */
export const CANVAS_EDGE_CLASS = String.raw`[--xy-edge-stroke:var(--border-strong)] [--xy-edge-stroke-width:1.5] [--xy-edge-stroke-selected:var(--primary)] [--xy-connectionline-stroke:var(--primary)] [--xy-connectionline-stroke-width:1.5] [&_.react-flow\_\_edge.selected]:[--xy-edge-stroke-width:2.2] [&_.react-flow\_\_edge:hover]:[--xy-edge-stroke-width:2.2] [&_.react-flow\_\_edge-path]:[stroke-linecap:round] [&_.react-flow\_\_edge-path]:[transition:stroke_120ms,stroke-width_120ms]`;

/** 连线末端的闭合箭头:方向一目了然(上游 → 下游)。 */
export const CANVAS_EDGE_MARKER = { type: MarkerType.ArrowClosed, width: 12, height: 12, color: "var(--border-strong)" };

/**
 * 拖线途中那根线,和松手后还没定下来的那根**是同一个样子**:主色虚线。
 * 从「正在拉」到「等你选」再到「连上了」,线只换一次样子(虚 → 实),不会中途变成另一根线。
 */
export const CANVAS_CONNECTION_LINE_STYLE = { stroke: "var(--primary)", strokeWidth: 1.5, strokeDasharray: "5 4" };
export const CANVAS_PENDING_EDGE_STYLE = CANVAS_CONNECTION_LINE_STYLE;

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

/** 工具条上那一排切换键:每种走线一颗,按下的那颗是当前的。 */
export function EdgeShapeToggle({ value, onChange }: { value: EdgeShape; onChange: (shape: EdgeShape) => void }) {
  const t = useI18n();
  return (
    <div className="flex items-center gap-1">
      {EDGE_SHAPES.map((shape) => {
        const Icon = EDGE_SHAPE_ICON[shape];
        return (
          <Button
            key={shape}
            variant={value === shape ? "secondary" : "ghost"}
            size="icon-sm"
            className={cn(value === shape && "bg-secondary text-foreground")}
            aria-label={t(EDGE_SHAPE_LABEL[shape])}
            title={t(EDGE_SHAPE_LABEL[shape])}
            aria-pressed={value === shape}
            onClick={() => onChange(shape)}
          >
            <Icon size={13} />
          </Button>
        );
      })}
    </div>
  );
}
