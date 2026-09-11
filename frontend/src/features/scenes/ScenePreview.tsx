import { Box } from "lucide-react";

import { bounds, cameraPaths, footprints, type ScenePreviewData } from "./sceneFootprint";

/**
 * 场景卡片上的那张图:**保存的场景本身的俯视平面**,不是截图。
 *
 * 与画板/工作流卡片(CanvasPreview)同一套路数 —— 从数据直出 SVG,所以它永远和场景同步,
 * 也不用为了一张缩略图在列表页开 WebGL 上下文。这里画的是地面投影:每个物体一块按自己颜色
 * 填的矩形,相机的运镜画成一条虚线。
 *
 * 外框(aspect/圆角/底色/边框)跟 CanvasPreview 对齐,两种卡片并排时是同一种东西。
 */
export function ScenePreview({ data }: { data: ScenePreviewData | null | undefined }) {
  const marks = footprints(data);
  const paths = cameraPaths(data);
  const view = bounds(marks, paths);

  return (
    <div className="grid aspect-[16/9] w-full place-items-center overflow-hidden rounded-lg border border-border bg-panel-subtle p-5">
      {marks.length === 0 ? (
        <Box size={40} strokeWidth={1} className="text-muted-foreground" aria-hidden="true" />
      ) : (
        <svg
          className="h-full w-full overflow-hidden"
          viewBox={`${view.x} ${view.z} ${view.w} ${view.d}`}
          aria-hidden="true"
        >
          {marks.map((mark, i) => {
            const shared = {
              fill: mark.color,
              fillOpacity: mark.kind === "camera" || mark.kind === "light" ? 0.9 : 0.55,
              // 描边**不跟物体颜色**:场景里完全可以有一个跟卡片底色差不多的深灰物体,那时同色
              // 描边等于没有,那块地就凭空消失了。固定描边保证轮廓在两种主题下都在(同 CanvasPreview)。
              stroke: "var(--border-strong)",
              strokeWidth: 1,
              vectorEffect: "non-scaling-stroke" as const,
            };
            // 圆柱和球俯视就是个圆 —— 画成方块的话,一屋子柱子看上去全成了箱子。
            if (mark.kind === "sphere" || mark.kind === "cylinder") {
              return <ellipse key={i} cx={mark.x} cy={mark.z} rx={mark.w / 2} ry={mark.d / 2} {...shared} />;
            }
            return (
              <rect
                key={i}
                x={mark.x - mark.w / 2}
                y={mark.z - mark.d / 2}
                width={mark.w}
                height={mark.d}
                // SVG 的 y 轴向下,而场景里绕 Y 的正角是另一个转向 —— 取负才转得和视口一致。
                transform={mark.angle ? `rotate(${-mark.angle} ${mark.x} ${mark.z})` : undefined}
                {...shared}
              />
            );
          })}
          {paths.map((path, i) => (
            <polyline
              key={`path-${i}`}
              points={path.map(([x, z]) => `${x},${z}`).join(" ")}
              fill="none"
              stroke="var(--primary)"
              strokeWidth="2"
              strokeDasharray="5 4"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
      )}
    </div>
  );
}
