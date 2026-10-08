/** @vitest-environment jsdom */

/**
 * 分段控件三档(docs/DESIGN_LANGUAGE.md「选择类控件」):总高度跟着这一行的档位,md 40 / sm 32 / xs 28。
 * 此前只有 40 这一档,别处在 className 里压成六种样子。
 */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CONTROL_HEIGHT } from "@/components/ui/control-size";
import { Segmented, segmentedItemClass, segmentedListClass } from "@/components/ui/segmented";

afterEach(cleanup);

const OPTIONS = [
  { value: "chat", label: "对话" },
  { value: "create", label: "创作" },
  { value: "old", label: "以前的", disabled: true },
] as const;

describe("分段控件", () => {
  it.each([
    ["md", "h-8", "p-1"],
    ["sm", CONTROL_HEIGHT.xs, "p-0.5"],
    ["xs", "h-6", "p-0.5"],
  ] as const)("%s:一项 %s,外壳内边距 %s —— 加起来就是这一档的高度", (size, item, padding) => {
    expect(segmentedItemClass(false, size).split(/\s+/)).toContain(item);
    expect(segmentedListClass(size).split(/\s+/)).toContain(padding);
  });

  it("单选语义:一组 radio,选中的那一项 aria-checked、强调底色;点一项就选它", () => {
    const onValueChange = vi.fn();
    render(<Segmented aria-label="分区" value="chat" onValueChange={onValueChange} options={[...OPTIONS]} />);
    const group = screen.getByRole("radiogroup", { name: "分区" });
    const [chat, create] = screen.getAllByRole("radio");
    expect(group).toBeTruthy();
    expect(chat.getAttribute("aria-checked")).toBe("true");
    expect(chat.className.split(/\s+/)).toContain("bg-accent");
    expect(create.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(create);
    expect(onValueChange).toHaveBeenCalledWith("create");
  });

  it("键盘:Tab 只停在选中的那一项;方向键换到哪个就选哪个,跳过点不了的;Home / End 到头尾", () => {
    const onValueChange = vi.fn();
    render(<Segmented aria-label="分区" value="create" onValueChange={onValueChange} options={[...OPTIONS]} />);
    const [chat, create] = screen.getAllByRole("radio");
    expect(chat.tabIndex).toBe(-1);
    expect(create.tabIndex).toBe(0);
    fireEvent.keyDown(create, { key: "ArrowRight" });
    expect(onValueChange).toHaveBeenLastCalledWith("chat");
    fireEvent.keyDown(create, { key: "ArrowLeft" });
    expect(onValueChange).toHaveBeenLastCalledWith("chat");
    fireEvent.keyDown(chat, { key: "End" });
    expect(onValueChange).toHaveBeenLastCalledWith("create");
  });
});
