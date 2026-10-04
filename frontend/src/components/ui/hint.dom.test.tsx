/** @vitest-environment jsdom */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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

describe("只能画在一条窄带里的说明(内嵌浏览器的顶栏)", () => {
  // 顶栏下面是原生网页视图,盖在一切 DOM 上:说明往下出就被盖住,往上出又出了窗口。
  const content = () => document.querySelector("[data-tooltip]") as HTMLElement | null;

  it("带里的说明默认往左右出(竖直方向夹在带里),不往下掉进网页那一块", () => {
    render(
      <TooltipProvider delayDuration={0}>
        <HintRegion.Provider value={{ band: { top: 0, height: 56 } }}>
          <Hint label="截屏" hint="可见区域、整页长图或框选一块">
            <button type="button" aria-label="截屏">S</button>
          </Hint>
        </HintRegion.Provider>
      </TooltipProvider>,
    );
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => screen.getByRole("button", { name: "截屏" }).focus());
    expect(screen.getByRole("tooltip").textContent).toBe("截屏可见区域、整页长图或框选一块");
    expect(content()?.getAttribute("data-side")).toBe("left");
    // 顶栏 z 200,比浮层那一层高:标上记号,styles.css 把它抬到顶栏上面。
    expect(content()?.hasAttribute("data-over-chrome")).toBe(true);
  });

  it("侧栏里(不限位置)照常往上出,但也压在侧栏上面;应用里的说明不带这个记号", () => {
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label="外面">
          <button type="button" aria-label="外面">O</button>
        </Hint>
        <HintRegion.Provider value={{ band: null }}>
          <Hint label="侧栏">
            <button type="button" aria-label="侧栏">D</button>
          </Hint>
        </HintRegion.Provider>
      </TooltipProvider>,
    );
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => screen.getByRole("button", { name: "外面" }).focus());
    expect(content()?.hasAttribute("data-over-chrome")).toBe(false);
    act(() => screen.getByRole("button", { name: "侧栏" }).focus());
    expect(content()?.getAttribute("data-side")).toBe("top");
    expect(content()?.hasAttribute("data-over-chrome")).toBe(true);
  });

  it("带外照旧往上出;带里显式给了方向就听它的", () => {
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label="外面">
          <button type="button" aria-label="外面">O</button>
        </Hint>
        <HintRegion.Provider value={{ band: { top: 0, height: 56 } }}>
          <Hint label="右边" side="right">
            <button type="button" aria-label="右边">R</button>
          </Hint>
        </HintRegion.Provider>
      </TooltipProvider>,
    );
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => screen.getByRole("button", { name: "外面" }).focus());
    expect(content()?.getAttribute("data-side")).toBe("top");
    act(() => screen.getByRole("button", { name: "右边" }).focus());
    expect(content()?.getAttribute("data-side")).toBe("right");
  });

  it("带里被截断的字(顶栏的状态那一句)看全文也往左右出", async () => {
    render(
      <TooltipProvider delayDuration={0}>
        <HintRegion.Provider value={{ band: { top: 0, height: 56 } }}>
          <Truncate>一段很长很长的报错</Truncate>
        </HintRegion.Provider>
      </TooltipProvider>,
    );
    const text = screen.getByText("一段很长很长的报错");
    Object.defineProperty(text, "scrollWidth", { value: 500, configurable: true });
    Object.defineProperty(text, "clientWidth", { value: 100, configurable: true });
    fireEvent.pointerEnter(text);
    fireEvent.pointerMove(text);
    await screen.findByRole("tooltip", {}, { timeout: 2000 });
    expect(content()?.getAttribute("data-side")).toBe("left");
  });
});
