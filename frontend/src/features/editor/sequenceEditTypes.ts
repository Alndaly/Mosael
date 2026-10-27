/** 序列编辑的公共载荷类型(同时被 UI 与 mutation hook 使用,不反向依赖组件)。 */

export const FILL_MODES = ["cover", "contain", "blur"] as const;
export type FillMode = (typeof FILL_MODES)[number];

export interface TrimPayload {
  timeline_start: number;
  src_in: number;
  src_out: number;
  /** false = 只修这一段,不带链接组员(按住 ⌥ 修剪,或临时解链的选区)。 */
  linked?: boolean;
}
