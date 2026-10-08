/** @vitest-environment jsdom */

/** 搜索框:字段的样子 + 左边一个放大镜;放大镜和输入框让出的位置跟着档位走;右头的一小段(结果数)不压字。 */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CONTROL_HEIGHT, SEARCH_FIELD } from "@/components/ui/control-size";
import { SearchInput } from "@/components/ui/search-input";

afterEach(cleanup);

describe("搜索框", () => {
  it.each(["xs", "sm", "md"] as const)("%s:高度、左边让出的位置、放大镜的位置和大小都是这一档的", (size) => {
    const { container } = render(<SearchInput size={size} aria-label="搜索" />);
    const input = screen.getByLabelText("搜索");
    const classes = input.className.split(/\s+/);
    expect(classes).toContain(CONTROL_HEIGHT[size]);
    expect(classes).toContain(SEARCH_FIELD[size].pad);
    const icon = container.querySelector("svg")!;
    for (const one of SEARCH_FIELD[size].icon.split(" ")) expect(icon.getAttribute("class")).toContain(one);
  });

  it("className 给外壳(排版),不进输入框;ref 指向输入框;右头的结果数给它让出位置", () => {
    const ref = React.createRef<HTMLInputElement>();
    render(<SearchInput ref={ref} className="w-52" aria-label="搜索" trailing={<span>3/12</span>} />);
    const input = screen.getByLabelText("搜索");
    expect(ref.current).toBe(input);
    expect(input.className).not.toContain("w-52");
    expect(input.closest("[data-search-input]")!.className).toContain("w-52");
    expect(input.className.split(/\s+/)).toContain("pr-12");
    expect(screen.getByText("3/12")).toBeTruthy();
  });
});
