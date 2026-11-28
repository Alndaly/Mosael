/** @vitest-environment jsdom */

/**
 * 工作台右栏的页签:只放图标(名字在悬停说明和读屏里),数字徽标照旧;不再因为列宽出现「选中才带名字」的跳动。
 */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { readHint } from "@/test/hint";

import { WorkbenchTabs } from "./WorkbenchTabs";

const TABS = [
  { value: "models", label: "Models", icon: <svg /> },
  { value: "run", label: "Run & results", icon: <svg /> },
  { value: "assistant", label: "Assistant", icon: <svg /> },
] as const;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function show(active: (typeof TABS)[number]["value"], onSelect = vi.fn()) {
  return render(
    <TooltipProvider>
      <WorkbenchTabs label="右栏" idPrefix="wb" active={active} onSelect={onSelect} tabs={[...TABS]} />
    </TooltipProvider>,
  );
}

describe("工作台右栏的页签", () => {
  it("和别处的页签同一个样子:不折行、14px、选中强调色字 + 底线", () => {
    show("models");
    const tab = screen.getByRole("tab", { name: "Run & results" });
    expect(tab.className.split(/\s+/)).toEqual(expect.arrayContaining(["whitespace-nowrap", "text-ui-sm", "aria-selected:text-primary", "aria-selected:border-primary"]));
  });

  it("只放图标:名字给读屏和悬停说明,数字徽标照旧", async () => {
    const onSelect = vi.fn();
    show("models", onSelect);
    expect(screen.getByRole("tablist").dataset.workbenchTabs).toBe("icons");
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["", "", ""]);
    const run = screen.getByRole("tab", { name: "Run & results" });
    expect(await readHint(run)).toContain("Run & results");
    fireEvent.click(run);
    expect(onSelect).toHaveBeenCalledWith("run");
  });
});
