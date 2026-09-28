/** @vitest-environment jsdom */
/**
 * ⋯ 菜单的条目、分组和破坏性样式。
 *
 * 此前「删除」是一颗补了 `border-t` 的 ghost Button:自带透明描边、悬停底色只圆下面两个角,
 * 看着被单独框在一个盒子里。现在所有条目都是 MENU_ITEM,分组是独立的分隔元素。
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { MENU_ITEM, MENU_ITEM_DESTRUCTIVE } from "@/components/ui/floating";
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ActionContextMenuItems, ActionMenu, type MenuAction } from "./ActionMenu";

function open(actions: Parameters<typeof ActionMenu>[0]["actions"]) {
  render(<ActionMenu label="More" actions={actions} />);
  const trigger = screen.getByRole("button", { name: "More" });
  fireEvent.click(trigger);
  return { trigger, menu: screen.getByRole("menu", { name: "More" }) };
}

const classesOf = (el: Element) => new Set(el.className.split(/\s+/));

describe("ActionMenu", () => {
  it("每个条目都是同一种 MENU_ITEM,破坏性条目只多出红字,没有描边", () => {
    const { menu } = open([
      { label: "Rename", icon: <svg />, onSelect: vi.fn() },
      { label: "Delete", icon: <svg />, destructive: true, onSelect: vi.fn() },
    ]);
    const items = within(menu).getAllByRole("menuitem");
    for (const item of items) {
      for (const cls of MENU_ITEM.split(" ")) expect(classesOf(item)).toContain(cls);
      expect(item.className).not.toMatch(/(^|\s)border(-t)?(\s|$)|border-divider|rounded-t-none/);
    }
    const del = within(menu).getByRole("menuitem", { name: "Delete" });
    for (const cls of MENU_ITEM_DESTRUCTIVE.split(" ")) expect(classesOf(del)).toContain(cls);
    expect(within(menu).getByRole("menuitem", { name: "Rename" }).className).not.toContain("text-destructive");
  });

  it("破坏性条目自动单独成组:前面有别的条目时,中间有一条独立的分隔线", () => {
    const { menu } = open([
      { label: "Rename", icon: <svg />, onSelect: vi.fn() },
      { label: "Export", icon: <svg />, onSelect: vi.fn() },
      { label: "Delete", icon: <svg />, destructive: true, onSelect: vi.fn() },
    ]);
    const rows = [...menu.children].map((el) => el.getAttribute("role") === "separator" ? "|" : el.textContent);
    expect(rows).toEqual(["Rename", "Export", "|", "Delete"]);
  });

  it("只有一个破坏性条目时不画分隔线", () => {
    const { menu } = open([{ label: "Delete", icon: <svg />, destructive: true, onSelect: vi.fn() }]);
    expect(within(menu).queryByRole("separator")).toBeNull();
  });

  it("附注在名字后面单独一段、弱化显示,不拼进名字", () => {
    const { menu } = open([{ label: "History", icon: <svg />, hint: "v29", onSelect: vi.fn() }]);
    const item = within(menu).getByRole("menuitem");
    const hint = within(item).getByText("v29");
    expect(hint.className).toContain("text-muted-foreground");
    expect(within(item).getByText("History")).not.toBe(hint);
  });

  it("方向键在可用条目之间循环,跳过禁用的;Enter 触发后菜单关闭", () => {
    const exportFile = vi.fn();
    const { menu } = open([
      { label: "Rename", icon: <svg />, onSelect: vi.fn() },
      { label: "History", icon: <svg />, disabled: true, onSelect: vi.fn() },
      { label: "Export", icon: <svg />, onSelect: exportFile },
      { label: "Delete", icon: <svg />, destructive: true, onSelect: vi.fn() },
    ]);
    const item = (name: string) => within(menu).getByRole("menuitem", { name });
    item("Rename").focus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(item("Export"));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(item("Delete"));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(item("Rename"));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(document.activeElement).toBe(item("Delete"));
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect(document.activeElement).toBe(item("Rename"));
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(document.activeElement).toBe(item("Delete"));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    // 原生 button:Enter 就是 click。
    fireEvent.click(document.activeElement!);
    expect(exportFile).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("Esc 关闭菜单,焦点回到 ⋯ 按钮", async () => {
    const { trigger, menu } = open([{ label: "Rename", icon: <svg />, onSelect: vi.fn() }]);
    // 打开时焦点落在第一个条目上 —— 键盘用户不用再按一次 Tab 才进得了菜单。
    await waitFor(() => expect(document.activeElement).toBe(within(menu).getByRole("menuitem", { name: "Rename" })));
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    // FocusScope 在卸载后的下一拍才把焦点还回去。
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("右键菜单从同一份清单画:同样的条目、图标和分组,禁用的跟着禁用", () => {
    const onRename = vi.fn();
    const actions: MenuAction[] = [
      { label: "Rename", icon: <svg data-testid="icon-rename" />, onSelect: onRename },
      { label: "Export", icon: <svg data-testid="icon-export" />, disabled: true, onSelect: vi.fn() },
      { label: "Delete", icon: <svg data-testid="icon-delete" />, destructive: true, onSelect: vi.fn() },
    ];
    render(
      <ContextMenu>
        <ContextMenuTrigger>card</ContextMenuTrigger>
        <ContextMenuContent>
          <ActionContextMenuItems actions={actions} />
        </ContextMenuContent>
      </ContextMenu>,
    );
    fireEvent.contextMenu(screen.getByText("card"));
    const items = screen.getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(["Rename", "Export", "Delete"]);
    for (const [i, name] of ["rename", "export", "delete"].entries()) {
      expect(within(items[i]).getByTestId(`icon-${name}`)).toBeTruthy();
    }
    expect(items[1].getAttribute("data-disabled")).not.toBeNull();
    expect(classesOf(items[2]).has("text-destructive")).toBe(true);
    expect(screen.getAllByRole("separator")).toHaveLength(1);
    fireEvent.click(items[0]);
    expect(onRename).toHaveBeenCalled();
  });
});
