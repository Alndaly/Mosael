/**
 * 视口角上那个坐标轴小控件要画成什么样 —— **纯算,不碰 three,也不碰 DOM**。
 *
 * 它回答的是一个几何问题:相机此刻朝着这个姿态时,世界的六个轴向各自落在小控件的哪个位置、
 * 谁在前谁在后。分出来是因为这部分**看不出对错** —— 轴画反了、前后压错了,画面上仍然是六个
 * 小球,只有当你点「+X」却转到了背面才发现。而它是纯函数,可以直接拿数钉住。
 *
 * 轴的约定跟场景数据走:**Y 朝上**(见 docs/3D_SCENES.md)。Blender 是 Z 朝上,所以标签的
 * 含义和它不一样 —— 这里 Y 是天,不是深度。颜色仍按通行的 X 红 / Y 绿 / Z 蓝。
 */

import type { MessageKey } from "@/app/messages";

export type AxisName = "x" | "y" | "z";

/** 相机的朝向,四元数 `[x, y, z, w]`。**不收 three 的类型** —— 那会把 WebGL 拖进单元测试。 */
export type Orientation = readonly [number, number, number, number];

export interface AxisHandle {
  /** `"x+"` / `"x-"` …… 作 React key 和测试里的名字。 */
  id: string;
  axis: AxisName;
  sign: 1 | -1;
  /** 正向才写字母;负向是个空心球(和 Blender 一样),写上字就挤成一团。 */
  label: string;
  color: string;
  /** 小控件内的坐标,原点在中心,范围 ±1(调用方乘半径)。y 已经翻成**屏幕方向**(下为正)。 */
  x: number;
  y: number;
  /** 相机空间的 z:**越大越靠前**。调用方按它从后往前画,并据此定 z-index。 */
  depth: number;
}

/** 世界轴 → 颜色。和地面网格那两条轴线同一套色相,只是亮一些(它是控件,不是背景)。 */
export const AXIS_COLOR: Record<AxisName, string> = {
  x: "#d9737a",
  y: "#7cb87a",
  z: "#6f8fd6",
};

const AXES: { axis: AxisName; vector: readonly [number, number, number] }[] = [
  { axis: "x", vector: [1, 0, 0] },
  { axis: "y", vector: [0, 1, 0] },
  { axis: "z", vector: [0, 0, 1] },
];

/**
 * 把世界方向转进相机空间 —— 即用相机朝向的**共轭**去转它。
 *
 * 手写而不是拿 three:这一份要能在没有 WebGL 的测试环境里跑,而它只是四元数转向量,
 * 十行的事。
 */
function intoCameraSpace(
  [qx, qy, qz, qw]: Orientation,
  [vx, vy, vz]: readonly [number, number, number],
): [number, number, number] {
  // 共轭 = 取反虚部。
  const cx = -qx, cy = -qy, cz = -qz, cw = qw;
  // t = 2 * cross(q.xyz, v)
  const tx = 2 * (cy * vz - cz * vy);
  const ty = 2 * (cz * vx - cx * vz);
  const tz = 2 * (cx * vy - cy * vx);
  return [
    vx + cw * tx + (cy * tz - cz * ty),
    vy + cw * ty + (cz * tx - cx * tz),
    vz + cw * tz + (cx * ty - cy * tx),
  ];
}

/**
 * 六个轴柄,**从后往前排好**。
 *
 * 顺序就是绘制顺序:后面的先画,前面的压在上面 —— 否则转到某个角度时,背面那个球会盖住
 * 正面的,而看上去只是"颜色不对"。
 */
export function gizmoHandles(orientation: Orientation): AxisHandle[] {
  const handles: AxisHandle[] = [];
  for (const { axis, vector } of AXES)
    for (const sign of [1, -1] as const) {
      const [x, y, z] = intoCameraSpace(orientation, [
        vector[0] * sign,
        vector[1] * sign,
        vector[2] * sign,
      ]);
      handles.push({
        id: `${axis}${sign > 0 ? "+" : "-"}`,
        axis,
        sign,
        label: sign > 0 ? axis.toUpperCase() : "",
        color: AXIS_COLOR[axis],
        x,
        // SVG / CSS 的 y 向下,相机空间的 y 向上。
        y: -y,
        depth: z,
      });
    }
  return handles.sort((a, b) => a.depth - b.depth);
}

/** 点了某个轴柄之后,相机该站到目标的哪一侧。 */
export function axisVector(axis: AxisName, sign: 1 | -1): [number, number, number] {
  const base = AXES.find((one) => one.axis === axis)!.vector;
  // `+ 0` 把 `-0` 收回 `0`:两者在数学上相等,但读出来、比较起来都像出了什么事。
  return [base[0] * sign + 0, base[1] * sign + 0, base[2] * sign + 0];
}

/** 轴柄的无障碍名字(文案表的 key)。屏幕阅读器听到的是「从上方看」,不是「y 加」。 */
export function axisLabel(axis: AxisName, sign: 1 | -1): MessageKey {
  if (axis === "y") return sign > 0 ? "sceneAxisTop" : "sceneAxisBottom";
  if (axis === "z") return sign > 0 ? "sceneAxisFront" : "sceneAxisBack";
  return sign > 0 ? "sceneAxisRight" : "sceneAxisLeft";
}
