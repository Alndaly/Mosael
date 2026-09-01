/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));

import { ModalShell } from "./modals";

describe("ModalShell sticky layout", () => {
  it("keeps header and footer fixed while the padded body owns scrolling", () => {
    render(
      <ModalShell
        open
        onOpenChange={vi.fn()}
        title="Edit labels"
        footer={<button type="button">Save</button>}
      >
        <input aria-label="Label" />
      </ModalShell>,
    );

    const dialog = screen.getByRole("dialog");
    const header = dialog.querySelector('[data-slot="modal-header"]');
    const body = dialog.querySelector('[data-slot="modal-body"]');
    const footer = dialog.querySelector('[data-slot="modal-footer"]');

    expect(dialog.className).toContain("overflow-hidden");
    expect(dialog.className).toContain("bg-transparent");
    expect(dialog.className).toContain("backdrop-blur-xl");
    expect(header?.className).toContain("sticky");
    expect(header?.className).toContain("top-0");
    expect(header?.className).toContain("bg-popover/90");
    expect(header?.className).toContain("backdrop-blur-xl");
    expect(body?.className).toContain("overflow-y-auto");
    expect(body?.className).toContain("bg-popover/90");
    expect(body?.className).toContain("backdrop-blur-xl");
    expect(body?.className).toContain("py-5");
    expect(footer?.className).toContain("sticky");
    expect(footer?.className).toContain("bottom-0");
    expect(footer?.className).toContain("sm:items-center");
    expect(footer?.className).toContain("bg-popover/90");
    expect(footer?.className).toContain("backdrop-blur-xl");
  });
});
