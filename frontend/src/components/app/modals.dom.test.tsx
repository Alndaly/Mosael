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
    expect(dialog.className).toContain("modal-surface");
    expect(dialog.className).not.toContain("backdrop-blur-xl");
    expect(header?.className).toContain("sticky");
    expect(header?.className).toContain("top-0");
    expect(header?.className).not.toMatch(/bg-(popover|panel|background)/);
    expect(header?.className).not.toContain("backdrop-blur-xl");
    expect(body?.className).toContain("overflow-y-auto");
    expect(body?.className).not.toMatch(/bg-(popover|panel|background)/);
    expect(body?.className).not.toContain("backdrop-blur-xl");
    // 留白在头尾上:正文一滚,它不会跟着滚走(见 ModalShell 的说明)。
    expect(header?.className).toContain("pb-5");
    expect(footer?.className).toContain("pt-5");
    expect(body?.className).not.toMatch(/\b(py|pt)-[2-9]/);
    expect(footer?.className).toContain("sticky");
    expect(footer?.className).toContain("bottom-0");
    expect(footer?.className).toContain("sm:items-center");
    expect(footer?.className).not.toMatch(/bg-(popover|panel|background)/);
    expect(footer?.className).not.toContain("backdrop-blur-xl");
  });

  it("uses one gap system and the shared surface radius", () => {
    render(
      <ModalShell
        open
        onOpenChange={vi.fn()}
        title="Edit labels"
        header={<div>Filters</div>}
        footer={<button type="button">Save</button>}
      >
        <div>Body</div>
      </ModalShell>,
    );

    const dialog = screen.getByRole("dialog");
    const header = dialog.querySelector('[data-slot="modal-header"]');
    const footer = dialog.querySelector('[data-slot="modal-footer"]');

    expect(dialog.className).toContain("rounded-2xl");
    expect(dialog.className).not.toContain("sm:rounded-2xl");
    expect(header?.className).toContain("gap-2.5");
    expect(header?.className).not.toMatch(/space-y-/);
    expect(footer?.className).toContain("gap-2");
    expect(footer?.className).not.toMatch(/space-x-/);
  });
});

import { ConfirmDialog } from "./modals";
import { fireEvent } from "@testing-library/react";

describe("ConfirmDialog 进行中", () => {
  it("确认后要等一阵的动作:确认键转圈,两个键都按不动,Esc 也关不掉", () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    render(<ConfirmDialog open pending title="删除?" onCancel={onCancel} onConfirm={onConfirm} />);

    const confirm = screen.getByRole("button", { name: /confirm/ });
    expect(confirm).toHaveAttribute("aria-busy", "true");
    expect(confirm).toBeDisabled();
    expect(screen.getByRole("button", { name: "cancel" })).toBeDisabled();

    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("没在进行时照常:确认就调用、不自己关(由调用方在完成后关)", () => {
    const onConfirm = vi.fn();
    render(<ConfirmDialog open pending={false} title="删除?" onCancel={vi.fn()} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });
});

describe("弹窗里用输入法打字时按 Esc", () => {
  //: 组词时的 Esc 是「放弃这次组词」。Radix 在捕获阶段听 Esc、不看组词 —— 此前按一下,
  //: 弹窗连同填了一半的字一起关掉。
  it("组词中的 Esc 不关弹窗;平常的 Esc 照常关", () => {
    const onOpenChange = vi.fn();
    render(
      <ModalShell open onOpenChange={onOpenChange} title="改名">
        <input aria-label="名字" />
      </ModalShell>,
    );
    const field = screen.getByLabelText("名字");
    field.focus();
    field.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", isComposing: true, keyCode: 229, bubbles: true, cancelable: true }));
    expect(onOpenChange).not.toHaveBeenCalled();
    field.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
