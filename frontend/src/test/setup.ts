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
}
export {};
