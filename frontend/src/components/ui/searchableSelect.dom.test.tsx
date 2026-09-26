/** @vitest-environment jsdom */
import * as React from "react";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { SearchableSelect } from "./searchable-select";
import { OptionPicker, SEARCHABLE_THRESHOLD } from "./option-picker";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./select";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

const TRIGGER_WIDTH = "w-(--radix-popover-trigger-width)";
const AVAILABLE_WIDTH = "max-w-(--radix-popover-content-available-width)";

const options = (count: number) =>
  Array.from({ length: count }, (_, index) => ({ value: `ckpt${index}`, label: `JANKUTrainedChenkinNoobai_v${index}.safetensors` }));

function openContent(): HTMLElement {
  // 默认触发器是普通按钮,自定义 / OptionPicker 的触发器顶着 role=combobox。
  fireEvent.click(screen.queryByRole("combobox") ?? screen.getByRole("button"));
  const content = document.querySelector<HTMLElement>("[data-radix-popper-content-wrapper] > [role='dialog']");
  expect(content, "浮层没打开").toBeTruthy();
  return content!;
}

function classes(element: HTMLElement): string[] {
  return element.className.split(/\s+/);
}

/**
 * 用户看到的:整宽的「模型」字段下面挂着一条四分之一宽的列表,长文件名全被截成省略号;
 * 旁边普通下拉的列表却和字段一样宽。根因是 `w-[--radix-popover-trigger-width]` ——
 * Tailwind v4 把它生成成 `width: --radix-popover-trigger-width`,浏览器丢掉无效声明,
 * 而 tailwind-merge 早把默认的 `w-72` 当冲突删了,浮层只剩 auto 宽。
 * jsdom 不排版,所以这里钉的是**类名**:宽度写的是哪条规则。
 */
describe("可搜索下拉的浮层宽度:对齐触发器,带下限,不出窗口", () => {
  beforeAll(() => {
    // cmdk 在挂载时就要 ResizeObserver;jsdom 没有。
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Element.prototype.scrollIntoView ??= () => {};
  });

  it("默认:宽度 = 触发器宽,下限 200px,上限 = 可用宽度", () => {
    render(<SearchableSelect value="ckpt0" onValueChange={vi.fn()} options={options(30)} />);
    const own = classes(openContent());
    expect(own).toContain(TRIGGER_WIDTH);
    expect(own).toContain(AVAILABLE_WIDTH);
    expect(own).toContain("min-w-[min(200px,var(--radix-popover-content-available-width))]");
    // PopoverContent 的默认 w-72 必须被盖掉,否则浮层就是 288px,不管触发器多宽。
    expect(own).not.toContain("w-72");
  });

  it("带描述的清单同一条规则,只是下限更宽 —— 不再是和触发器无关的固定 360px", () => {
    render(
      <SearchableSelect
        value=""
        onValueChange={vi.fn()}
        options={[{ value: "a", label: "发布", description: "把成片发到抖音、小红书" }]}
        trigger={<button type="button" role="combobox">+</button>}
      />,
    );
    const own = classes(openContent());
    expect(own).toContain(TRIGGER_WIDTH);
    expect(own).toContain("min-w-[min(360px,var(--radix-popover-content-available-width))]");
    expect(own.some((one) => /^w-\[\d+px\]$/.test(one)), "又出现了固定宽度").toBe(false);
  });

  it("OptionPicker 只抬高下限,宽度照样跟触发器 —— 整格触发器下面不再挂一条 320px 的窄列表", () => {
    render(<OptionPicker value="ckpt0" onChange={vi.fn()} options={options(SEARCHABLE_THRESHOLD + 1)} />);
    const own = classes(openContent());
    expect(own).toContain(TRIGGER_WIDTH);
    expect(own).toContain("min-w-[min(320px,var(--radix-popover-content-available-width))]");
    // 调用方的下限替换默认下限,而不是两条 min-w 叠在一起看谁在样式表里排后面。
    expect(own).not.toContain("min-w-[min(200px,var(--radix-popover-content-available-width))]");
  });

  it("调用方给的上限仍然生效", () => {
    render(
      <SearchableSelect value="" onValueChange={vi.fn()} options={options(30)} contentClassName="max-w-[min(520px,calc(100vw-32px))]" />,
    );
    const own = classes(openContent());
    expect(own).toContain("max-w-[min(520px,calc(100vw-32px))]");
    expect(own).not.toContain(AVAILABLE_WIDTH);
    expect(own).toContain(TRIGGER_WIDTH);
  });

  it("键盘照旧:打开后方向键 + 回车选中,Esc 关掉", () => {
    const onValueChange = vi.fn();
    render(<SearchableSelect value="" onValueChange={onValueChange} options={options(5)} />);
    openContent();
    const input = document.querySelector("[cmdk-input]") as HTMLInputElement;
    expect(document.activeElement, "打开后焦点该在搜索框").toBe(input);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onValueChange).toHaveBeenCalledWith("ckpt1");
    expect(document.querySelector("[cmdk-input]"), "选中后浮层该收起").toBeNull();
  });

  it("普通 Select 的上限同样是有效的变量写法", () => {
    render(
      <Select value="a" defaultOpen>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="a">a</SelectItem>
        </SelectContent>
      </Select>,
    );
    const content = document.querySelector<HTMLElement>("[data-radix-select-content], [role='listbox']");
    expect(content).toBeTruthy();
    const own = classes(content!.closest<HTMLElement>("[data-state]") ?? content!);
    expect(own).toContain("min-w-[var(--radix-select-trigger-width)]");
    expect(own).toContain("max-w-(--radix-select-content-available-width)");
  });
});

/**
 * 同一个坑的根:Tailwind v3 的 `x-[--var]` 在 v4 里不再自动包 `var()`,生成的是无效声明 ——
 * 不报错、不告警,样式悄悄没了。v4 的写法是 `x-(--var)` 或 `x-[var(--var)]`。
 */
describe("Tailwind v4 下不再有 `x-[--var]` 这种写法", () => {
  it("src 里一处都没有", () => {
    const root = join(__dirname, "../..");
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (/\.(tsx?|css)$/.test(name) && !/\.test\.tsx?$/.test(name)) {
          readFileSync(path, "utf8")
            .split("\n")
            .forEach((line, index) => {
              // 注释里讲这个坑时会原样写出坏写法,不算。
              if (/^\s*(\*|\/\/|\/\*|\{\/\*)/.test(line)) return;
              if (/[a-z0-9]-\[--[a-z]/.test(line)) offenders.push(`${relative(root, path)}:${index + 1}`);
            });
        }
      }
    };
    walk(root);
    expect(offenders).toEqual([]);
  });
});
