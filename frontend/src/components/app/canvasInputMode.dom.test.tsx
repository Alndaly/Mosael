/** @vitest-environment jsdom */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  CANVAS_INPUT_KEY,
  canvasWheelProps,
  readCanvasInputMode,
  setCanvasInputMode,
  useCanvasInputMode,
} from "./canvasInputMode";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  setCanvasInputMode("trackpad");
  localStorage.clear();
});
function Consumer({ name }: { name: string }) {
  const [mode] = useCanvasInputMode();
  return <output data-testid={name}>{mode}</output>;
}
it("preserves the existing 3D preference until a shared choice is made", () => {
  localStorage.setItem("mosael.scene.navigation", "mouse");
  expect(readCanvasInputMode()).toBe("mouse");
  setCanvasInputMode("trackpad");
  expect(readCanvasInputMode()).toBe("trackpad");
  expect(localStorage.getItem(CANVAS_INPUT_KEY)).toBe("trackpad");
});
it("updates mounted views together and responds to another window", () => {
  render(
    <>
      <Consumer name="scene" />
      <Consumer name="board" />
    </>,
  );
  act(() => setCanvasInputMode("mouse"));
  expect(screen.getByTestId("scene").textContent).toBe("mouse");
  expect(screen.getByTestId("board").textContent).toBe("mouse");
  act(() => {
    localStorage.setItem(CANVAS_INPUT_KEY, "trackpad");
    window.dispatchEvent(
      new StorageEvent("storage", { key: CANVAS_INPUT_KEY }),
    );
  });
  expect(screen.getByTestId("scene").textContent).toBe("trackpad");
  expect(screen.getByTestId("board").textContent).toBe("trackpad");
});
it("keeps the new choice usable when storage writes are unavailable", () => {
  localStorage.setItem(CANVAS_INPUT_KEY, "mouse");
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Unavailable");
  });
  setCanvasInputMode("trackpad");
  expect(readCanvasInputMode()).toBe("trackpad");
});

it("画布的滚轮不靠「按住 ⌘」切换:触控板双指永远平移、鼠标滚轮永远缩放,捏合照样缩放", () => {
  //: ⌘ 的抬起常被系统吞掉(聚焦搜索、截图),React Flow 就一直以为它按着 —— 双指滑动变成了缩放。
  expect(canvasWheelProps("trackpad")).toEqual({ panOnScroll: true, zoomOnScroll: false, zoomActivationKeyCode: null });
  expect(canvasWheelProps("mouse")).toEqual({ panOnScroll: false, zoomOnScroll: true, zoomActivationKeyCode: null });
});
