/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CommandDialog, CommandInput, CommandList } from "./command";

describe("CommandDialog surface", () => {
  it("keeps the global search surface translucent", () => {
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
    expect(dialog.className).toContain("bg-popover/90");
    expect(dialog.className).toContain("backdrop-blur-xl");
    expect(dialog.firstElementChild?.className).toContain("bg-transparent");
  });
});
