/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Command, CommandDialog, CommandInput, CommandItem, CommandList } from "./command";
import { SearchableSelect } from "./searchable-select";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

describe("CommandDialog surface", () => {
  it("uses the shared frosted surface without a second opaque background", () => {
    vi.stubGlobal(
      "ResizeObserver",
      class ResizeObserver {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    render(
      <CommandDialog open>
        <CommandInput aria-label="Search" />
        <CommandList />
      </CommandDialog>,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("modal-surface");
    expect(dialog.className).not.toContain("bg-popover");
    expect(dialog.className).not.toContain("backdrop-blur-xl");
    expect(dialog.firstElementChild?.className).toContain("bg-transparent");
  });
});

describe("CommandList 搜索时滚回顶上", () => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView ??= () => undefined;

  it("cmdk 自己过滤的列表:改搜索词,滚动位置归零", () => {
    render(
      <Command>
        <CommandInput aria-label="Search" />
        <CommandList data-testid="list">
          {Array.from({ length: 50 }, (_, index) => (
            <CommandItem key={index} value={`item ${index}`}>{`item ${index}`}</CommandItem>
          ))}
        </CommandList>
      </Command>,
    );
    const list = screen.getByTestId("list");
    list.scrollTop = 400;
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "item 4" } });
    expect(list.scrollTop).toBe(0);
  });

  it("SearchableSelect(自己过滤)也走这一处:打开、滚下去、再输入,列表回到顶上", async () => {
    render(
      <SearchableSelect
        value=""
        onValueChange={() => undefined}
        searchPlaceholder="找"
        options={Array.from({ length: 60 }, (_, index) => ({ value: `v${index}`, label: `选项 ${index}` }))}
        trigger={<button type="button">open</button>}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "open" }));
    const input = await screen.findByPlaceholderText("找");
    const list = document.querySelector<HTMLElement>("[cmdk-list]")!;
    list.scrollTop = 300;
    fireEvent.change(input, { target: { value: "选项 5" } });
    expect(list.scrollTop).toBe(0);
  });
});
