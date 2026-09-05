/**
 * 拖动分组框时,哪几项跟着走。
 *
 * 抽成纯函数是因为这是一条**规则**,不是渲染:埋在 BoardCanvas 一千五百行里既读不出来
 * 也测不到,而它出过一个只有嵌套时才看得见的错(见下)。
 */

export interface CarryBox {
  id: string;
  /** 画布上的类型。`frame` 是分组框本身。 */
  kind: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * 谁在这个框里。
 *
 * **按中心判,不按碰撞。** 压着边线的那一项用碰撞判会跟着走,而它看起来明明在框外。
 *
 * **框也会被框带走。** 此前这里排除了所有 `frame`,于是嵌套时外框把内框**里的东西**带走了
 * (它们按中心判确实在外框里),却把内框本身留在原地 —— 一拖,里面的内容就从它的框里跑了
 * 出来。排除自己就够了:每一项按自己的原点各挪一次,内框和它的内容不会被移两遍。
 */
export function carriedByFrame(frame: CarryBox, all: readonly CarryBox[]): CarryBox[] {
  const left = frame.x;
  const top = frame.y;
  const right = left + frame.width;
  const bottom = top + frame.height;
  return all.filter((one) => {
    if (one.id === frame.id) return false;
    const cx = one.x + one.width / 2;
    const cy = one.y + one.height / 2;
    return cx >= left && cx <= right && cy >= top && cy <= bottom;
  });
}
