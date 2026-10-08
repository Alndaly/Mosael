/** @vitest-environment jsdom */
import * as React from "react";
import { createPortal } from "react-dom";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readHint } from "@/test/hint";

import { Switch } from "./switch";
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

describe("多行的说明", () => {
  it("说明里的换行照写的来:画板格子「详情」里的「原因 + 怎么修」一步一行,不挤成一段", () => {
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label={"那台 ComfyUI 太旧\n1. 升级:\npip install -U x"} hint={"原话\n第二行"}>
          <button type="button" aria-label="详情">详情</button>
        </Hint>
      </TooltipProvider>,
    );
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => screen.getByRole("button", { name: "详情" }).focus());
    const tooltip = screen.getByRole("tooltip");
    //: 最里面那一层(名字外面还套着一层和快捷键并排的 flex)
    const innermost = (text: string) => [...tooltip.querySelectorAll("span")].filter((one) => one.textContent === text).at(-1)!;
    const label = innermost("那台 ComfyUI 太旧\n1. 升级:\npip install -U x");
    const hint = innermost("原话\n第二行");
    expect(label.className).toMatch(/whitespace-pre-line/);
    expect(hint.className).toMatch(/whitespace-pre-line/);
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

describe("说明套在有自己状态的控件上", () => {
  it("开关的 checked / unchecked 不被说明的 closed / delayed-open 盖掉 —— 否则开关只剩一个看不见状态的淡点(浏览器池卡片)", async () => {
    function Toggle() {
      const [on, setOn] = React.useState(true);
      return (
        <TooltipProvider delayDuration={0}>
          <Hint label="启用这个账号">
            <Switch checked={on} onCheckedChange={setOn} aria-label="启用" />
          </Hint>
        </TooltipProvider>
      );
    }
    render(<Toggle />);
    const toggle = screen.getByRole("switch", { name: "启用" });
    expect(toggle.getAttribute("data-state")).toBe("checked");
    expect(await readHint(toggle)).toBe("启用这个账号");
    expect(toggle.getAttribute("data-state")).toBe("checked");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("data-state")).toBe("unchecked");
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

/**
 * 「这一下该不该出说明」只在说明的触发器里判(tooltip.tsx 的 TooltipTrigger)。Radix 一试图打开就先广播一声把别的说明
 * 全关掉,在 onOpenChange 里再拒绝已经晚了 —— 下面每一条都是「Radix 先动了手」留下的闪烁。
 */
describe("说明只在真有人要看的时候出:不闪", () => {
  /** 说明浮层挂上、卸下的次序。一闪而过就是挂上又卸下。 */
  function watchTooltips() {
    const events: string[] = [];
    const has = (node: Node) =>
      node instanceof HTMLElement && (node.matches("[data-tooltip]") || node.querySelector("[data-tooltip]") !== null);
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) if (has(node)) events.push("mount");
        for (const node of record.removedNodes) if (has(node)) events.push("unmount");
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return events;
  }
  const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 20)));
  const hover = (element: HTMLElement) => {
    fireEvent.pointerEnter(element);
    fireEvent.pointerMove(element);
  };

  it("一个控件套两层说明、里层没话说(画板的「4×」):指针从外层挪进里层的按钮,一直是外层那一条,挂在外层上,不先开再被关掉", async () => {
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label="跑几遍" hint="每遍按工作流原样出 4 张">
          <span data-testid="outer">
            <Hint label={undefined}>
              <button type="button" aria-label="一次落出几格">4×</button>
            </Hint>
          </span>
        </Hint>
      </TooltipProvider>,
    );
    const outer = screen.getByTestId("outer");
    const inner = screen.getByRole("button", { name: "一次落出几格" });
    const events = watchTooltips();
    //: 指针先落在外层够得着、里层够不着的那条边上(从右边的发送键移过来就是这样),说明出来
    hover(outer);
    await screen.findByRole("tooltip");
    //: 再挪进里层的按钮:此前里层那条没话说的 Hint 也去敲 Radix 的门,Radix 广播一声把外层这条关了
    hover(inner);
    await settle();
    const tooltips = screen.getAllByRole("tooltip");
    expect(tooltips.map((one) => one.textContent)).toEqual(["跑几遍每遍按工作流原样出 4 张"]);
    expect(document.querySelector("[data-tooltip]")?.getAttribute("data-state")).not.toBe("closed");
    expect(outer.getAttribute("aria-describedby"), "说明挂在外层的触发器上").toBe(tooltips[0].id);
    expect(inner.hasAttribute("aria-describedby")).toBe(false);
    expect(events, "只挂上一次,没有卸下再挂").toEqual(["mount"]);
  });

  it("两层都有话说:指针在里层时只出里层那一条 —— 外层不跟着开出来把它顶掉", async () => {
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label="外层">
          <span>
            <Hint label="里层">
              <button type="button">B</button>
            </Hint>
          </span>
        </Hint>
      </TooltipProvider>,
    );
    const events = watchTooltips();
    hover(screen.getByRole("button"));
    await screen.findByRole("tooltip");
    await settle();
    expect(screen.getAllByRole("tooltip").map((one) => one.textContent)).toEqual(["里层"]);
    expect(events).toEqual(["mount"]);
  });

  it("Hint 包着一个自带弹出清单的控件:在清单里移动指针、用方向键挑选项,外层的说明都不出 —— 此前它挂在触发器上盖着清单,每挪一次焦点开关一次", async () => {
    //: 清单经 portal 渲染到 body 底下,但在 React 的树里它还是 Hint 的子孙 —— 事件顺着 React 的树冒到 Hint 的触发器上
    //: 和 Hint 包着的 <span><Pick/></span> 一样:触发器是一个真正的元素,弹出的清单是它的子组件
    const Picker = React.forwardRef<HTMLSpanElement, React.HTMLAttributes<HTMLSpanElement>>(function Picker(props, ref) {
      return (
        <span ref={ref} {...props}>
          <button type="button">4×</button>
          {createPortal(
            <div role="listbox">
              <button type="button" role="option" aria-selected="false">8×</button>
              <button type="button" role="option" aria-selected="false">12×</button>
            </div>,
            document.body,
          )}
        </span>
      );
    });
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label="跑几遍">
          <Picker />
        </Hint>
      </TooltipProvider>,
    );
    const [eight, twelve] = screen.getAllByRole("option");
    hover(eight);
    await settle();
    expect(screen.queryByRole("tooltip"), "指针在清单里").toBeNull();
    fireEvent.keyDown(document, { key: "ArrowDown" });
    act(() => twelve.focus());
    await settle();
    expect(screen.queryByRole("tooltip"), "方向键挑到下一项").toBeNull();
  });

  it("在菜单里用方向键挑完,按 Esc / Enter 关掉:焦点还回按钮的那一下不出说明", () => {
    const [write, translate] = mount();
    fireEvent.keyDown(document, { key: "ArrowDown" });
    fireEvent.keyDown(document, { key: "Escape" });
    act(() => write.focus());
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.keyDown(document, { key: "ArrowDown" });
    fireEvent.keyDown(document, { key: "Enter" });
    act(() => translate.focus());
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("工具条里用方向键在按钮之间挪(和 Tab 一样是键盘切过来的):出说明", () => {
    const [, translate] = mount();
    fireEvent.keyDown(document, { key: "ArrowRight" });
    act(() => translate.focus());
    expect(screen.getByRole("tooltip").textContent).toBe("翻译");
  });

  it("指针停在上面:只出一次,在上面来回移动不会关了再开", async () => {
    const [write] = mount();
    const events = watchTooltips();
    hover(write);
    await screen.findByRole("tooltip");
    for (let step = 0; step < 5; step += 1) fireEvent.pointerMove(write);
    await settle();
    expect(events).toEqual(["mount"]);
  });
});
