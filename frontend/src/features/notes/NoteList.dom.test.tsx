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
  revision: 1,
  created_at: "2026-09-07",
  updated_at: "2026-09-07",
}));
function mount(
  action = vi.fn(async (_action: string, rows: Note[]) =>
    rows.map((n) => n.id),
  ),
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
