/** @vitest-environment jsdom */
import React from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { APP_CHROME } from "@/components/ui/appChrome";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

function Harness({ kind }: { kind: "dialog" | "sheet" }) {
  const [open, setOpen] = React.useState(true);
  return (
    <>
      {/* 内嵌网页视图亮着时盖在最上层的浏览器顶栏 / 页面列表 */}
      <div {...APP_CHROME}>
        <button type="button">返回 Mosael</button>
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
