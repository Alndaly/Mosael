/**
 * 「这个位置到底在不在一个真正的 Dialog 里面」。
 *
 * 问的人是那些浮层控件(Combobox / SearchableSelect):它们要不要给 Popover 开 `modal`。
 *
 * 开 modal 是为了解决 Dialog 专属的问题:Dialog 用 react-remove-scroll 锁背景滚动,只放行自己
 * shard 内的滚轮,而 PopoverContent 走 Portal 落在 shard 之外 —— 不开就滚不动列表。
 * 但 modal 会让 Radix 给 `document.body` 挂上 `pointer-events: none`,而这个还原**并不可靠**
 * (多层 Popper 交替开关时会漏)。留下来的后果是**整个应用点击穿透** —— 表现为「点面板上的
 * 输入框,却选中了它背后的画布节点」,而且看不出跟下拉框有任何关系。所以按位置决定。
 *
 * **只认 `role="dialog"` 是不够的**:Radix 给 PopoverContent 也挂了 `role="dialog"`(而且两边都
 * **不**挂 `aria-modal`,那条也分不开)。于是嵌在设置弹层里的下拉会被当成「在对话框里」,
 * 平白开了 modal,把上面那个点击穿透带到一处根本不需要它的地方。
 *
 * 分辨的记号是 popper:Popover / Select / 下拉菜单的浮层都长在
 * `[data-radix-popper-content-wrapper]` 里面,真正的 Dialog 不是。撞见 popper 就跨过整层继续
 * 往上找 —— Dialog 里套 Popover 再套下拉,最外面那层仍然是 Dialog,modal 该开还得开。
 */
export function insideDialog(node: Element | null | undefined): boolean {
  let current: Element | null | undefined = node;
  while (current) {
    const dialog = current.closest('[role="dialog"]');
    if (!dialog) return false;
    const wrapper = dialog.parentElement;
    if (!wrapper?.hasAttribute("data-radix-popper-content-wrapper")) return true;
    current = wrapper.parentElement;
  }
  return false;
}
