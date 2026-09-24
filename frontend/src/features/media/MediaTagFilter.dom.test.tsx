/** @vitest-environment jsdom */
/**
 * 标签筛选可以同时勾几个。此前只能选一个:点一个弹层就关,再点另一个就换掉前一个。
 * 素材库用带字的触发器,剪辑页素材面板用 `compact`(图标 + 角标)配一排可去掉的标签 —— 弹层是同一个。
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ActiveTagChips, MediaTagFilter } from "./MediaTagFilter";
import type { TagMatch } from "./assetTags";

// 其余 key 原样返回;「去掉标签」要带上是哪个标签,给它留个占位。
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => (key === "mediaRemoveTag" ? "remove {tag}" : key) }));

const COUNTS = new Map([["Demo", 1], ["Interview", 4], ["Landscape", 2]]);

function Harness({ change, compact = false }: { change: (value: string[]) => void; compact?: boolean }) {
  const [value, setValue] = React.useState<string[]>([]);
  const [match, setMatch] = React.useState<TagMatch>("all");
  const onChange = (next: string[]) => { change(next); setValue(next); };
  return (
    <>
      <MediaTagFilter counts={COUNTS} value={value} onChange={onChange} match={match} onMatchChange={setMatch} compact={compact} />
      {compact && <ActiveTagChips value={value} onChange={onChange} match={match} />}
      <output data-testid="match">{match}</output>
    </>
  );
}

const tagOption = (dialog: HTMLElement, tag: string) => within(dialog).getByRole("button", { name: new RegExp(`^${tag}`) });

it("可以连着勾几个标签,弹层不关;按钮上写第一个加 +N;一键清空", async () => {
  const change = vi.fn();
  render(<Harness change={change} />);
  fireEvent.click(screen.getByRole("button", { name: "filterByTag" }));
  const dialog = await screen.findByRole("dialog");

  fireEvent.click(tagOption(dialog, "Interview"));
  fireEvent.click(tagOption(dialog, "Demo"));
  expect(change).toHaveBeenLastCalledWith(["Interview", "Demo"]);
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "filterByTag" })).toHaveTextContent("Interview +1");

  // 再点一次是取消那一个。
  fireEvent.click(tagOption(dialog, "Demo"));
  expect(change).toHaveBeenLastCalledWith(["Interview"]);

  fireEvent.click(screen.getByRole("button", { name: "mediaClearTag" }));
  expect(change).toHaveBeenLastCalledWith([]);
});

it("每个标签后面标着挂了几条素材,勾没勾看 aria-pressed;可以搜", async () => {
  render(<Harness change={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "filterByTag" }));
  const dialog = await screen.findByRole("dialog");
  expect(tagOption(dialog, "Interview")).toHaveTextContent("Interview4");
  expect(tagOption(dialog, "Landscape")).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(tagOption(dialog, "Landscape"));
  expect(tagOption(dialog, "Landscape")).toHaveAttribute("aria-pressed", "true");

  fireEvent.change(within(dialog).getByRole("textbox", { name: "mediaSearchTags" }), { target: { value: "inter" } });
  expect(within(dialog.querySelector("[role=group]") as HTMLElement).getAllByRole("button").map((one) => one.textContent)).toEqual(["Interview4"]);
});

it("勾了两个以上才出现「同时 / 任一」,默认是同时", async () => {
  render(<Harness change={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "filterByTag" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(tagOption(dialog, "Interview"));
  expect(within(dialog).queryByRole("radiogroup")).not.toBeInTheDocument();

  fireEvent.click(tagOption(dialog, "Landscape"));
  expect(within(dialog).getByRole("radio", { name: "mediaTagMatchAll" })).toHaveAttribute("aria-checked", "true");
  fireEvent.click(within(dialog).getByRole("radio", { name: "mediaTagMatchAny" }));
  expect(screen.getByTestId("match")).toHaveTextContent("any");
});

it("compact:图标角上标勾了几个;下面一排标签点一个去掉一个,「清除」全去掉", async () => {
  const change = vi.fn();
  render(<Harness change={change} compact />);
  const trigger = screen.getByRole("button", { name: "filterByTag" });
  expect(trigger.querySelector("[data-tag-filter-count]")).toBeNull();
  expect(screen.queryByRole("group", { name: "mediaActiveTags" })).not.toBeInTheDocument();

  fireEvent.click(trigger);
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(tagOption(dialog, "Interview"));
  fireEvent.click(tagOption(dialog, "Landscape"));
  expect(trigger.querySelector("[data-tag-filter-count]")).toHaveTextContent("2");

  const chips = screen.getByRole("group", { name: "mediaActiveTags" });
  // 两个以上时写明怎么算。
  expect(chips).toHaveTextContent("mediaTagMatchAll");
  fireEvent.click(within(chips).getByRole("button", { name: "remove Interview" }));
  expect(change).toHaveBeenLastCalledWith(["Landscape"]);
  expect(trigger.querySelector("[data-tag-filter-count]")).toHaveTextContent("1");

  fireEvent.click(within(screen.getByRole("group", { name: "mediaActiveTags" })).getByRole("button", { name: "mediaClearTag" }));
  expect(change).toHaveBeenLastCalledWith([]);
  expect(trigger.querySelector("[data-tag-filter-count]")).toBeNull();
  expect(screen.queryByRole("group", { name: "mediaActiveTags" })).not.toBeInTheDocument();
});
