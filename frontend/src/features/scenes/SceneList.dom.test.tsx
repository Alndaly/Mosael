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
import { messages, type MessageKey } from "@/app/messages";
import { SceneList } from "./SceneList";
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: MessageKey) => messages["zh-CN"][key] }));
afterEach(cleanup);
const scenes = ["a", "b", "c"].map((id) => ({
  id,
  name: id,
  revision: 1,
  updated_at: "2026-09-07",
  object_count: 1,
  shot_count: 1,
}));
function mount(
  onDelete = vi.fn(async (rows: typeof scenes) => rows.map((s) => s.id)),
) {
  const onOpen = vi.fn(),
    onRename = vi.fn(async () => true);
  function Harness() {
    const [selecting, onSelecting] = React.useState(false);
    return (
      <SceneList
        {...{ scenes, selecting, onSelecting, onOpen, onDelete, onRename }}
      />
    );
  }
  render(<Harness />);
  return {
    onOpen,
    onDelete,
    onRename,
    row: (id: string) => screen.getByRole("button", { name: `打开场景 ${id}` }),
  };
}
it("selects ranges and all via keyboard, then Escape restores click-to-open", () => {
  const { row, onOpen } = mount();
  fireEvent.click(row("a"), { metaKey: true });
  fireEvent.click(row("c"), { shiftKey: true });
  expect(screen.getByText("已选 3 个场景")).toBeTruthy();
  fireEvent.click(row("b"), { ctrlKey: true });
  expect(screen.getByText("已选 2 个场景")).toBeTruthy();
  fireEvent.keyDown(row("a"), { key: "a", ctrlKey: true });
  expect(screen.getByText("已选 3 个场景")).toBeTruthy();
  expect(onOpen).not.toHaveBeenCalled();
  fireEvent.keyDown(row("a"), { key: "Escape" });
  fireEvent.click(row("b"));
  expect(onOpen).toHaveBeenCalledWith("b");
});
it("right-clicks the selected group and preserves failed deletions for retry", async () => {
  const remove = vi.fn(async () => ["a"]);
  const { row } = mount(remove);
  fireEvent.click(row("a"), { metaKey: true });
  fireEvent.click(row("b"), { metaKey: true });
  fireEvent.contextMenu(row("a"), { clientX: 10, clientY: 10 });
  fireEvent.click(screen.getByRole("menuitem", { name: "删除 2 个场景" }));
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: messages["zh-CN"].confirm }));
  await waitFor(() => expect(remove).toHaveBeenCalledWith(scenes.slice(0, 2)));
  await waitFor(() => expect(screen.getByText("已选 1 个场景")).toBeTruthy());
  // 删失败的那个仍然选着,好让人重试。选中态画在缩略图上(勾选圈 + 主色圈),按钮报「按下」。
  expect(row("b")).toHaveAttribute("aria-pressed", "true");
});
it("right-click outside the selection only targets that scene and rename submits trimmed text", async () => {
  const { row, onRename } = mount();
  fireEvent.click(row("a"), { metaKey: true });
  fireEvent.click(row("b"), { metaKey: true });
  fireEvent.contextMenu(row("c"), { clientX: 10, clientY: 10 });
  fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }));
  fireEvent.change(screen.getByRole("textbox", { name: "场景名称" }), {
    target: { value: "  New  " },
  });
  fireEvent.submit(document.getElementById("scene-rename")!);
  await waitFor(() => expect(onRename).toHaveBeenCalledWith(scenes[2], "New"));
});
