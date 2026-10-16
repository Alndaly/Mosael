/** @vitest-environment jsdom */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { readHint } from "@/test/hint";

import { FLOATING_BUTTON, FLOATING_GAP, FLOATING_SIZE, FLOATING_TOP_RIGHT, FloatingIconButton } from "./floating-button";

const Icon = () => <svg data-icon="" />;

/** 类名里带某个前缀的那几个(`top-*`、`z-*`)—— 比两颗钮是不是同一顶边、同一层,不比整串。 */
const prefixed = (element: HTMLElement, prefix: string) => [...element.classList].filter((one) => one.startsWith(prefix)).sort();

/** 离右边缘多少 px:`right-2`(刻度 4 → 8)和 `right-[52px]` 都读得出来。 */
function rightOffset(element: HTMLElement): number {
  const token = [...element.classList].find((one) => /^right-(\d+|\[\d+px\])$/.test(one));
  if (!token) throw new Error(`这颗钮没有 right-* 定位:${element.className}`);
  const exact = /\[(\d+)px\]/.exec(token);
  return exact ? Number(exact[1]) : Number(/right-(\d+)/.exec(token)![1]) * 4;
}

describe("浮在画面上的圆钮", () => {
  it("名字只写一次:既是读屏念的 aria-label,也是悬停说明", async () => {
    render(<FloatingIconButton label="保存到本地"><Icon /></FloatingIconButton>);
    const button = screen.getByRole("button", { name: "保存到本地" });
    expect(button.hasAttribute("title")).toBe(false);
    expect(await readHint(button)).toBe("保存到本地");
  });

  it("外观只有一档:36px 圆钮、半透明黑底、白图标 18px —— 都是基础件给的,不在调用处", () => {
    render(<FloatingIconButton label="保存到本地"><Icon /></FloatingIconButton>);
    const button = screen.getByRole("button", { name: "保存到本地" });
    for (const token of FLOATING_BUTTON.split(/\s+/).filter(Boolean)) {
      expect(button.classList.contains(token), `少了 ${token}`).toBe(true);
    }
    expect(FLOATING_BUTTON).toContain("size-9");
    expect(FLOATING_BUTTON).toContain("rounded-full");
    expect(FLOATING_BUTTON, "图标大小也在这里,调用方不写 size").toContain("[&_svg]:size-[18px]");
  });

  it("右上角那一排:同一顶边、同一层,往左每一颗正好退一颗钮 + 8px", () => {
    render(
      <>
        <FloatingIconButton slot={0} label="关闭"><Icon /></FloatingIconButton>
        <FloatingIconButton slot={1} label="保存到本地"><Icon /></FloatingIconButton>
      </>,
    );
    const close = screen.getByRole("button", { name: "关闭" });
    const save = screen.getByRole("button", { name: "保存到本地" });
    expect(prefixed(close, "top-")).toEqual(prefixed(save, "top-"));
    expect(prefixed(close, "z-")).toEqual(prefixed(save, "z-"));
    for (const token of FLOATING_TOP_RIGHT[0].split(" ")) expect(close.classList.contains(token)).toBe(true);
    for (const token of FLOATING_TOP_RIGHT[1].split(" ")) expect(save.classList.contains(token)).toBe(true);
    expect(rightOffset(save) - rightOffset(close)).toBe(FLOATING_SIZE + FLOATING_GAP);
  });

  it("不给 slot 就不摆位置:位置由调用方自己给(窗格里浮着的那种)", () => {
    render(<FloatingIconButton label="保存到本地" className="absolute left-2 top-8"><Icon /></FloatingIconButton>);
    const button = screen.getByRole("button", { name: "保存到本地" });
    expect(button.classList.contains("fixed")).toBe(false);
    expect([...button.classList].some((one) => one.startsWith("right-"))).toBe(false);
    expect([...button.classList]).toContain("absolute");
  });
});
