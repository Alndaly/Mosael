/** @vitest-environment jsdom */
import * as React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { OptionPicker, SEARCHABLE_THRESHOLD } from "./option-picker";
import { insideDialog } from "./insideDialog";
import { Hint, TooltipProvider } from "./tooltip";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

const options = (count: number) =>
  Array.from({ length: count }, (_, index) => ({ value: `m${index}`, label: `模型 ${index}` }));

// cmdk 在挂载时就要 ResizeObserver;jsdom 没有。放在文件这一层:「选项的副标题」那组也挂可搜索的那版 —— 此前这段写在第一组里,
// 打乱顺序(`vitest --sequence.shuffle`)时副标题那组先跑,就是 `ResizeObserver is not defined`。
beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView ??= () => {};
});

describe("选项一多就带搜索", () => {
  it("短清单还是 Select —— 三个宽高比之间插一行输入框是纯噪音", () => {
    const { container } = render(
      <OptionPicker value="m0" onChange={vi.fn()} options={options(SEARCHABLE_THRESHOLD)} />,
    );
    // 两个分支都顶着 role=combobox(换实现不该换掉读屏听到的东西);短清单的区别是**没有搜索框**。
    expect(container.querySelector('[role="combobox"]')).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    expect(document.querySelector("[cmdk-input]")).toBeNull();
  });

  it("长清单换成可搜索的那一版,并且真的过滤", () => {
    render(<OptionPicker value="m0" onChange={vi.fn()} options={options(SEARCHABLE_THRESHOLD + 1)} />);
    fireEvent.click(screen.getByRole("combobox"));
    const input = document.querySelector("[cmdk-input]") as HTMLInputElement;
    expect(input, "长清单该有搜索框").toBeTruthy();
    fireEvent.change(input, { target: { value: "模型 7" } });
    expect(screen.queryByText("模型 3")).toBeNull();
    expect(screen.getByText("模型 7")).toBeTruthy();
  });

  it("两个分支的触发器共用同一串类名 —— 长短清单在版面上不该看得出区别", () => {
    const style = "h-6 w-auto bg-transparent [&>svg]:hidden";
    const short = render(<OptionPicker value="m0" onChange={vi.fn()} options={options(3)} className={style} />);
    const shortClass = short.container.querySelector("[role='combobox']")!.className;
    short.unmount();
    const long = render(<OptionPicker value="m0" onChange={vi.fn()} options={options(30)} className={style} />);
    const longClass = long.container.querySelector("[role='combobox']")!.className;
    for (const one of style.split(" ")) {
      expect(shortClass, `短清单丢了 ${one}`).toContain(one);
      expect(longClass, `长清单丢了 ${one}`).toContain(one);
    }
  });
});

/**
 * `modal` 会给 `document.body` 挂上 `pointer-events: none`,而 Radix 还原它并不可靠 —— 漏一次
 * 就是**整个应用点击穿透**。所以只在真的躲在 Dialog 的滚动锁后面时才付这个代价。
 *
 * 麻烦在于 Radix 给 PopoverContent 也挂了 `role="dialog"`,而且两边都**不**挂 `aria-modal`。
 * 分辨的记号只剩 popper 包装层。
 */
describe("选项的副标题", () => {
  it("副标题出现在清单里,而不是挤进触发器", async () => {
    // 供应商默认模型那一格永远有值(没配就是"未设置"),placeholder 轮不上;
    // 解释只能挂在选项自己身上。但触发器只该显示"当前选的是什么" —— 把那句解释也塞进去,
    // 这一行就成了两行字的控件,和旁边每一格都不一样高。
    // 两个分支都要测:副标题在可搜索那版和短清单那版是两段不同的代码,只测一边等于没测。
    for (const count of [SEARCHABLE_THRESHOLD + 1, 3]) {
      const view = render(
        <OptionPicker
          value="m0"
          onChange={vi.fn()}
          options={[{ value: "m0", label: "未设置", description: "用到时按能力挑" }, ...options(count)]}
        />,
      );
      const trigger = screen.getByRole("combobox");
      expect(trigger.textContent, `${count} 项:触发器该只说当前选了什么`).toContain("未设置");
      expect(trigger.textContent).not.toContain("用到时按能力挑");
      // Radix 的 Select 在 jsdom 里靠键盘开;可搜索那版是普通按钮,点开即可。
      if (count > SEARCHABLE_THRESHOLD) await userEvent.click(trigger);
      else fireEvent.keyDown(trigger, { key: "Enter" });
      expect(await screen.findByText("用到时按能力挑"), `${count} 项时丢了副标题`).toBeInTheDocument();
      view.unmount();
    }
  });

  it("没得选的时候是禁用的,而不是点开一片空", () => {
    render(<OptionPicker value="x" onChange={vi.fn()} options={[{ value: "x", label: "还没有可用模型" }]} disabled />);
    expect(screen.getByRole("combobox")).toBeDisabled();
  });
});

describe("触发器上的悬停说明", () => {
  const LONG = "watercolor-character.json · 演示 ComfyUI";
  const items = [
    { value: "a", label: LONG },
    { value: "b", label: "短" },
  ];
  /** 让触发器里那段值「放不下」(jsdom 没有版面)。 */
  function clipValue() {
    const value = screen.getByRole("combobox").querySelector<HTMLElement>(".truncate");
    expect(value, "触发器里的值该是一段会截断的字").toBeTruthy();
    Object.defineProperty(value!, "scrollWidth", { value: 400, configurable: true });
    Object.defineProperty(value!, "clientWidth", { value: 120, configurable: true });
  }
  function hover(element: HTMLElement) {
    fireEvent.pointerEnter(element);
    fireEvent.pointerMove(element);
  }

  it("短清单的触发器里被截断的值,悬停看得到全名 —— 此前值是 Radix 从清单里克隆过来的,悬停什么都不出", async () => {
    render(
      <TooltipProvider delayDuration={0}>
        <OptionPicker value="a" onChange={vi.fn()} options={items} />
      </TooltipProvider>,
    );
    clipValue();
    hover(screen.getByRole("combobox"));
    expect((await screen.findByRole("tooltip")).textContent).toBe(LONG);
  });

  it("外面还套着一条说「这一格是什么」的 Hint(画板的参数芯片、「4×」):全名并进外面那一条,只有一条说明", async () => {
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label="目标语言">
          <span>
            <OptionPicker value="a" onChange={vi.fn()} options={items} />
          </span>
        </Hint>
      </TooltipProvider>,
    );
    clipValue();
    hover(screen.getByRole("combobox"));
    await screen.findByRole("tooltip");
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(screen.getAllByRole("tooltip").map((one) => one.textContent)).toEqual([`${LONG}目标语言`]);
  });

  it("键盘打开下拉、方向键挑、Enter 选中:外面那条说明不在下拉开着时冒出来,焦点还回触发器时也不出", async () => {
    const onChange = vi.fn();
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label="跑几遍">
          <span>
            <OptionPicker value="1" onChange={onChange} options={["1", "2", "3"].map((value) => ({ value, label: `${value}×` }))} />
          </span>
        </Hint>
      </TooltipProvider>,
    );
    const trigger = screen.getByRole("combobox");
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => trigger.focus());
    expect(screen.getByRole("tooltip").textContent, "键盘切过来时照样出").toBe("跑几遍");
    fireEvent.keyDown(trigger, { key: "Enter" });
    const options = await screen.findAllByRole("option");
    expect(screen.queryByRole("tooltip"), "下拉一开说明就收起").toBeNull();
    fireEvent.keyDown(document, { key: "ArrowDown" });
    act(() => options[1].focus());
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(screen.queryByRole("tooltip"), "方向键挑选项时").toBeNull();
    fireEvent.keyDown(options[1], { key: "Enter" });
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(onChange).toHaveBeenCalledWith("2");
    expect(screen.queryByRole("tooltip"), "选中后焦点还回触发器").toBeNull();
  });
});

describe("认不认得出「真的在对话框里」", () => {
  const build = (html: string) => {
    const host = document.createElement("div");
    host.innerHTML = html;
    document.body.append(host);
    return host.querySelector("[data-probe]");
  };

  it("对话框里 → 要 modal", () => {
    expect(insideDialog(build(`<div role="dialog"><span data-probe></span></div>`))).toBe(true);
  });

  it("画布上的浮层里 → 不要", () => {
    expect(insideDialog(build(`<div class="panel"><span data-probe></span></div>`))).toBe(false);
  });

  it("设置弹层(Popover)里 → 不要 —— 它顶着 role=dialog,但它不是对话框", () => {
    expect(
      insideDialog(
        build(`<div data-radix-popper-content-wrapper><div role="dialog"><span data-probe></span></div></div>`),
      ),
    ).toBe(false);
  });

  it("对话框里再套一层 Popover → 仍然要 —— 锁背景滚动的是最外面那层", () => {
    expect(
      insideDialog(
        build(
          `<div role="dialog"><div data-radix-popper-content-wrapper><div role="dialog"><span data-probe></span></div></div></div>`,
        ),
      ),
    ).toBe(true);
  });
});
