/** @vitest-environment jsdom */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { Combobox } from "@/components/app/combobox";
import { Button } from "@/components/ui/button";
import { CONTROL_HEIGHT, type FieldSize } from "@/components/ui/control-size";
import { Input } from "@/components/ui/input";
import { OptionPicker, SEARCHABLE_THRESHOLD } from "@/components/ui/option-picker";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Select, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TimePicker } from "@/components/ui/time-picker";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

/**
 * 字段的 `size` 落到 DOM 上是**哪一档高度、哪一档字号**。
 *
 * 断言按「东西在哪」查:高度类必须挂在真正画出边框的那个元素上(input 本身、带 role=combobox
 * 的触发器),而不是某个外壳 —— 外壳上的 h-8 让测试变绿,屏幕上的框还是 40px。
 */
const TIERS: Array<[FieldSize, string, string]> = [
  ["xs", CONTROL_HEIGHT.xs, "text-ui-xs"],
  ["sm", CONTROL_HEIGHT.sm, "text-ui-sm"],
  ["md", CONTROL_HEIGHT.md, "text-ui-sm"],
];
const HEIGHTS = Object.values(CONTROL_HEIGHT);

/** 元素上的高度类恰好一个,且是期望那一档 —— 两个高度类同时在就是 cn() 没合并掉。 */
function expectHeight(element: Element, height: string) {
  const classes = element.className.split(/\s+/);
  expect(classes.filter((name) => HEIGHTS.includes(name as (typeof HEIGHTS)[number]))).toEqual([height]);
}

const options = (count: number) =>
  Array.from({ length: count }, (_, index) => ({ value: `v${index}`, label: `选项 ${index}` }));

beforeAll(() => {
  // cmdk 挂载时就要 ResizeObserver;jsdom 没有。
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

describe("Input 的档位", () => {
  it("不写 size 就是 md —— 表单的默认高度", () => {
    render(<Input aria-label="名字" />);
    expectHeight(screen.getByLabelText("名字"), CONTROL_HEIGHT.md);
  });

  it.each(TIERS)("size=%s → %s,字号 %s", (size, height, text) => {
    render(<Input aria-label="名字" size={size} />);
    const input = screen.getByLabelText("名字");
    expectHeight(input, height);
    expect(input.className).toContain(text);
    //: 原生 size 属性(按字符数定宽)不能漏到 DOM 上 —— 那会悄悄改掉输入框的宽度。
    expect(input.hasAttribute("size")).toBe(false);
  });

  it("调用点的字号、留白仍可覆盖,高度不被冲掉", () => {
    render(<Input aria-label="名字" size="sm" className="px-1.5 text-ui-xs" />);
    const input = screen.getByLabelText("名字");
    expectHeight(input, CONTROL_HEIGHT.sm);
    expect(input.className).toContain("text-ui-xs");
    expect(input.className).not.toContain("text-ui-sm");
    expect(input.className).toContain("px-1.5");
    expect(input.className).not.toContain("px-2.5");
  });
});

describe("下拉触发器的档位和输入框同一把尺", () => {
  it.each(TIERS)("SelectTrigger size=%s → %s", (size, height, text) => {
    render(
      <Select value="a">
        <SelectTrigger size={size} aria-label="档">
          <SelectValue />
        </SelectTrigger>
      </Select>,
    );
    const trigger = screen.getByRole("combobox");
    expectHeight(trigger, height);
    expect(trigger.className).toContain(text);
  });

  it.each(TIERS)("OptionPicker 两个分支 size=%s 同一档", (size, height) => {
    const { unmount } = render(<OptionPicker value="v0" onChange={vi.fn()} options={options(SEARCHABLE_THRESHOLD)} size={size} />);
    expectHeight(screen.getByRole("combobox"), height);
    unmount();
    render(<OptionPicker value="v0" onChange={vi.fn()} options={options(SEARCHABLE_THRESHOLD + 1)} size={size} />);
    expectHeight(screen.getByRole("combobox"), height);
  });

  it.each(TIERS)("SearchableSelect / Combobox / TimePicker size=%s → %s", (size, height) => {
    const { unmount: a } = render(<SearchableSelect value="v0" onValueChange={vi.fn()} options={options(3)} size={size} />);
    expectHeight(screen.getByRole("button"), height);
    a();
    const { unmount: b } = render(<Combobox value="v0" onValueChange={vi.fn()} options={options(3)} size={size} />);
    expectHeight(screen.getByRole("combobox"), height);
    b();
    render(<TimePicker value="09:30" onChange={vi.fn()} ariaLabel="时间" size={size} />);
    expectHeight(screen.getByLabelText("时间"), height);
  });
});

it("同一行 size 相同就同高:输入框、下拉、按钮", () => {
  render(
    <div>
      <Input aria-label="搜索" size="sm" />
      <Select value="a">
        <SelectTrigger size="sm" aria-label="筛选">
          <SelectValue />
        </SelectTrigger>
      </Select>
      <Button size="sm">应用</Button>
    </div>,
  );
  for (const element of [screen.getByLabelText("搜索"), screen.getByRole("combobox"), screen.getByRole("button", { name: "应用" })])
    expectHeight(element, CONTROL_HEIGHT.sm);
});
