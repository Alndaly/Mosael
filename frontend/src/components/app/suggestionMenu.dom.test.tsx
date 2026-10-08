/** @vitest-environment jsdom */
import React from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useSuggestionMenu, type SuggestionMenu } from "./suggestionMenu";

const positioning = vi.hoisted(() => ({ update: () => {}, cleanup: vi.fn(), options: {} as Record<string, unknown> }));
vi.mock("@floating-ui/dom", () => ({
  offset: vi.fn(), flip: vi.fn(), shift: vi.fn(),
  autoUpdate: (_reference: unknown, _element: unknown, update: () => void) => {
    positioning.update = update;
    update();
    return positioning.cleanup;
  },
  computePosition: (reference: { getBoundingClientRect: () => DOMRect }, _element: unknown, options: Record<string, unknown>) => {
    positioning.options = options;
    const rect = reference.getBoundingClientRect();
    return Promise.resolve({ x: rect.x, y: rect.bottom + 6 });
  },
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

let menu: SuggestionMenu<string>;
function Harness() {
  menu = useSuggestionMenu<string>();
  return <menu.Portal>{(item) => <button onClick={() => menu.choose(item)}>{item}</button>}</menu.Portal>;
}

it("keeps the same menu DOM and caret anchor when suggestions update or their decoration briefly disappears", async () => {
  render(<Harness />);
  let rect: DOMRect | null = new DOMRect(420, 300, 0, 20);
  const props = { items: ["one", "two"], command: vi.fn(), clientRect: () => rect };
  const lifecycle = menu.render();
  act(() => lifecycle.onStart(props));
  const element = document.querySelector<HTMLElement>("[data-suggestion-menu]")!;
  await waitFor(() => expect(element.style.left).toBe("420px"));
  expect(element.style.top).toBe("326px");
  expect(positioning.options.strategy).toBe("fixed");

  rect = null;
  act(() => {
    lifecycle.onUpdate({ ...props, items: ["two"] });
    positioning.update();
  });
  await waitFor(() => expect(element.textContent).toBe("two"));
  expect(document.querySelector("[data-suggestion-menu]")).toBe(element);
  expect(element.style.left).toBe("420px");
  expect(element.style.visibility).toBe("visible");

  rect = new DOMRect(180, 160, 0, 20);
  act(() => positioning.update());
  await waitFor(() => expect(element.style.left).toBe("180px"));
  act(() => lifecycle.onKeyDown({ event: new KeyboardEvent("keydown", { key: "Enter" }) }));
  expect(props.command).toHaveBeenCalledWith("two");
  act(() => lifecycle.onExit());
  expect(document.querySelector("[data-suggestion-menu]")).toBeNull();
  expect(positioning.cleanup).toHaveBeenCalled();
});

it("stays hidden until a real caret rectangle exists instead of flashing at the origin", async () => {
  render(<Harness />);
  let rect = new DOMRect();
  act(() => menu.render().onStart({ items: ["one"], command: vi.fn(), clientRect: () => rect }));
  const element = document.querySelector<HTMLElement>("[data-suggestion-menu]")!;
  expect(element.style.visibility).toBe("hidden");
  rect = new DOMRect(240, 160, 1, 20);
  act(() => positioning.update());
  await waitFor(() => expect(element.style.visibility).toBe("visible"));
  expect(element.style.left).toBe("240px");
});

it("opened from the window chrome (the ComfyUI workbench column, z 200): lifted over it and marked as chrome, like a Popover there", async () => {
  const { HintRegion } = await import("@/components/ui/tooltip");
  render(<HintRegion.Provider value={{ side: "left" }}><Harness /></HintRegion.Provider>);
  act(() => menu.render().onStart({ items: ["one"], command: vi.fn(), clientRect: () => new DOMRect(10, 10, 1, 20) }));
  const element = document.querySelector<HTMLElement>("[data-suggestion-menu]")!;
  expect(element.className).toContain("z-[210]");
  expect(element.className).not.toContain("z-50");
  expect(element.hasAttribute("data-app-chrome")).toBe(true);
  cleanup();
  render(<Harness />);
  act(() => menu.render().onStart({ items: ["one"], command: vi.fn(), clientRect: () => new DOMRect(10, 10, 1, 20) }));
  const plain = document.querySelector<HTMLElement>("[data-suggestion-menu]")!;
  expect(plain.className, "elsewhere it stays in the normal floating layer").toContain("z-50");
  expect(plain.hasAttribute("data-app-chrome")).toBe(false);
});

it("a caller whose `view` changes identity every render (an inline arrow) does not send the menu into a render loop", async () => {
  //: 智能体输入框就是这么写的:`view: (items) => items.slice(0, N)`。此前 hook 每次重算都回一个新对象,
  //: 「渲染 → effect → setState → 渲染」转个不停(菜单开着时每秒上百次)。
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  let renders = 0;
  let inline: SuggestionMenu<string>;
  function Inline() {
    renders += 1;
    //: 死循环时让它当场炸,而不是把测试进程拖到内存耗尽。
    if (renders > 60) throw new Error("render loop: the menu never stops re-rendering");
    inline = useSuggestionMenu<string>({ view: (items) => items.slice(0, 5) });
    return <inline.Portal>{(item) => <span>{item}</span>}</inline.Portal>;
  }
  render(<Inline />);
  act(() => inline.render().onStart({ items: ["one", "two"], command: vi.fn(), clientRect: () => new DOMRect(10, 10, 1, 20) }));
  const settled = renders;
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 200));
  });
  expect(renders - settled).toBeLessThanOrEqual(1);
  expect(inline!.menu?.items).toEqual(["one", "two"]);
  expect(errors.mock.calls.filter((args) => String(args[0]).includes("Maximum update depth"))).toHaveLength(0);
  errors.mockRestore();
});

it("keyboard highlight survives a recompute over the same candidates", () => {
  render(<Harness />);
  const lifecycle = menu.render();
  const props = { items: ["one", "two", "three"], command: vi.fn(), clientRect: () => new DOMRect(10, 10, 1, 20) };
  act(() => lifecycle.onStart(props));
  act(() => lifecycle.onKeyDown({ event: new KeyboardEvent("keydown", { key: "ArrowDown" }) }));
  act(() => lifecycle.onUpdate({ ...props, items: [...props.items] }));
  expect(menu.menu?.active).toBe(1);
  act(() => lifecycle.onUpdate({ ...props, items: ["three"] }));
  expect(menu.menu?.active, "a different batch starts from the top").toBe(0);
});
