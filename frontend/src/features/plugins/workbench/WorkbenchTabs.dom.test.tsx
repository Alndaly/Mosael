/** @vitest-environment jsdom */

/**
 * 工作台右栏的页签:名字不折行;放不下时没选中的只剩图标(名字在悬停说明和读屏里),选中的始终带名字。
 * 维护者:英文界面里「Run & results」折成了两行。
 */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { readHint } from "@/test/hint";

import { WorkbenchTabs } from "./WorkbenchTabs";

const TABS = [
  { value: "models", label: "Models", icon: <svg /> },
  { value: "run", label: "Run & results", icon: <svg /> },
  { value: "assistant", label: "Assistant", icon: <svg /> },
] as const;

let rowWidth = 420;
const SHADOW_WIDTH = 433;
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(function (this: HTMLElement) {
    return this.getAttribute("role") === "tablist" ? rowWidth : 0;
  });
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(function (this: HTMLElement) {
    return this.getAttribute("aria-hidden") === "true" ? SHADOW_WIDTH : 0;
  });
});
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
    rowWidth = 600;
    show("models");
    const tab = screen.getByRole("tab", { name: "Run & results" });
    expect(tab.className.split(/\s+/)).toEqual(expect.arrayContaining(["whitespace-nowrap", "text-ui-sm", "aria-selected:text-primary", "aria-selected:border-primary"]));
  });

  it("放得下:每个页签都带名字", () => {
    rowWidth = 600;
    show("models");
    expect(screen.getByRole("tablist").dataset.workbenchTabs).toBe("full");
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Models", "Run & results", "Assistant"]);
  });

  it("放不下:没选中的只剩图标,名字给读屏和悬停说明;选中的照旧带名字;点图标照样切过去", async () => {
    rowWidth = 420;
    const onSelect = vi.fn();
    show("models", onSelect);
    expect(screen.getByRole("tablist").dataset.workbenchTabs).toBe("compact");
    expect(screen.getByRole("tab", { name: "Models", selected: true }).textContent).toBe("Models");
    const run = screen.getByRole("tab", { name: "Run & results" });
    expect(run.textContent).toBe("");
    expect(await readHint(run)).toContain("Run & results");
    fireEvent.click(run);
    expect(onSelect).toHaveBeenCalledWith("run");
  });
});
