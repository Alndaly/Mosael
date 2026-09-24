/**
 * 视口右上角的坐标轴小控件 —— 看得出「现在是从哪个方向看的」,点一下就转过去。
 *
 * **用 DOM 画,不在 WebGL 里画。** 轴柄是真的 `<button>`:能聚焦、能用键盘、读屏软件念得出
 * 「从上方看」。画在画布里的话,这些全要自己实现一遍,而它本来就是界面控件,不是场景内容。
 *
 * 朝向由视口**在它自己那条渲染循环里**推过来(`subscribe`),而且只在真的转动时推 ——
 * 每帧 setState 会让这棵小树每秒重渲六十次,而绝大多数帧里相机根本没动。
 */

import React from "react";

import { useI18n } from "@/app/preferences";
import {
  axisLabel,
  gizmoHandles,
  type AxisHandle,
  type AxisName,
  type Orientation,
} from "./axisGizmo";

/** 控件半径(像素)。轴柄落在这个圆上,容器再留一圈给球本身。 */
const RADIUS = 26;
const BALL = 9;

export function SceneAxisGizmo({
  subscribe,
  onPick,
}: {
  /** 视口在这里登记一个回调,相机转了就调它。返回注销函数。 */
  subscribe: (listener: (orientation: Orientation) => void) => () => void;
  onPick: (axis: AxisName, sign: 1 | -1) => void;
}) {
  const t = useI18n();
  const [orientation, setOrientation] = React.useState<Orientation>([0, 0, 0, 1]);
  React.useEffect(() => subscribe(setOrientation), [subscribe]);
  const handles = React.useMemo(() => gizmoHandles(orientation), [orientation]);
  const size = (RADIUS + BALL) * 2;

  return (
    <div
      className="scene-axis-gizmo"
      style={{ width: size, height: size }}
      role="group"
      aria-label={t("sceneAxisGizmo")}
    >
      <svg width={size} height={size} aria-hidden="true">
        {/* 只给正向画杆。六根杆会在正对某个轴时叠成一团,而负向本来就只是个落点。 */}
        {handles
          .filter((one) => one.sign > 0)
          .map((one) => (
            <line
              key={one.id}
              x1={size / 2}
              y1={size / 2}
              x2={size / 2 + one.x * RADIUS}
              y2={size / 2 + one.y * RADIUS}
              stroke={one.color}
              strokeWidth={1.6}
              strokeLinecap="round"
              // 指向背面的杆淡一些 —— 不然正面和背面在平面上长得一样。
              opacity={one.depth < 0 ? 0.35 : 0.8}
            />
          ))}
      </svg>
      {handles.map((one) => (
        <GizmoBall key={one.id} handle={one} center={size / 2} onPick={onPick} />
      ))}
    </div>
  );
}

function GizmoBall({
  handle,
  center,
  onPick,
}: {
  handle: AxisHandle;
  center: number;
  onPick: (axis: AxisName, sign: 1 | -1) => void;
}) {
  const t = useI18n();
  const front = handle.depth >= 0;
  return (
    <button
      type="button"
      className="scene-axis-ball"
      data-front={front || undefined}
      title={t(axisLabel(handle.axis, handle.sign))}
      aria-label={t(axisLabel(handle.axis, handle.sign))}
      style={{
        left: center + handle.x * RADIUS - BALL,
        top: center + handle.y * RADIUS - BALL,
        width: BALL * 2,
        height: BALL * 2,
        // 前后关系靠它:转到某个角度时,背面那个球不该盖住正面的。
        zIndex: Math.round(handle.depth * 100) + 200,
        // 正向是实心球,负向是空心的(和 Blender 一样);背面的一律淡一档。
        background: handle.sign > 0 ? handle.color : "var(--panel)",
        borderColor: handle.color,
        opacity: front ? 1 : 0.55,
        color: handle.sign > 0 ? "#12141a" : handle.color,
      }}
      onClick={() => onPick(handle.axis, handle.sign)}
    >
      {handle.label}
    </button>
  );
}
