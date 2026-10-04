/** @vitest-environment jsdom */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MENU_ITEM, MENU_WIDTH } from "./floating";
import { MenuContent, MenuItem, MenuItemBody, MenuSeparator } from "./menu";
import { Popover, PopoverTrigger } from "./popover";

const Icon = () => <svg data-icon="" />;

function openMenu(children: React.ReactNode) {
  render(
    <Popover>
      <PopoverTrigger>insert</PopoverTrigger>
      <MenuContent label="插入">{children}</MenuContent>
    </Popover>,
  );
  fireEvent.click(screen.getByText("insert"));
  return screen.getByRole("menu", { name: "插入" });
}

const classes = (element: Element) => new Set(element.className.split(/\s+/));

describe("菜单的宽度规则只在一处", () => {
  it("MenuContent 随内容定宽,夹在统一的最小、最大宽度之间", () => {
    const menu = openMenu(<MenuItem icon={<Icon />} label="引用块" />);
    for (const one of MENU_WIDTH.split(" ")) expect(classes(menu)).toContain(one);
    expect(MENU_WIDTH).toMatch(/\bmin-w-/);
    expect(MENU_WIDTH).toMatch(/\bmax-w-/);
  });
});

describe("菜单项", () => {
  it("静态文案不截断:放不下就折行", () => {
    const menu = openMenu(<MenuItem icon={<Icon />} label="插入图片" description="也可粘贴或拖入" />);
    const item = within(menu).getByRole("menuitem");
    for (const one of MENU_ITEM.split(" ")) expect(classes(item)).toContain(one);
    const label = within(item).getByText("插入图片");
    expect(label.className).not.toContain("truncate");
    expect(label.className).toContain("break-words");
  });

  it("补充说明是名字下面一行淡色的字,和悬停说明同一种层次", () => {
    const menu = openMenu(<MenuItem icon={<Icon />} label="插入图片" description="也可粘贴或拖入" />);
    const description = within(menu).getByText("也可粘贴或拖入");
    expect(description.className).toContain("text-muted-foreground");
    expect(description.className).not.toContain("truncate");
    expect(within(menu).getByRole("menuitem", { name: /插入图片/ })).toBeTruthy();
  });

  it("动态的长值单行截断(悬停看全文),不把菜单撑开", () => {
    const name = "an-extremely-long-workflow-name-that-would-push-the-menu-wide.json";
    const menu = openMenu(<MenuItem icon={<Icon />} label={name} truncate />);
    expect(within(menu).getByText(name).className).toContain("truncate");
  });

  it("快捷键用键帽画在行尾", () => {
    const menu = openMenu(<MenuItem icon={<Icon />} label="撤销" shortcut="⌘Z" />);
    expect(within(menu).getByRole("menuitem").querySelector("kbd")?.textContent).toBe("⌘Z");
  });

  it("勾选态画在行尾;没有图标的行用 inset 和有图标的行对齐", () => {
    render(
      <div>
        <MenuItemBody inset label="正文" checked />
      </div>,
    );
    const row = screen.getByText("正文").closest("div")!;
    expect(row.querySelectorAll("svg")).toHaveLength(1);
    expect(row.querySelector("[data-menu-icon]")).toBeTruthy();
  });

  it("方向键在可用条目之间循环", () => {
    const menu = openMenu(
      <>
        <MenuItem icon={<Icon />} label="甲" />
        <MenuItem icon={<Icon />} label="乙" disabled />
        <MenuSeparator />
        <MenuItem icon={<Icon />} label="丙" />
      </>,
    );
    const item = (name: string) => within(menu).getByRole("menuitem", { name });
    item("甲").focus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(item("丙"));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(item("甲"));
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(document.activeElement).toBe(item("丙"));
  });

  it("点一下触发 onClick", () => {
    const onClick = vi.fn();
    const menu = openMenu(<MenuItem icon={<Icon />} label="甲" onClick={onClick} />);
    fireEvent.click(within(menu).getByRole("menuitem"));
    expect(onClick).toHaveBeenCalled();
  });
});
