/** @vitest-environment jsdom */

/** 列表里一组的折叠标题:整行、会转的箭头、名字、右头的数字;aria-expanded 跟着开合;能套进右键菜单的触发器(转发 ref)。 */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GroupToggle } from "@/components/ui/group-toggle";

afterEach(cleanup);

describe("列表分组的折叠标题", () => {
  it("名字、数字都在这一颗按钮里;开合写在 aria-expanded 上;点了交给调用方", () => {
    const onClick = vi.fn();
    const { rerender } = render(<GroupToggle open={false} label="来自别处" count={3} onClick={onClick} />);
    const toggle = screen.getByRole("button", { name: /来自别处/ });
    expect(toggle.textContent).toContain("3");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.getAttribute("type")).toBe("button");
    fireEvent.click(toggle);
    expect(onClick).toHaveBeenCalledTimes(1);
    rerender(<GroupToggle open label="来自别处" count={3} onClick={onClick} />);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("转发 ref(右键菜单的触发器 asChild 要拿到它)", () => {
    const ref = React.createRef<HTMLButtonElement>();
    render(<GroupToggle ref={ref} open label="默认分组" />);
    expect(ref.current?.tagName).toBe("BUTTON");
  });
});
