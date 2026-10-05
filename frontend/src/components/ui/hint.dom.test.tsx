/** @vitest-environment jsdom */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readHint } from "@/test/hint";

import { Hint, HintRegion, TooltipProvider } from "./tooltip";
import { Truncate } from "./truncate";

function mount() {
  render(
    <TooltipProvider delayDuration={0}>
      <Hint label="让 AI 写" hint="在这张便签下面打开 AI 写作">
        <button type="button" aria-label="让 AI 写">A</button>
      </Hint>
      <Hint label="翻译">
        <button type="button" aria-label="翻译">B</button>
      </Hint>
    </TooltipProvider>,
  );
  return [screen.getByRole("button", { name: "让 AI 写" }), screen.getByRole("button", { name: "翻译" })];
}

describe("图标按钮的悬停说明", () => {
  it("键盘切过来时出:名字一行、说明一行", () => {
    const [write] = mount();
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => write.focus());
    expect(screen.getByRole("tooltip").textContent).toBe("让 AI 写在这张便签下面打开 AI 写作");
  });

  it("焦点被还回来(关掉菜单、面板之后)不出 —— 否则那条说明挂在按钮上,移到别的按钮也不走", () => {
    const [write] = mount();
    fireEvent.pointerDown(document.body);
    act(() => write.focus());
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("同一时刻只有一条:下一条出来,上一条收起", () => {
    const [write, translate] = mount();
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => write.focus());
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => translate.focus());
    expect(screen.getAllByRole("tooltip").map((one) => one.textContent)).toEqual(["翻译"]);
  });

  it("快捷键用键帽画在名字那一行,不拼进文字", async () => {
    render(
      <Hint label="撤销" shortcut="⌘Z">
        <button type="button" aria-label="撤销">U</button>
      </Hint>,
    );
    expect(await readHint(screen.getByRole("button", { name: "撤销" }))).toBe("撤销⌘Z");
    const tooltip = document.querySelector("[data-hint]")!;
    expect(tooltip.querySelector("kbd")?.textContent).toBe("⌘Z");
  });

  it("几个键任选其一:每个键一颗键帽", async () => {
    render(
      <Hint label="重做" shortcut={["⇧⌘Z", "⌘Y"]}>
        <button type="button" aria-label="重做">R</button>
      </Hint>,
    );
    await readHint(screen.getByRole("button", { name: "重做" }));
    expect([...document.querySelectorAll("[data-hint] kbd")].map((one) => one.textContent)).toEqual(["⇧⌘Z", "⌘Y"]);
  });

  it("外面没有 TooltipProvider 也能用 —— 单独渲染一个组件时不该抛错", () => {
    expect(() =>
      render(
        <Hint label="删除">
          <button type="button" aria-label="删除">D</button>
        </Hint>,
      ),
    ).not.toThrow();
  });
});

describe("有时有说明的控件", () => {
  it("没有可说的就不出说明,而且结构不变 —— 说明来去时控件不会被换掉、丢了焦点", async () => {
    const { rerender } = render(
      <Hint label={undefined}>
        <input aria-label="名字" />
      </Hint>,
    );
    const input = screen.getByRole("textbox", { name: "名字" });
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => input.focus());
    expect(screen.queryByRole("tooltip")).toBeNull();
    rerender(
      <Hint label="名字不能为空">
        <input aria-label="名字" />
      </Hint>,
    );
    expect(screen.getByRole("textbox", { name: "名字" })).toBe(input);
    expect(document.activeElement).toBe(input);
  });

  it("文字按钮上只写点不了的原因:说明里就只有原因,不把按钮上的字再念一遍", async () => {
    render(
      <Hint disabledReason="先保存再运行">
        <button type="button" disabled>运行</button>
      </Hint>,
    );
    expect(await readHint(screen.getByRole("button", { name: "运行" }))).toBe("先保存再运行");
  });
});

describe("点不了的按钮说出为什么", () => {
  it("disabled 的按钮自己收不到悬停:套一层能接住指针和键盘的外壳,说明里写原因", async () => {
    render(
      <Hint label="撤销" disabledReason="没有可撤销的操作">
        <button type="button" aria-label="撤销" disabled>U</button>
      </Hint>,
    );
    const button = screen.getByRole("button", { name: "撤销" });
    expect(button).toBeDisabled();
    const shell = button.parentElement!;
    expect(shell.hasAttribute("data-hint-disabled")).toBe(true);
    expect(shell.tabIndex).toBe(0);
    expect(await readHint(button)).toBe("撤销没有可撤销的操作");
  });

  it("不给原因就不套壳 —— 能点的按钮结构不变", () => {
    render(
      <Hint label="撤销" disabledReason={false}>
        <button type="button" aria-label="撤销">U</button>
      </Hint>,
    );
    expect(screen.getByRole("button", { name: "撤销" }).parentElement?.hasAttribute("data-hint-disabled")).toBe(false);
  });
});

describe("内嵌浏览器外壳(顶栏、页面列表、侧栏)里的说明", () => {
  // 外壳旁边就是原生网页视图,盖在一切 DOM 上。说明交给一块透明的原生浮层视图画(见 electron/publish/floatLayer),
  // DOM 里那份只用来量位置、给读屏。没有浮层视图(网页版)时照旧画在 DOM 里,压在外壳上面。
  const content = () => document.querySelector("[data-tooltip]") as HTMLElement | null;
  const showFloat = vi.fn();
  const hideFloat = vi.fn();

  function chrome(side: "bottom" | "right" | "left" | "top" = "bottom") {
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label="外面">
          <button type="button" aria-label="外面">O</button>
        </Hint>
        <HintRegion.Provider value={{ side }}>
          <Hint label="截屏" hint="可见区域、整页长图或框选一块">
            <button type="button" aria-label="截屏">S</button>
          </Hint>
          <Hint label="右边" side="right">
            <button type="button" aria-label="右边">R</button>
          </Hint>
        </HintRegion.Provider>
      </TooltipProvider>,
    );
    fireEvent.keyDown(document, { key: "Tab" });
  }

  beforeEach(() => {
    showFloat.mockClear();
    hideFloat.mockClear();
    Object.defineProperty(window, "mosaelPublish", { configurable: true, value: { showFloat, hideFloat } });
  });
  afterEach(() => {
    Object.defineProperty(window, "mosaelPublish", { configurable: true, value: undefined });
  });

  it("交给浮层视图画在网页上面:内容、位置、主题都交过去;DOM 里那份看不见但读屏照样念;收起时浮层也收起", async () => {
    chrome();
    act(() => screen.getByRole("button", { name: "截屏" }).focus());
    await waitFor(() => expect(showFloat).toHaveBeenCalled());
    const payload = showFloat.mock.calls.at(-1)![0];
    expect(payload.html).toContain("截屏");
    expect(payload.html).toContain("可见区域、整页长图或框选一块");
    expect(Object.keys(payload.rect).sort()).toEqual(["height", "width", "x", "y"]);
    expect(payload.id).toEqual(expect.any(String));
    expect(payload.root).toEqual(expect.objectContaining({ className: expect.any(String), attributes: expect.any(Object) }));
    expect(content()!.parentElement!.style.opacity).toBe("0");
    expect(screen.getByRole("tooltip").textContent).toBe("截屏可见区域、整页长图或框选一块");
    act(() => screen.getByRole("button", { name: "外面" }).focus());
    await waitFor(() => expect(hideFloat).toHaveBeenCalledWith(payload.id));
  });

  it("顶栏里默认往下出(盖在网页上);显式给了方向就听它的", async () => {
    chrome("bottom");
    act(() => screen.getByRole("button", { name: "截屏" }).focus());
    await waitFor(() => expect(content()?.getAttribute("data-side")).toBe("bottom"));
    act(() => screen.getByRole("button", { name: "右边" }).focus());
    await waitFor(() => expect(content()?.getAttribute("data-side")).toBe("right"));
  });

  it("区域外的说明照旧画在 DOM 里,不交给浮层", async () => {
    chrome();
    act(() => screen.getByRole("button", { name: "外面" }).focus());
    expect(content()?.getAttribute("data-side")).toBe("top");
    expect(content()?.hasAttribute("data-over-chrome")).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(showFloat).not.toHaveBeenCalled();
  });

  it("没有浮层视图(网页版):照旧画在 DOM 里,压在外壳上面", async () => {
    Object.defineProperty(window, "mosaelPublish", { configurable: true, value: undefined });
    chrome();
    act(() => screen.getByRole("button", { name: "截屏" }).focus());
    expect(content()?.hasAttribute("data-over-chrome")).toBe(true);
    expect(content()!.parentElement!.style.opacity).not.toBe("0");
  });

  it("区域里被截断的字看全文也交给浮层", async () => {
    render(
      <TooltipProvider delayDuration={0}>
        <HintRegion.Provider value={{ side: "right" }}>
          <Truncate>一段很长很长的页面标题</Truncate>
        </HintRegion.Provider>
      </TooltipProvider>,
    );
    const text = screen.getByText("一段很长很长的页面标题");
    Object.defineProperty(text, "scrollWidth", { value: 500, configurable: true });
    Object.defineProperty(text, "clientWidth", { value: 100, configurable: true });
    fireEvent.pointerEnter(text);
    fireEvent.pointerMove(text);
    await screen.findByRole("tooltip", {}, { timeout: 2000 });
    expect(content()?.getAttribute("data-side")).toBe("right");
    await waitFor(() => expect(showFloat).toHaveBeenCalled());
    expect(showFloat.mock.calls.at(-1)![0].html).toContain("一段很长很长的页面标题");
  });
});
