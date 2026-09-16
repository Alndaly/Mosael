/** @vitest-environment jsdom */
/**
 * 「再加一行」是**一条撑满的虚线空位**,不是挂在列表末尾的一枚幽灵小钮。
 *
 * 用户撞到的:一行都没有的时候,那枚按钮悬在一大片空白里 —— 读不出是可点的,也读不出它和
 * 上面那格是什么关系,只看得出"这里的间距不对劲"。判据是它长得像**它将要变成的那个东西**:
 * 点下去出现的是一整行,所以它本身就占一整行,并且有自己的边界。
 *
 * jsdom 量不到版面,能钉的是那三样决定它长相的东西都在:撑满、有边界、是虚线(虚线是
 * "这里还空着"的说法,实线会被读成又一格要填的表单)。
 */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

import { AddRow } from "./add-row";

it("占满一整行,而且有自己的边界", () => {
  render(<AddRow label="加一行" onClick={() => {}} />);
  const button = screen.getByRole("button", { name: /加一行/ });
  expect(button.className).toContain("w-full");
  expect(button.className).toContain("border");
  //: 虚线 —— 实线会被读成"又一格要填的字段",而它是个空位。
  expect(button.className).toContain("border-dashed");
  //: 有底色才看得出是一块可点的区域(hover 之前也得看得出来)。
  expect(button.className).toMatch(/bg-panel/);
});

it("高度跟着所在表单的刻度 —— 密排的检查器压一档", () => {
  const { rerender } = render(<AddRow label="加" onClick={() => {}} />);
  expect(screen.getByRole("button").className).toContain("h-10");
  rerender(<AddRow dense label="加" onClick={() => {}} />);
  expect(screen.getByRole("button").className).toContain("h-8");
});

it("点了要真的回调", () => {
  const add = vi.fn();
  render(<AddRow label="加一行" onClick={add} />);
  fireEvent.click(screen.getByRole("button"));
  expect(add).toHaveBeenCalledTimes(1);
});
