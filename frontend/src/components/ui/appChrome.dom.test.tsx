/** @vitest-environment jsdom */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { APP_CHROME, installAppChromeGuards, keepOpenOnAppChrome } from "@/components/ui/appChrome";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { HintRegion } from "@/components/ui/tooltip";

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

describe("外壳里点一下就卸掉的东西(勾进表单的那一行、换成就地确认的按钮)也不算点了弹窗外面", () => {
  // 工作台「应用」面板里勾一项放进表单:Radix Dialog 等到 click 才判「点了外面」(deferPointerDownOutside),判的是按下的那个
  // 元素 —— 那时勾选框已经随那一行卸掉、脱离了文档,查不出它在外壳里,底下的工作流库就被关掉了(真 Chromium 里复现过;
  // jsdom 里 React 刷新的时机不一样,所以这里直接照 Radix 的顺序走一遍:按下 → 卸掉 → 判)。
  it("按下时在外壳里就算外壳里,哪怕判的时候它已经不在文档里了", () => {
    const chrome = document.createElement("div");
    chrome.setAttribute("data-app-chrome", "");
    const checkbox = document.createElement("button");
    chrome.appendChild(checkbox);
    document.body.appendChild(chrome);
    const elsewhere = document.createElement("button");
    document.body.appendChild(elsewhere);
    const outside = keepOpenOnAppChrome();
    fireEvent.pointerDown(checkbox);
    fireEvent.pointerDown(elsewhere);
    checkbox.remove();
    const judge = (target: Element) => {
      const originalEvent = new Event("pointerdown");
      Object.defineProperty(originalEvent, "target", { value: target });
      const event = new CustomEvent("dismissableLayer.pointerDownOutside", { cancelable: true, detail: { originalEvent } });
      outside(event);
      return event.defaultPrevented;
    };
    expect(judge(checkbox), "按下时在外壳里:不关").toBe(true);
    expect(judge(elsewhere), "别处:照样关").toBe(false);
    chrome.remove();
    elsewhere.remove();
  });
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

describe("外壳里打开的浮层也是外壳", () => {
  // 外壳 z 200;浮层统一 z 120(styles.css)。从外壳里开出来的不抬上去就压在外壳底下,点了像没反应(工作台模型库的小眼睛)。
  const floating = (label: string) => (
    <>
      <Popover defaultOpen>
        <PopoverTrigger>{label}</PopoverTrigger>
        <PopoverContent aria-label={`${label}-popover`}>设置</PopoverContent>
      </Popover>
      <Select defaultOpen defaultValue="a">
        <SelectTrigger aria-label={`${label}-select`}><SelectValue /></SelectTrigger>
        <SelectContent aria-label={`${label}-listbox`}><SelectItem value="a">一项</SelectItem></SelectContent>
      </Select>
    </>
  );

  it("区域里开的 Popover / Select 抬到外壳之上、挂 APP_CHROME;区域外的什么都不加", () => {
    const { unmount } = render(<HintRegion.Provider value={{ side: "left" }}>{floating("in")}</HintRegion.Provider>);
    for (const name of ["in-popover", "in-listbox"]) {
      const layer = screen.getByLabelText(name);
      expect(layer.hasAttribute("data-over-chrome"), name).toBe(true);
      expect(layer.hasAttribute("data-app-chrome"), name).toBe(true);
    }
    unmount();
    render(floating("out"));
    for (const name of ["out-popover", "out-listbox"]) {
      const layer = screen.getByLabelText(name);
      expect(layer.hasAttribute("data-over-chrome"), name).toBe(false);
      expect(layer.hasAttribute("data-app-chrome"), name).toBe(false);
    }
  });

  it("styles.css 把挂着 data-over-chrome 的那层抬到外壳之上", () => {
    const css = readFileSync(join(import.meta.dirname, "..", "..", "app", "styles.css"), "utf8");
    expect(css).toMatch(/\[data-radix-popper-content-wrapper\]:has\(> \[data-over-chrome\]\)\s*\{[^}]*z-index:\s*210/);
  });
});
