/** @vitest-environment jsdom */
/**
 * 时间线工具栏上的「序列设置」:画幅和填充方式。
 *
 * 它们此前写在检查器的「未选中片段」那一支里 —— 而检查器只在选中片段时出现,那一支永远画不出来,
 * 画幅和填充方式因此没有任何入口。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import type { Sequence } from "@/api/client";
import { SequenceSettings } from "./SequenceSettings";

const sequence = (extra: Partial<Sequence> = {}) =>
  ({ id: "s", name: "S", width: 1920, height: 1080, fps: 30, reframe: { fill_mode: "contain" }, ...extra }) as Sequence;

async function open(seq: Sequence, onReframe = vi.fn()) {
  render(<SequenceSettings sequence={seq} onReframe={onReframe} />);
  await userEvent.click(screen.getByRole("button", { name: /sequenceSettings/ }));
  return onReframe;
}

describe("序列设置", () => {
  it("触发按钮上看得到当前画幅;弹层里当前画幅和填充方式是选中的", async () => {
    await open(sequence());
    expect(screen.getByRole("button", { name: /sequenceSettings/ })).toHaveTextContent("16:9");
    expect(screen.getByRole("radio", { name: "16:9" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "fillContain" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("1920×1080 · 30fps")).toBeInTheDocument();
  });

  it("换画幅保留填充方式,换填充方式保留画幅;点已选中的那一档不发请求", async () => {
    const onReframe = await open(sequence());
    await userEvent.click(screen.getByRole("radio", { name: "9:16" }));
    expect(onReframe).toHaveBeenLastCalledWith(1080, 1920, "contain");
    await userEvent.click(screen.getByRole("radio", { name: "fillBlur" }));
    expect(onReframe).toHaveBeenLastCalledWith(1920, 1080, "blur");
    await userEvent.click(screen.getByRole("radio", { name: "16:9" }));
    await userEvent.click(screen.getByRole("radio", { name: "fillContain" }));
    expect(onReframe).toHaveBeenCalledTimes(2);
  });

  it("改的请求在路上:点的那一档转圈,别的几档点不了也不转;请求回来就停", async () => {
    const onReframe = vi.fn();
    const { rerender } = render(<SequenceSettings sequence={sequence()} onReframe={onReframe} />);
    await userEvent.click(screen.getByRole("button", { name: /sequenceSettings/ }));
    await userEvent.click(screen.getByRole("radio", { name: "9:16" }));
    rerender(<SequenceSettings sequence={sequence()} onReframe={onReframe} pending />);
    const picked = screen.getByRole("radio", { name: "9:16" });
    expect(picked).toHaveAttribute("aria-busy", "true");
    expect(picked.querySelector("svg.animate-mosael-spin")).not.toBeNull();
    const other = screen.getByRole("radio", { name: "1:1" });
    expect(other).toBeDisabled();
    expect(other).not.toHaveAttribute("aria-busy");
    expect(screen.getByRole("radio", { name: "fillBlur" })).not.toHaveAttribute("aria-busy");
    rerender(<SequenceSettings sequence={sequence({ width: 1080, height: 1920 })} onReframe={onReframe} />);
    expect(screen.getByRole("radio", { name: "9:16" })).not.toHaveAttribute("aria-busy");
    expect(screen.getByRole("radio", { name: "9:16" }).querySelector("svg")).toBeNull();
  });

  it("不在预设里的尺寸照样显示,没有哪一档亮着;没写填充方式就是裁剪", async () => {
    await open(sequence({ width: 1280, height: 720, reframe: {} }));
    expect(screen.getByRole("button", { name: /sequenceSettings/ })).toHaveTextContent("1280×720");
    for (const radio of screen.getAllByRole("radio", { checked: true })) {
      expect(radio).toHaveAccessibleName("fillCover");
    }
  });
});
