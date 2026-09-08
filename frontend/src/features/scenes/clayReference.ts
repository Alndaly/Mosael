/**
 * 「同时送一张灰模」这个开关的持久化。
 *
 * 灰模是把场景里所有材质换成同一种中性灰再渲一张,和正片一起作为第二张参考图交给模型:
 * 去掉材质噪音(3D 里的占位色看着塑料,会把模型往塑料感带),只留**光的结构** —— 影子、
 * 明暗过渡、体积。生成侧的 `reference_image` 上限是 9,多送一张是现成能力,不用改后端。
 *
 * 存本地而不是存进场景:它说的是"我习惯怎么交给模型",不是这个场景长什么样 —— 同一个场景
 * 换个人打开,该由那个人的习惯决定。和吸附开关(`sceneSnap`)同一类偏好、同一套写法。
 *
 * **默认开**:多一张参考图对可控性的提升是明确的,而代价只是多渲一帧。
 */
const KEY = "mosael.scene.clay-reference";

export function readClayReference(): boolean {
  try {
    return localStorage.getItem(KEY) !== "0";
  } catch {
    return true;
  }
}

/** 存一次并原样回传 —— 调用点因此能写成 `setClay((on) => writeClayReference(!on))`。 */
export function writeClayReference(on: boolean): boolean {
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* 记不住而已,这一次照常生效。 */
  }
  return on;
}
