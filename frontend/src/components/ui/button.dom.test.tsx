/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/button";

/**
 * `loading` 是全项目"点了没反应"的统一解法(判据见 buttonPending.test.ts)。三条各对一个坏结果:
 * 还能点 → 连点两下发两次请求;宽度变了 → 一行按钮在请求期间跳一下;
 * asChild 时塞东西 → 把 <label>/<a> 的结构撑坏(附件上传那类按钮就是 asChild)。
 */
describe("Button 的 loading", () => {
  it("禁用点击", async () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        保存
      </Button>,
    );
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button.getAttribute("aria-busy")).toBe("true");
    button.click();
    expect(onClick).not.toHaveBeenCalled();
  });

  it("**替换**已有图标而不是再加一个 —— 否则按钮变宽,整行会跳", () => {
    const Icon = () => <svg data-testid="icon" />;
    const { rerender, container } = render(
      <Button>
        <Icon /> 扫描
      </Button>,
    );
    expect(container.querySelectorAll("svg")).toHaveLength(1);
    rerender(
      <Button loading>
        <Icon /> 扫描
      </Button>,
    );
    expect(container.querySelectorAll("svg")).toHaveLength(1);
    expect(screen.queryByTestId("icon")).toBeNull();
    expect(screen.getByText("扫描")).toBeTruthy();
  });

  it("没有图标就在文字前补一个", () => {
    const { container } = render(<Button loading>保存</Button>);
    expect(container.querySelectorAll("svg")).toHaveLength(1);
    expect(screen.getByText("保存")).toBeTruthy();
  });

  it("asChild 时不动 children —— 那时 Button 只是把样式借给别人", () => {
    render(
      <Button asChild loading>
        <label data-testid="wrap">
          <input type="file" />
        </label>
      </Button>,
    );
    const wrap = screen.getByTestId("wrap");
    expect(wrap.querySelector("input")).toBeTruthy();
    expect(wrap.querySelector("svg")).toBeNull();
  });
});

/**
 * 行内动作(`variant="inline"`):挨着一个值、一行说明的次要动作。比正文小一档、次要色、图标缩小、不撑高那一行 ——
 * 维护者截图里「在 Civitai 上找」「标为 NSFW」用的是 sm 档、正文字号,比旁边的值还醒目。
 */
describe("Button 的行内动作那一档", () => {
  it("小一档的字、次要色、24px 高(上下各收 2px)、14px 图标;写了 size 也是这一套", () => {
    for (const size of [undefined, "sm", "default"] as const) {
      const { getByRole, unmount } = render(<Button variant="inline" size={size}>在 Civitai 上找</Button>);
      const classes = getByRole("button").className.split(/\s+/);
      expect(classes).toEqual(expect.arrayContaining(["text-ui-xs", "text-muted-foreground", "font-normal", "h-6", "-my-0.5", "px-1.5", "[&_svg]:size-3.5"]));
      for (const gone of ["text-ui-sm", "h-8", "h-10", "px-3", "px-4", "font-medium", "[&_svg]:size-4"]) expect(classes, `${size}: ${gone}`).not.toContain(gone);
      unmount();
    }
  });

  it("别的档位一个类都没变(行内动作只是新增的一档)", () => {
    const { getByRole } = render(<Button variant="ghost" size="sm">展开</Button>);
    const classes = getByRole("button").className.split(/\s+/);
    expect(classes).toEqual(expect.arrayContaining(["h-8", "px-3", "text-ui-sm", "font-medium", "[&_svg]:size-4"]));
    expect(classes).not.toContain("text-muted-foreground");
  });
});
