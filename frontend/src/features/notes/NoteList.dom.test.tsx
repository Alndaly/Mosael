/** @vitest-environment jsdom */
import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { emptyNote, type Note } from "@/api/domains/notes";
import { NoteList, rangeSelection } from "./NoteList";
vi.mock("@/app/preferences", () => ({
  usePreferences: () => ({ locale: "zh-CN" }),
  useI18n: () => (key: string) => key,
}));
afterEach(cleanup);
const notes: Note[] = ["a", "b", "c"].map((id) => ({
  ...emptyNote,
  id,
  title: id,
  workspace_id: "ws",
  revision: 1, save_seq: 1,
  created_at: "2026-09-07",
  updated_at: "2026-09-07",
}));
function mount(
  action = vi.fn(async (_action: string, rows: Note[]) =>
    rows.map((n) => n.id),
  ),
  writeBlocked: { reason: string; brief: string } | null = null,
) {
  const open = vi.fn();
  function Harness() {
    const [selecting, setSelecting] = React.useState(false);
    return (
      <NoteList
        notes={notes}
        currentId="a"
        selecting={selecting}
        onSelecting={setSelecting}
        onOpen={open}
        onAction={action}
        empty={null}
        writeBlocked={writeBlocked}
      />
    );
  }
  const result = render(<Harness />);
  const row = (id: string) =>
    result.container.querySelector(`[data-note-id="${id}"] .note-list-row`)!;
  return { row, open, action, ...result };
}
it("supports modifier selection, ranges, select-all and Escape without opening notes", () => {
  const { row, open } = mount();
  fireEvent.click(row("a"), { metaKey: true });
  fireEvent.click(row("c"), { shiftKey: true });
  expect(screen.getByText("已选 3 篇")).toBeTruthy();
  expect(open).not.toHaveBeenCalled();
  fireEvent.click(row("b"), { ctrlKey: true });
  expect(screen.getByText("已选 2 篇")).toBeTruthy();
  fireEvent.keyDown(screen.getByLabelText("选择笔记 a"), {
    key: "a",
    ctrlKey: true,
  });
  expect(screen.getByText("已选 3 篇")).toBeTruthy();
  fireEvent.keyDown(screen.getByLabelText("选择笔记 a"), { key: "Escape" });
  expect(screen.queryByLabelText("批量操作")).toBeNull();
  fireEvent.click(row("b"));
  expect(open).toHaveBeenCalledWith("b");
});
it("targets the selection on right-click and keeps unsuccessful batch items selected", async () => {
  const action = vi.fn(async () => ["a"]);
  const { row } = mount(action);
  fireEvent.click(row("a"), { metaKey: true });
  fireEvent.click(row("b"), { metaKey: true });
  fireEvent.contextMenu(row("a"), { clientX: 10, clientY: 10 });
  expect(screen.getAllByRole("menu")).toHaveLength(1);
  fireEvent.click(screen.getByRole("menuitem", { name: "移入回收站" }));
  await waitFor(() =>
    expect(action).toHaveBeenCalledWith(
      "trash",
      [notes[0], notes[1]],
      undefined,
    ),
  );
  await waitFor(() => expect(screen.getByText("已选 1 篇")).toBeTruthy());
});
it("uses only the clicked note when right-clicking outside the selection", async () => {
  const { row, action } = mount();
  fireEvent.click(row("a"), { metaKey: true });
  fireEvent.contextMenu(row("c"), { clientX: 10, clientY: 10 });
  fireEvent.click(screen.getByRole("menuitem", { name: "创建副本" }));
  await waitFor(() =>
    expect(action).toHaveBeenCalledWith("duplicate", [notes[2]], undefined),
  );
});
it("handles reversed ranges and an anchor no longer in the filtered list", () => {
  expect(rangeSelection(["a", "b", "c"], "c", "a")).toEqual(["a", "b", "c"]);
  expect(rangeSelection(["b", "c"], "a", "c")).toEqual(["c"]);
});
it("批量操作在跑时转圈的是点的那一颗,别的动作只是点不了;做完都恢复", async () => {
  let finish: (ids: string[]) => void = () => undefined;
  const action = vi.fn(() => new Promise<string[]>((resolve) => { finish = resolve; }));
  const { row } = mount(action);
  fireEvent.click(row("a"), { metaKey: true });
  const exportButton = () => screen.getByRole("button", { name: "导出 Markdown" });
  const trashButton = () => screen.getByRole("button", { name: "移入回收站" });
  fireEvent.click(exportButton());
  await waitFor(() => expect(exportButton().getAttribute("aria-busy")).toBe("true"));
  expect(exportButton().querySelector("svg.animate-mosael-spin")).not.toBeNull();
  expect((trashButton() as HTMLButtonElement).disabled, "别的动作这期间点不了").toBe(true);
  expect(trashButton().getAttribute("aria-busy"), "但不转圈:在跑的不是它").toBeNull();
  finish(["a"]);
  await waitFor(() => expect(exportButton().getAttribute("aria-busy")).toBeNull());
  expect((trashButton() as HTMLButtonElement).disabled).toBe(false);
});
//: 只读成员(体检 UM-20 / D62):改名、复制、收藏、移到回收站都是灰的并说为什么;导出照常(只是把字带走)。
it("只读成员:右键和批量里会改笔记的都是灰的、说为什么,导出照常", async () => {
  const { row, action } = mount(undefined, { reason: "只读,找管理员调", brief: "只读" });
  fireEvent.contextMenu(row("b"), { clientX: 10, clientY: 10 });
  for (const name of [/^重命名/, /^创建副本/, /^收藏/, /^移入回收站/]) {
    expect(screen.getByRole("menuitem", { name })).toHaveAttribute("aria-disabled", "true");
  }
  //: 菜单条目底下是短的那句(同一张菜单里每条都写);整句在按钮的悬停说明里
  expect(screen.getByRole("menuitem", { name: /^重命名/ }).textContent).toBe("重命名只读");
  expect(screen.getByRole("menuitem", { name: "导出 Markdown" })).not.toHaveAttribute("aria-disabled");
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });

  fireEvent.click(row("a"), { metaKey: true });
  expect((screen.getByRole("button", { name: "移入回收站" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "收藏" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "导出 Markdown" }) as HTMLButtonElement).disabled).toBe(false);
  expect(action).not.toHaveBeenCalled();
});
