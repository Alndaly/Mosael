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
 *
 * 这里只管**怎么走**;线**长什么样**(颜色、线宽、箭头、各种语义变体)在 components/app/canvasEdges。
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
