/** @vitest-environment jsdom */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  CANVAS_INPUT_KEY,
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
