/**
 * 下拉选中之后,吞掉落到它**下面**的那一次 click。
 *
 * Radix Select 用鼠标选时是在**按键抬起**那一刻选中并关掉菜单的(`pointerup`);菜单一关,浏览器紧跟着补发的
 * `click` 就落到了此刻指针下面的东西上 —— 画板上是菜单下面那格视频:开始播放、被选中(用户:「弹窗下拉菜单上的
 * 点击会穿透到下方视频」)。触屏不走这条(Radix 在 click 上选),所以只管鼠标。
 *
 * 做法:抬起时在 window 的捕获阶段挂一个一次性的 click 拦截,只拦落在菜单外面的那一下;这一轮事件派发完就摘掉 ——
 * 抬起和它补发的 click 在同一个任务里,下一轮之后的点击照常。
 */
export function swallowClickThrough(event: { pointerType?: string }, inside: (target: EventTarget | null) => boolean): void {
  if (event.pointerType !== "mouse") return;
  const swallow = (click: MouseEvent) => {
    if (inside(click.target)) return;
    click.preventDefault();
    click.stopPropagation();
    stop();
  };
  const stop = () => {
    window.removeEventListener("click", swallow, true);
    window.clearTimeout(timer);
  };
  window.addEventListener("click", swallow, true);
  const timer = window.setTimeout(stop, 0);
}
