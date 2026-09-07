/**
 * 变换吸附开关的持久化。
 *
 * 吸附改的是移动/旋转/缩放的步长(0.25 米 / 15° / 0.1,见 SceneViewport)。它是
 * **「我习惯这么干活」**,不是这一次的临时状态 —— 每次打开场景都退回关闭,等于让常开的人
 * 每次先点一下。与画布输入模式(`components/app/canvasInputMode`)同一类偏好、同一套写法。
 *
 * 存不进去(隐私窗口、站点数据被禁)不算错:读回默认值、照常工作,只是下次不记得。
 */
const KEY = "mosael.scene.transform-snap";

export function readSceneSnap(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

/** 存一次并把它原样回传 —— 调用点因此能写成 `setSnap((on) => writeSceneSnap(!on))`。 */
export function writeSceneSnap(on: boolean): boolean {
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* 记不住而已,这一次照常生效。 */
  }
  return on;
}
