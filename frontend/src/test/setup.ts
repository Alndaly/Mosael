/**
 * 测试环境准备。
 *
 * 只在 jsdom 环境下装 DOM 断言与清理:纯函数测试仍跑在 node 环境(快得多),那里没有 document,
 * 装了反而会炸。判据用 typeof document 而不是环境变量,免得两处配置各说各话。
 */
if (typeof document !== "undefined") {
  await import("@testing-library/jest-dom/vitest");
  const { cleanup, configure } = await import("@testing-library/react");
  // `findBy*` / `waitFor` 等的是条件,条件一成立就返回 —— 上限给多大都不花钱,只在真红的时候多等一会儿。默认的 1 秒
  // 在整套并行跑、机器满载时不够:AI Studio 那一页挂上、拉完假数据、画出「生成中」要一秒多(实测 findByRole 超时)。
  // 给 4 秒:留在单条用例 15 秒的上限(vite.config 的 testTimeout)里面,红的时候报的还是「找不到什么」而不是「超时」。
  configure({ asyncUtilTimeout: 4_000 });
  const { afterEach } = await import("vitest");
  afterEach(() => {
    cleanup();
    // 悬停说明记着「焦点是不是键盘切过来的」(components/ui/tooltip 的模块级标记,按 Tab 记上、指针一动清掉)。
    // 不清的话,上一条测试按过 Tab,这一条里对话框自动聚焦到的那个控件就冒出说明 —— 依赖先后的绿,单独跑或打乱顺序就红。
    document.dispatchEvent(new Event("pointerdown"));
  });

  // jsdom 没有 matchMedia,而项目里的响应式分支全走 useMediaMatch —— 少了它,任何渲染到
  // 带断点组件的用例都会在 useSyncExternalStore 里炸,报的还是 React 内部栈,看不出是环境缺口。
  // 默认不匹配(宽屏);要测窄屏的用例自己覆盖 window.matchMedia。
  if (!window.matchMedia) {
    window.matchMedia = (query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener() {},
        removeEventListener() {},
        addListener() {},
        removeListener() {},
        dispatchEvent: () => false,
      }) as MediaQueryList;
  }

  // radix 的下拉走 Pointer Events 和 scrollIntoView,jsdom 两样都没有 —— 缺了它们,
  // 点一下触发器就在 radix 内部炸,报的是库里的栈,看不出是环境缺口。
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = () => false;
    Element.prototype.setPointerCapture = () => {};
    Element.prototype.releasePointerCapture = () => {};
  }
  Element.prototype.scrollIntoView ??= () => {};

  // jsdom 没有 Range 的版面接口。TipTap 的 focus() 会在下一帧把选区滚进视野(scrollIntoView →
  // ProseMirror coordsAtPos → range.getClientRects),那一帧落在用例结束之后时,报成一条
  // 「unhandled error」让整轮测试失败 —— 本机和 CI 的帧时机不同,于是 CI 上时红时绿。
  // 给空矩形即可:没有版面,滚不滚都一样。
  Range.prototype.getClientRects ??= () => ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] }) as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect ??= () => new DOMRect(0, 0, 0, 0);

  // jsdom 没有 DOMMatrixReadOnly。React Flow 重新量一个节点的接点(useUpdateNodeInternals)时拿它从画布的
  // transform 读缩放 —— 工作流节点的接点一变(开始节点的参数改名、加一行)就会量,那一帧在 jsdom 里报成
  // 「unhandled error」让整轮测试失败。给单位矩阵即可:jsdom 没有版面,量出来本来都是 0。
  window.DOMMatrixReadOnly ??= class {
    a = 1; b = 0; c = 0; d = 1; e = 0; f = 0;
    m11 = 1; m12 = 0; m21 = 0; m22 = 1; m41 = 0; m42 = 0;
  } as unknown as typeof DOMMatrixReadOnly;

  // jsdom 30.1 的焦点回归:获得焦点的元素被移出 DOM 后,它把「上一个焦点」记成 document;
  // 下一次 focus() 时就对 document 派发 blur,并按规则转发到 window。浏览器不会这样 —— 焦点
  // 在同一个文档里移动时,文档同时在新旧两条焦点链上,规范里它不失焦。
  // 而 radix 的菜单打开期间一收到 window 的 blur 就关菜单,于是「上一条测试卸载时焦点正在菜单
  // 里」的下一条菜单测试,菜单开了立刻又关,表现为 9 条毫不相干的失败。
  // 只拦这一种:目标是 window、relatedTarget 是本页里的元素 —— 真的窗口失焦 relatedTarget 是 null。
  // 「目标是 window」用 eventPhase 判:vitest 暴露的全局 window 和 jsdom 派发时的 Window 不是同一个引用。
  // 验证能否删:去掉这段跑 src/test/jsdomFocus.dom.test.tsx。
  window.addEventListener("blur", (event) => {
    const next = (event as FocusEvent).relatedTarget;
    if (event.eventPhase === Event.AT_TARGET && next instanceof Node && document.contains(next)) event.stopImmediatePropagation();
  }, true);
}
export {};
