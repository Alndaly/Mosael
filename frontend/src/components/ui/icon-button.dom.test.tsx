/** @vitest-environment jsdom */
import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { readHint } from "@/test/hint";

import { IconButton } from "./icon-button";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

const Icon = () => <svg data-icon="" />;

describe("只有图标的按钮", () => {
  it("名字只写一次:既是读屏念的 aria-label,也是悬停说明的第一行", async () => {
    render(<IconButton label="删除"><Icon /></IconButton>);
    const button = screen.getByRole("button", { name: "删除" });
    expect(button.hasAttribute("title")).toBe(false);
    expect(await readHint(button)).toBe("删除");
  });

  it("补充说明、快捷键一起进说明", async () => {
    render(<IconButton label="撤销" hint="撤回上一步编辑" shortcut="⌘Z"><Icon /></IconButton>);
    expect(await readHint(screen.getByRole("button", { name: "撤销" }))).toBe("撤销⌘Z撤回上一步编辑");
  });

  it("点不了时说明里写原因;能点时不写", async () => {
    const { rerender } = render(
      <IconButton label="撤销" disabled disabledReason="没有可撤销的操作"><Icon /></IconButton>,
    );
    expect(await readHint(screen.getByRole("button", { name: "撤销" }))).toBe("撤销没有可撤销的操作");
    rerender(<IconButton label="撤销" disabledReason="没有可撤销的操作"><Icon /></IconButton>);
    const button = screen.getByRole("button", { name: "撤销" });
    expect(button.parentElement?.hasAttribute("data-hint-disabled")).toBe(false);
  });

  it("默认是 ghost 的 icon-sm;unstyled 时不带 Button 的外观,样式全由调用方给", () => {
    render(
      <>
        <IconButton label="甲"><Icon /></IconButton>
        <IconButton label="乙" unstyled className="note-tool"><Icon /></IconButton>
      </>,
    );
    expect(screen.getByRole("button", { name: "甲" }).className).toContain("hover:bg-accent");
    expect(screen.getByRole("button", { name: "乙" }).className).toBe("note-tool");
  });

  it("unstyled 也认 loading:图标换成同样大小的转圈、aria-busy、点不了;没有图标的内容不补转圈", () => {
    const Sized = ({ size }: { size?: number }) => <svg data-icon="" width={size} />;
    const { rerender } = render(<IconButton label="上传" unstyled><Sized size={12} /></IconButton>);
    const button = screen.getByRole("button", { name: "上传" });
    expect(button.getAttribute("aria-busy")).toBeNull();
    rerender(<IconButton label="上传" unstyled loading><Sized size={12} /></IconButton>);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(button.querySelector("[data-icon]"), "图标让位给转圈").toBeNull();
    expect(button.querySelector("svg.animate-mosael-spin")?.getAttribute("width"), "转圈和原来的图标一样大").toBe("12");

    rerender(<IconButton label="上传" unstyled loading><img alt="" /><span>A</span></IconButton>);
    expect(button.querySelector("svg"), "头像这种自绘的内容:转圈由调用方画").toBeNull();
    expect(button.querySelector("img")).not.toBeNull();
  });

  it("能当 Popover 的触发器:点开浮层、浮层的状态挂在按钮上", () => {
    const onClick = vi.fn();
    render(
      <Popover>
        <PopoverTrigger asChild>
          <IconButton label="更多" onClick={onClick}><Icon /></IconButton>
        </PopoverTrigger>
        <PopoverContent>菜单</PopoverContent>
      </Popover>,
    );
    const button = screen.getByRole("button", { name: "更多" });
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalled();
    expect(screen.getByText("菜单")).toBeTruthy();
    expect(button.getAttribute("data-state")).toBe("open");
  });

  it("转发 ref", () => {
    const ref = React.createRef<HTMLButtonElement>();
    render(<IconButton ref={ref} label="甲"><Icon /></IconButton>);
    expect(ref.current).toBe(screen.getByRole("button", { name: "甲" }));
  });
});
