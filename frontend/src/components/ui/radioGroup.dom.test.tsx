/** @vitest-environment jsdom */

/** 单选:底下是原生的同名 radio —— 方向键、Tab、读屏都是浏览器给的;每项可带一行说明。 */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RadioGroup } from "@/components/ui/radio-group";

afterEach(cleanup);

const OPTIONS = [
  { value: "system", label: "跟着系统", description: "系统切深色时一起切" },
  { value: "light", label: "总是浅色" },
  { value: "dark", label: "总是深色", disabled: true },
] as const;

describe("单选", () => {
  it("一组同名的 radio,名字和说明都在可点的那一块里;选中的那一项 checked", () => {
    render(<RadioGroup aria-label="主题" value="system" onValueChange={vi.fn()} options={[...OPTIONS]} />);
    expect(screen.getByRole("radiogroup", { name: "主题" })).toBeTruthy();
    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(new Set(radios.map((radio) => radio.name)).size).toBe(1);
    expect(radios[0].checked).toBe(true);
    expect(screen.getByRole("radio", { name: /跟着系统/ })).toBe(radios[0]);
    expect(screen.getByText("系统切深色时一起切")).toBeTruthy();
    //: 圆点画在 input(绝对定位、有底色)上面:它自己不定位的话被那层底色盖住,选中了也看不见(真界面里栽过一次)。
    expect((radios[0].nextElementSibling as HTMLElement).className.split(/\s+/)).toContain("relative");
  });

  it("点名字就选它;点不了的那一项不响应", () => {
    const onValueChange = vi.fn();
    render(<RadioGroup aria-label="主题" value="system" onValueChange={onValueChange} options={[...OPTIONS]} />);
    fireEvent.click(screen.getByText("总是浅色"));
    expect(onValueChange).toHaveBeenCalledWith("light");
    const dark = screen.getByRole("radio", { name: /总是深色/ }) as HTMLInputElement;
    expect(dark.disabled).toBe(true);
  });
});
