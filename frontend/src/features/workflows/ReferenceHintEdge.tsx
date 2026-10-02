import { BaseEdge, getBezierPath, getSmoothStepPath, type EdgeProps } from "@xyflow/react";

import { REFERENCE_HINT_EDGE_TYPE, type ReferenceHintFlowEdge } from "@/features/workflows/referenceHints";

/**
 * 引用提示线的渲染器(见 referenceHints)。走线跟着画布的偏好(贝塞尔 / 折线),和真连线同一种走法;
 * 长什么样全由类名给(components/app/canvasEdges 的「引用提示」那两行),这里不写线色、线宽、虚线。
 *
 * 唯一多出来的是 `<title>`:悬停在线上时浏览器显示那句「引用 {{A.x}}(只管先后,不会让 A 运行)」——
 * SVG 元素不认 `title` 属性,得是一个子元素。
 */
export function ReferenceHintEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  interactionWidth,
}: EdgeProps<ReferenceHintFlowEdge>) {
  const ends = { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition };
  const [path] = data?.shape === "smoothstep" ? getSmoothStepPath(ends) : getBezierPath(ends);
  return (
    <>
      <title>{data?.title}</title>
      <BaseEdge id={id} path={path} interactionWidth={interactionWidth} />
    </>
  );
}

/** 工作流画布的自定义边类型。**模块级常量** —— 每次渲染给一个新对象,React Flow 会警告并重挂所有边。 */
export const WORKFLOW_CANVAS_EDGE_TYPES = { [REFERENCE_HINT_EDGE_TYPE]: ReferenceHintEdge };
