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
