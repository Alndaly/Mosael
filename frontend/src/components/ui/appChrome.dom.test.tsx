/** @vitest-environment jsdom */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { APP_CHROME, installAppChromeGuards } from "@/components/ui/appChrome";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

function Harness({ kind }: { kind: "dialog" | "sheet" }) {
  const [open, setOpen] = React.useState(true);
  return (
    <>
      {/* 内嵌网页视图亮着时盖在最上层的浏览器顶栏 / 页面列表 */}
      <div {...APP_CHROME}>
        <button type="button">返回 Mosael</button>
        <input aria-label="地址栏" />
      </div>
      <button type="button">别处</button>
      {kind === "dialog" ? (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent>
            <DialogTitle>工作流库</DialogTitle>
          </DialogContent>
        </Dialog>
      ) : (
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetContent>
            <SheetTitle>工作流库</SheetTitle>
          </SheetContent>
        </Sheet>
      )}
    </>
  );
}

describe("点在窗口外壳(浏览器顶栏、页面列表)上不算点了弹窗外面", () => {
  // 真机上:工作流库「在编辑器里打开」之后点「返回 Mosael」,底下开着的工作流库跟着关了 —— 顶栏在弹窗外面,
  // Radix 把这一下当成点了外面。
  for (const kind of ["dialog", "sheet"] as const) {
    it(`${kind}:点顶栏不关，点别处照样关`, async () => {
      render(<Harness kind={kind} />);
      // Radix 在打开后的下一拍才开始听「点了外面」;模态时外面的元素对辅助技术是隐藏的,按 hidden 取
      await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
      // 模态时 body 是 pointer-events:none —— 真实的点在原生层上照样发生,这里关掉 user-event 的那道检查
      const user = userEvent.setup({ pointerEventsCheck: 0 });
      await user.click(screen.getByRole("button", { name: "返回 Mosael", hidden: true }));
      expect(screen.queryByText("工作流库")).not.toBeNull();
      await user.click(screen.getByRole("button", { name: "别处", hidden: true }));
      expect(screen.queryByText("工作流库")).toBeNull();
    });
  }
});

describe("底下开着模态弹窗时,窗口外壳照样能用", () => {
  // 模态弹窗把焦点圈在自己里面(Radix FocusScope)、把 body 设成 pointer-events: none、按 Esc 就关。外壳盖在它上面,
  // 却在它外面:点地址栏,焦点马上被拽回弹窗;点按钮,这一下落不到按钮上;在地址栏按 Esc,底下的弹窗关了。
  let uninstall = () => undefined as void;
  beforeEach(() => {
    uninstall = installAppChromeGuards(document);
  });
  afterEach(() => uninstall());

  for (const kind of ["dialog", "sheet"] as const) {
    it(`${kind}:地址栏拿得到焦点,不被弹窗拽回去;在地址栏按 Esc 不关弹窗`, async () => {
      render(<Harness kind={kind} />);
      await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
      const address = screen.getByRole("textbox", { name: "地址栏", hidden: true });
      act(() => address.focus());
      await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
      expect(document.activeElement).toBe(address);
      fireEvent.keyDown(address, { key: "Escape" });
      expect(screen.queryByText("工作流库")).not.toBeNull();
    });
  }

  it("外壳自己接得住指针(模态弹窗把 body 设成了 pointer-events: none)", () => {
    const css = readFileSync(join(import.meta.dirname, "..", "..", "app", "styles.css"), "utf8");
    expect(css).toMatch(/\[data-app-chrome\]\s*\{[^}]*pointer-events:\s*auto/);
  });
});
