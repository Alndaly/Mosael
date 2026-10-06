/** @vitest-environment jsdom */

/**
 * 「高级」这类折叠开关(Disclosure):一行字,不是按钮。钉的是:
 *
 * - 点它开合:`aria-expanded` 跟着变、`aria-controls` 指着内容,内容收着时不挂载;
 * - 几项(count)、一句提示(hint)、占满一整行(wide)都摆得出来;
 * - 任何状态下没有底色、边框、按钮的内边距和高度,悬停只变字的颜色,焦点环只给键盘聚焦。
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Disclosure } from "./disclosure";

function Harness({ wide = false }: { wide?: boolean }) {
  const [open, setOpen] = React.useState(false);
  return (
    <Disclosure label="高级" count={3} hint="一般不用改" wide={wide} open={open} onOpenChange={setOpen}>
      <p>收着的设置</p>
    </Disclosure>
  );
}

describe("Disclosure", () => {
  it("点它开合:aria-expanded 跟着变,aria-controls 指着内容;收着时内容不挂载", () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: /高级/ });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("收着的设置")).toBeNull();
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    const content = screen.getByText("收着的设置");
    const controls = trigger.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    expect(content.closest(`[id="${controls}"]`)).not.toBeNull();
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("收着的设置")).toBeNull();
  });

  it("几项和提示都摆得出来;wide 时占满一整行", () => {
    const { unmount } = render(<Harness />);
    const trigger = screen.getByRole("button", { name: /高级/ });
    expect(trigger.textContent).toContain("3");
    expect(trigger.textContent).toContain("一般不用改");
    expect(trigger.className).toContain("w-fit");
    unmount();
    render(<Harness wide />);
    expect(screen.getByRole("button", { name: /高级/ }).className).toMatch(/(^|\s)w-full(\s|$)/);
  });

  it("不是按钮的长相:没有底色、边框、内边距和固定高度;悬停只变字色,焦点环只给键盘聚焦", () => {
    render(<Harness />);
    const classes = screen.getByRole("button", { name: /高级/ }).className.split(/\s+/);
    expect(classes).toContain("bg-transparent");
    expect(classes).toContain("border-0");
    expect(classes).toContain("p-0");
    expect(classes.filter((one) => /^(hover:|data-\[state=open\]:)?bg-(?!transparent)/.test(one))).toEqual([]);
    expect(classes.filter((one) => /^(px|py|h)-/.test(one) || /^rounded-(md|lg|full)$/.test(one))).toEqual([]);
    expect(classes.filter((one) => one.startsWith("hover:"))).toEqual(["hover:text-foreground"]);
    expect(classes.filter((one) => one.startsWith("focus:"))).toEqual([]);
    expect(classes).toContain("focus-visible:ring-2");
  });
});
