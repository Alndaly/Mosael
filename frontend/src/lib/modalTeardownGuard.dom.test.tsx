/** @vitest-environment jsdom */
import { render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { useModalTeardownGuard } from "./modalTeardownGuard";

function Guarded() {
  useModalTeardownGuard();
  return null;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("卸载后的那一拍清理它挂上时的那份文档,不读全局的 document —— 测试环境那时可能已经拆掉了", () => {
  // 真机上的样子:BoardPendingLink 的测试跑完、jsdom 拆掉之后才轮到这一拍,报 document is not defined,
  // 整套测试全过、退出码却是 1。
  vi.useFakeTimers();
  const view = render(<Guarded />);
  const doc = document;
  doc.body.style.setProperty("pointer-events", "none");
  view.unmount();
  vi.stubGlobal("document", undefined);
  expect(() => vi.runAllTimers()).not.toThrow();
  vi.unstubAllGlobals();
  expect(doc.body.style.getPropertyValue("pointer-events"), "照样清掉了卡住的 pointer-events").toBe("");
});
