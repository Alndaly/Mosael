/** @vitest-environment jsdom */
import * as React from "react";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { SearchableSelect } from "./searchable-select";
import { OptionPicker, SEARCHABLE_THRESHOLD } from "./option-picker";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./select";
import { SEARCHABLE_CONTENT_WIDTH, SEARCHABLE_CONTENT_WIDTH_WITH_DESCRIPTIONS, SELECT_CONTENT_WIDTH } from "./floating";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

const own = (rule: string) => rule.split(" ");

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

  it("默认:宽度 = max(触发器宽, 下限),上限 = 可用宽度(规则在 floating.ts)", () => {
    render(<SearchableSelect value="ckpt0" onValueChange={vi.fn()} options={options(30)} />);
    const classNames = classes(openContent());
    for (const one of own(SEARCHABLE_CONTENT_WIDTH)) expect(classNames).toContain(one);
    expect(SEARCHABLE_CONTENT_WIDTH).toContain("var(--radix-popover-trigger-width)");
    expect(SEARCHABLE_CONTENT_WIDTH).toContain("max-w-(--radix-popover-content-available-width)");
    // PopoverContent 的默认 w-72 必须被盖掉,否则浮层就是 288px,不管触发器多宽。
    expect(classNames).not.toContain("w-72");
  });

  it("带描述的清单同一条规则,只是下限更宽 —— 不再是和触发器无关的固定宽", () => {
    render(
      <SearchableSelect
        value=""
        onValueChange={vi.fn()}
        options={[{ value: "a", label: "发布", description: "把成片发到抖音、小红书" }]}
        trigger={<button type="button" role="combobox">+</button>}
      />,
    );
    const classNames = classes(openContent());
    for (const one of own(SEARCHABLE_CONTENT_WIDTH_WITH_DESCRIPTIONS)) expect(classNames).toContain(one);
    expect(classNames.some((one) => /^w-\[\d+px\]$/.test(one)), "又出现了固定宽度").toBe(false);
  });

  it("OptionPicker 的长清单走同一条规则,不再自己另抬一个下限", () => {
    render(<OptionPicker value="ckpt0" onChange={vi.fn()} options={options(SEARCHABLE_THRESHOLD + 1)} />);
    const classNames = classes(openContent());
    for (const one of own(SEARCHABLE_CONTENT_WIDTH)) expect(classNames).toContain(one);
    expect(classNames.filter((one) => one.startsWith("min-w-"))).toEqual([]);
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

  it("普通 Select 的宽度规则同样是有效的变量写法", () => {
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
    const classNames = classes(content!.closest<HTMLElement>("[data-state]") ?? content!);
    for (const one of own(SELECT_CONTENT_WIDTH)) expect(classNames).toContain(one);
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

/**
 * 几项同名(好几个「未命名场景」)时,cmdk 按 value 认「哪一行」—— 此前 value 是显示的文字,同名的几行
 * 被当成一行:一起高亮,点哪个都可能选到另一个。value 必须是这一项自己的值,文字只用来搜。
 */
describe("同名的几项各是各的", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Element.prototype.scrollIntoView ??= () => {};
  });

  it("每一行按自己的值标识,点第二个选中的就是第二个;按名字照样搜得到", () => {
    const onChange = vi.fn();
    const twins = [
      { value: "scene-a", label: "未命名场景" },
      { value: "scene-b", label: "未命名场景" },
      { value: "scene-c", label: "客厅" },
    ];
    render(<SearchableSelect value="scene-a" onValueChange={onChange} options={twins} />);
    const content = openContent();
    const rows = [...content.querySelectorAll<HTMLElement>("[cmdk-item]")];
    expect(rows.map((row) => row.getAttribute("data-value"))).toEqual(["scene-a", "scene-b", "scene-c"]);
    // 同一时刻只有一行是高亮的。
    expect(rows.filter((row) => row.getAttribute("data-selected") === "true")).toHaveLength(1);
    fireEvent.click(rows[1]);
    expect(onChange).toHaveBeenCalledWith("scene-b");
  });
});

/**
 * 用户看到的:画板「参数」弹层里,「项目」的下拉没排在标签右边撑满,而是掉到下一行、只有标签列
 * 那 112px 宽。根因:可搜索下拉(项多于 SEARCHABLE_THRESHOLD)在触发器旁边插了一个
 * `hidden` 的探针 span,表单行的 `[&>span]:flex` 把它重新显示出来,空 span 占掉了右格。
 * 下拉只能交出**一个**元素给所在的版面 —— 触发器本身。
 */
describe("可搜索下拉在版面里只占一格", () => {
  it("除了触发器不渲染任何兄弟元素", () => {
    const { container } = render(
      <div data-row="">
        <span>项目</span>
        <OptionPicker value="" onChange={() => {}} options={options(SEARCHABLE_THRESHOLD + 1)} placeholder="请选择" />
      </div>,
    );
    const row = container.querySelector<HTMLElement>("[data-row]")!;
    expect([...row.children].map((child) => child.tagName)).toEqual(["SPAN", "BUTTON"]);
    expect(row.children[1].getAttribute("role")).toBe("combobox");
  });
});
