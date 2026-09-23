/** @vitest-environment jsdom */
/**
 * 标签筛选可以同时勾几个。此前只能选一个:点一个弹层就关,再点另一个就换掉前一个。
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MediaTagFilter, type TagMatch } from "./MediaTagFilter";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

function Harness({ change }: { change: (value: string[]) => void }) {
  const [value, setValue] = React.useState<string[]>([]);
  const [match, setMatch] = React.useState<TagMatch>("all");
  return (
    <>
      <MediaTagFilter
        tags={["Interview", "Landscape", "Demo"]}
        value={value}
        onChange={(next) => { change(next); setValue(next); }}
        match={match}
        onMatchChange={setMatch}
      />
      <output data-testid="match">{match}</output>
    </>
  );
}

it("可以连着勾几个标签,弹层不关;按钮上写第一个加 +N;一键清空", async () => {
  const change = vi.fn();
  render(<Harness change={change} />);
  fireEvent.click(screen.getByRole("button", { name: "filterByTag" }));
  const dialog = await screen.findByRole("dialog");

  fireEvent.click(within(dialog).getByRole("button", { name: "Interview" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Demo" }));
  expect(change).toHaveBeenLastCalledWith(["Interview", "Demo"]);
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "filterByTag" })).toHaveTextContent("Interview +1");

  // 再点一次是取消那一个。
  fireEvent.click(within(dialog).getByRole("button", { name: "Demo" }));
  expect(change).toHaveBeenLastCalledWith(["Interview"]);

  fireEvent.click(screen.getByRole("button", { name: "mediaClearTag" }));
  expect(change).toHaveBeenLastCalledWith([]);
});

it("勾了两个以上才出现「同时 / 任一」,默认是同时", async () => {
  render(<Harness change={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "filterByTag" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Interview" }));
  expect(within(dialog).queryByRole("radiogroup")).not.toBeInTheDocument();

  fireEvent.click(within(dialog).getByRole("button", { name: "Landscape" }));
  expect(within(dialog).getByRole("radio", { name: "mediaTagMatchAll" })).toHaveAttribute("aria-checked", "true");
  fireEvent.click(within(dialog).getByRole("radio", { name: "mediaTagMatchAny" }));
  expect(screen.getByTestId("match")).toHaveTextContent("any");
});
