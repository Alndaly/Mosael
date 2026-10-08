import * as React from "react";

/**
 * **压在窗口外壳之上的模态弹窗**:从 ComfyUI 工作台那一列里打开的模型详情、它的「存为预览图」确认框。
 *
 * 工作台亮着时,原生网页视图(画布)盖在一切 DOM 上,顶栏和右边那一列(窗口外壳)是 z-200。普通的弹窗(z-50)在这里
 * 两头都看不见:中间那块被画布盖着,两边被外壳盖着。所以在这个范围里打开的 Dialog / AlertDialog:
 *
 * - 遮罩和内容抬到 z-205(外壳之上;外壳里打开的浮层 z-210、大图 z-220 照旧在它上面 —— 弹窗里的菜单、下拉从外壳的区域里
 *   开出来(useChromeLayer),照样露得出来);
 * - 开着的这段时间请原生视图让开(见 nativeViewAside:先铺一张冻结的画面再挪开,画布不闪)。
 *
 * 内容**不**挂 `APP_CHROME`:挂了,弹窗自己的「按 Esc 关」也会被 keepOpenOnAppChrome 当成落在外壳上拦下。也用不着 ——
 * 底下还开着的弹窗(工作流库)是 Radix 的下一层,在上面这一层里点、按 Esc,它本来就不管(Radix 只让最上面那层响应)。
 *
 * 范围之外什么都不变。
 *
 * 这个模块只依赖 React(app/contextIdentity.test.ts):请原生视图让开的那个组件(`StepNativeViewAside`)住在 nativeViewAside 里。
 */
export const OverChromeModals = React.createContext(false);

/** 抬过外壳的那一层(遮罩和内容同一个数,后打开的排在后面、盖在上面)。 */
export const OVER_CHROME_MODAL_LAYER = "z-[205]";

/** 在范围里时:遮罩和内容要加的那一层,以及要不要请原生视图让开。 */
export function useOverChromeModal(): { layer: string | undefined; aside: boolean } {
  const over = React.useContext(OverChromeModals);
  return { layer: over ? OVER_CHROME_MODAL_LAYER : undefined, aside: over };
}
