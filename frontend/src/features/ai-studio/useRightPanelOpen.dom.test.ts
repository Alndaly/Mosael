/** @vitest-environment jsdom */
/**
 * AI Studio 右栏:宽屏停靠默认开,窄屏浮层默认关。
 *
 * 走查时 1024 宽一进 AI Studio,浮层就开着盖住了标题和输入框(输入框右侧被压到 995px,浮层从 664px 起)。
 */
import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";

import { useRightPanelOpen } from "@/features/ai-studio/useRightPanelOpen";

it("宽屏默认开、窄屏默认关", () => {
  expect(renderHook(() => useRightPanelOpen(false)).result.current[0]).toBe(true);
  expect(renderHook(() => useRightPanelOpen(true)).result.current[0]).toBe(false);
});

it("窄屏开关抽屉不改宽屏的停靠状态,回到宽屏后抽屉收起", () => {
  const { result, rerender } = renderHook(({ narrow }) => useRightPanelOpen(narrow), { initialProps: { narrow: false } });
  act(() => result.current[1](false));
  expect(result.current[0]).toBe(false);

  rerender({ narrow: true });
  act(() => result.current[1](true));
  expect(result.current[0]).toBe(true);

  rerender({ narrow: false });
  expect(result.current[0]).toBe(false);

  rerender({ narrow: true });
  expect(result.current[0]).toBe(false);
});
