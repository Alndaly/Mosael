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
}
export {};
