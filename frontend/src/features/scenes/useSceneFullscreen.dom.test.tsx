/** @vitest-environment jsdom */
import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useSceneFullscreen } from "./useSceneFullscreen";
function Harness() {
  const root = React.useRef<HTMLDivElement>(null);
  const fullscreen = useSceneFullscreen(root);
  return (
    <div>
      <aside data-testid="chrome">
        <button>App navigation</button>
      </aside>
      <div ref={root}>
        <output>{fullscreen.active ? "viewport" : "normal"}</output>
        <button onClick={() => void fullscreen.toggle()}>Viewport</button>
      </div>
    </div>
  );
}
let element: Element | null = null;
function native(reject = false) {
  Object.defineProperty(document, "fullscreenElement", {
    configurable: true,
    get: () => element,
  });
  Object.defineProperty(document, "fullscreenEnabled", {
    configurable: true,
    value: true,
  });
  const request = vi.fn(async () => {
    if (reject) throw new Error("Embedded client");
    element = document.documentElement;
    document.dispatchEvent(new Event("fullscreenchange"));
  });
  const exit = vi.fn(async () => {
    element = null;
    document.dispatchEvent(new Event("fullscreenchange"));
  });
  Object.defineProperty(document.documentElement, "requestFullscreen", {
    configurable: true,
    value: request,
  });
  Object.defineProperty(document, "exitFullscreen", {
    configurable: true,
    value: exit,
  });
  return { request, exit };
}
afterEach(() => {
  cleanup();
  element = null;
  vi.restoreAllMocks();
});
it("keeps menus within document fullscreen, hides the app chrome, and follows a native exit", async () => {
  const api = native();
  render(<Harness />);
  fireEvent.click(screen.getByText("Viewport"));
  await waitFor(() => expect(api.request).toHaveBeenCalledOnce());
  expect(screen.getByRole("status")).toHaveTextContent("viewport");
  expect(screen.getByTestId("chrome").style.visibility).toBe("hidden");
  // 退出全屏可以不经过我们:浏览器的 Esc、系统手势都会直接触发 fullscreenchange。
  act(() => {
    element = null;
    document.dispatchEvent(new Event("fullscreenchange"));
  });
  expect(screen.getByRole("status")).toHaveTextContent("normal");
  expect(screen.getByTestId("chrome").style.visibility).toBe("");
});
it("keeps full-window mode when the host refuses native fullscreen and leaves it on Escape", async () => {
  const api = native(true);
  render(<Harness />);
  fireEvent.click(screen.getByText("Viewport"));
  await waitFor(() => expect(api.request).toHaveBeenCalledOnce());
  expect(screen.getByRole("status")).toHaveTextContent("viewport");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.getByRole("status")).toHaveTextContent("normal");
  expect(api.exit).not.toHaveBeenCalled();
});
it("exits native fullscreen on Escape while letting open dialogs consume Escape first", async () => {
  const api = native();
  render(<Harness />);
  fireEvent.click(screen.getByText("Viewport"));
  await waitFor(() => expect(api.request).toHaveBeenCalledOnce());
  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("data-state", "open");
  document.body.append(dialog);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.getByRole("status")).toHaveTextContent("viewport");
  expect(api.exit).not.toHaveBeenCalled();
  dialog.remove();
  fireEvent.keyDown(window, { key: "Escape" });
  await waitFor(() => expect(api.exit).toHaveBeenCalledOnce());
  expect(screen.getByRole("status")).toHaveTextContent("normal");
  expect(screen.getByTestId("chrome").style.visibility).toBe("");
});
it("exits only fullscreen acquired by this editor when navigating away", async () => {
  const api = native();
  const view = render(<Harness />);
  fireEvent.click(screen.getByText("Viewport"));
  await waitFor(() => expect(api.request).toHaveBeenCalledOnce());
  view.unmount();
  expect(api.exit).toHaveBeenCalledOnce();
});
