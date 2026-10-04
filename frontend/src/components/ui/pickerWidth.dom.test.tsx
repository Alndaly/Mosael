/** @vitest-environment jsdom */
/**
 * 选值的下拉:宽度规则在共用组件里定,长值在行里单行截断,不把浮层撑开。
 *
 * 此前三种下拉三种宽度:Select 随内容一直长到整个窗口(checkpoint 文件名能把菜单撑满屏),
 * Combobox 死等于触发器宽(窄格子下面挂一条只剩几个字的列表),调用方只好各自补
 * `max-w-[min(360px,…)]` / `max-w-none`。规则收进 floating.ts 之后,调用方不再写宽度
 * (棘轮:design/menuWidths.test.ts)。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { MENU_WIDTH, SEARCHABLE_CONTENT_WIDTH, SELECT_CONTENT_WIDTH } from "./floating";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./select";
import { SearchableSelect } from "./searchable-select";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

const UI = import.meta.dirname;
const read = (path: string) => readFileSync(join(UI, path), "utf8");
const LONG = "juggernaut-xl-v9-rundiffusion-photo-2-lightning-4steps.safetensors";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

describe("宽度规则", () => {
  it("动作菜单有下限也有上限", () => {
    expect(MENU_WIDTH).toMatch(/\bmin-w-\S+/);
    expect(MENU_WIDTH).toMatch(/\bmax-w-\S+/);
  });

  it("Select 的上限是「触发器、24rem 里大的那个」,再不超出可用宽度", () => {
    expect(SELECT_CONTENT_WIDTH).toContain("--radix-select-trigger-width");
    expect(SELECT_CONTENT_WIDTH).toContain("24rem");
    expect(SELECT_CONTENT_WIDTH).toContain("--radix-select-content-available-width");
  });

  it("各个浮层都从 floating.ts 取宽度,自己不写", () => {
    expect(read("select.tsx")).toContain("SELECT_CONTENT_WIDTH");
    expect(read("context-menu.tsx").match(/MENU_WIDTH/g)?.length).toBeGreaterThanOrEqual(3);
    expect(read("searchable-select.tsx")).toContain("SEARCHABLE_CONTENT_WIDTH");
    expect(read("../app/combobox.tsx")).toContain("SEARCHABLE_CONTENT_WIDTH");
    expect(SEARCHABLE_CONTENT_WIDTH).toContain("--radix-popover-trigger-width");
  });
});

describe("Select 的选项", () => {
  function openSelect(item: React.ReactNode) {
    render(
      <Select value="a" onValueChange={vi.fn()}>
        <SelectTrigger aria-label="模型"><SelectValue /></SelectTrigger>
        <SelectContent>{item}</SelectContent>
      </Select>,
    );
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    return screen.getByRole("listbox");
  }

  it("静态选项折行,不截断", () => {
    const list = openSelect(<SelectItem value="a" description="跟着系统的外观走">跟随系统默认外观</SelectItem>);
    const option = within(list).getByRole("option");
    expect(within(option).getByText("跟随系统默认外观").className).not.toContain("truncate");
    expect(within(option).getByText("跟着系统的外观走").className).not.toContain("truncate");
  });

  it("动态的长值(truncate)单行截断,悬停看全文", () => {
    const list = openSelect(<SelectItem value="a" truncate>{LONG}</SelectItem>);
    const option = within(list).getByRole("option");
    expect(within(option).getByText(LONG).className).toContain("truncate");
  });
});

describe("带搜索的下拉", () => {
  it("名字单行截断,说明折行", () => {
    render(
      <SearchableSelect
        value=""
        onValueChange={vi.fn()}
        placeholder="选一个"
        options={[{ value: "a", label: LONG, description: "适合写实人像,四步出图" }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "选一个" }));
    const row = screen.getByRole("option");
    expect(within(row).getByText(LONG).className).toContain("truncate");
    expect(within(row).getByText("适合写实人像,四步出图").className).not.toContain("truncate");
  });
});
