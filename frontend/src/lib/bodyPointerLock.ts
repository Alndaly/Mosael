/**
 * Radix 把 `<body>` 的 `pointer-events: none` 留在那儿之后,整页点不动。
 *
 * ## 症状
 *
 * 画面一切正常 —— 节点在、按钮在、悬停样式甚至还会变 —— 但**什么都点不动、拖不动**,只能刷新。
 * 因为那把锁在 `<body>` 上,它盖住的是整个应用,不是某一个面板。
 *
 * ## 为什么会留下
 *
 * Radix 的模态浮层(Dialog / AlertDialog / Select / 带 modal 的 Popover 与 ContextMenu)打开时
 * 给 body 上锁,关闭时解锁。解锁发生在**它自己的清理逻辑**里,所以只要那段清理没跑完整,锁就留下:
 *
 *   1. **浮层还开着就被卸载。** 无限画布上这是常态:提示词面板挂在「当前选中的那一项」上,
 *      点一下空白处就整块卸载。如果那一刻里面有个 Select / Popover 开着,它没有机会走关闭流程。
 *   2. **两个浮层的清理互相打架。** 由右键菜单唤起弹窗时,菜单的清理和弹窗的打开竞争;弹窗再关时
 *      只跑了自己那份,菜单留下的锁没人清。
 *
 * ## 为什么要做成全局的
 *
 * 此前的兜底长在 `ModalShell` 里,只在**它自己** open→false 时检查一次。于是漏掉两种:上面第 1 种
 * (卸载时 open 始终是 true,那个 effect 根本不会进分支),以及「关掉之后 250ms 内就卸载」
 * (清理函数把定时器取消了)。而真正留下锁的那个浮层,可能压根不是 ModalShell —— Select、
 * 右键菜单、图片预览都能上锁,它们谁都不认识 ModalShell。
 *
 * 所以改成盯住**锁本身**:body 的 style 一变就看一眼,DOM 里确实没有开着的 Radix 浮层就解锁。
 * 无论是谁上的锁、以什么方式消失的,都兜得住。
 */

/** DOM 里还开着的 Radix 浮层。开着就不该解锁 —— 那把锁正是它要的。 */
const OPEN_OVERLAY = [
  '[data-state="open"][role="dialog"]',
  '[data-state="open"][role="alertdialog"]',
  '[data-state="open"][role="menu"]',
  '[data-state="open"][role="listbox"]',
  "[data-radix-menu-content][data-state=\"open\"]",
  "[data-radix-select-content][data-state=\"open\"]",
  '[data-radix-popper-content-wrapper] [data-state="open"]',
].join(", ");

/** 现在有没有浮层真的开着。导出给测试用 —— 这条判据错了就会把别人的模态屏蔽误清掉。 */
export function hasOpenOverlay(doc: Document = document): boolean {
  return Boolean(doc.querySelector(OPEN_OVERLAY));
}

/** body 上有锁、但没有任何浮层开着 = 这把锁是被落下的。 */
export function isStalePointerLock(doc: Document = document): boolean {
  return doc.body.style.pointerEvents === "none" && !hasOpenOverlay(doc);
}

/**
 * 开始盯着这把锁。返回停止函数。
 *
 * 检查**延后一拍**:浮层关闭时 Radix 先改 body、再把节点从 DOM 里摘掉(或反过来),中间那一帧
 * 两者都成立,当场判断会误判成"锁是落下的"而提前解锁 —— 那会让正在关闭的模态短暂漏出点击。
 * 延后到下一轮宏任务再看,两边都已经落定。
 */
export function watchBodyPointerLock(doc: Document = document, delayMs = 300): () => void {
  let timer = 0;
  const check = () => {
    if (isStalePointerLock(doc)) doc.body.style.pointerEvents = "";
  };
  const schedule = () => {
    // **没上锁就什么都不做。** 下面盯的是整棵子树,而这个应用里 DOM 一直在动(画布、轮询、
    // 流式输出);不先挡一道的话,每一批变更都要起一个定时器,而绝大多数时候根本没有锁要兜。
    if (doc.body.style.pointerEvents !== "none") return;
    if (timer) clearTimeout(timer);
    timer = (doc.defaultView ?? window).setTimeout(check, delayMs);
  };
  const observer = new (doc.defaultView ?? window).MutationObserver(schedule);
  // 只盯 body 自己的 style,以及子树的增删 —— 浮层被卸载时 body 的 style 可能一动不动,
  // 而"没有浮层了"这件事只体现在子树上。
  observer.observe(doc.body, { attributes: true, attributeFilter: ["style"] });
  observer.observe(doc.body, { childList: true, subtree: true });
  schedule();
  return () => {
    observer.disconnect();
    if (timer) clearTimeout(timer);
  };
}
