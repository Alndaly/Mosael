/**
 * 测试环境准备。
 *
 * 只在 jsdom 环境下装 DOM 断言与清理:纯函数测试仍跑在 node 环境(快得多),那里没有 document,
 * 装了反而会炸。判据用 typeof document 而不是环境变量,免得两处配置各说各话。
 */
if (typeof document !== "undefined") {
  await import("@testing-library/jest-dom/vitest");
  const { cleanup } = await import("@testing-library/react");
  const { afterEach } = await import("vitest");
  afterEach(() => cleanup());

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
