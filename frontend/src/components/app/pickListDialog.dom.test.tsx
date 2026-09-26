/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PickListDialog } from "./PickListDialog";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

const items = [
  { id: "a", name: "开场" },
  { id: "b", name: "结尾" },
];

function mount(onPick = vi.fn()) {
  render(
    <PickListDialog
      open
      onOpenChange={() => {}}
      title="选择笔记"
      searchLabel="搜索"
      query=""
      onQueryChange={() => {}}
      items={items}
      itemKey={(item) => item.id}
      row={(item) => ({ lead: null, title: item.name, subtitle: "一行说明", meta: "v2" })}
      onPick={onPick}
      empty={{ icon: null, text: "没有" }}
    />,
  );
  return onPick;
}

describe("挑一项的弹窗", () => {
  it("一行一个:名字、一行说明、附注;第一行默认高亮", () => {
    mount();
    const rows = screen.getAllByRole("option");
    expect(rows.map((row) => row.textContent)).toEqual(["开场一行说明v2", "结尾一行说明v2"]);
    expect(rows[0].getAttribute("aria-selected")).toBe("true");
  });

  it("键盘挑完:在搜索框里 ↓ 换到下一行,回车挑它", () => {
    const onPick = mount();
    const search = screen.getByRole("textbox", { name: "搜索" });
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[1].getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(search, { key: "Enter" });
    expect(onPick).toHaveBeenCalledWith(items[1]);
  });
});
