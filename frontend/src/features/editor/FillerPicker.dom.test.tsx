/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { readHint } from "@/test/hint";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import {
  DEFAULT_FILLER_CATEGORIES,
  fillerMatches,
  isFillerToken,
  type FillerCategoryId,
  type ProjectedSegment,
} from "@/domain/timeline/transcriptProjection";
import { FillerPicker } from "@/features/editor/FillerPicker";

const row = (words: string[]): ProjectedSegment => ({
  segmentId: "s", clipId: "c", text: words.join(""), speaker: null, timelineStart: 0, timelineEnd: words.length,
  srcStart: 0, srcEnd: words.length, clipped: false, continues: null,
  tokens: words.map((text, index) => ({ start_time: index, end_time: index + 1, text })),
});

describe("口癖词表", () => {
  it("歧义词(那个 / like)默认不算口癖,拖音默认算", () => {
    expect(isFillerToken("呃")).toBe(true);
    expect(isFillerToken("那个")).toBe(false);
    expect(isFillerToken("like")).toBe(false);
    expect(isFillerToken("那个", new Set<FillerCategoryId>(["ambiguousZh"]))).toBe(true);
  });

  it("每一处都带上前后文,给人预览", () => {
    const [match] = fillerMatches([row(["我们", "呃", "去", "公园"])]);
    expect(match).toMatchObject({ key: "c:s:1", word: "呃", before: "我们", after: "去公园", category: "hesitation" });
  });
});

function Harness({ onSelect }: { onSelect: (keys: string[]) => void }) {
  const [enabled, setEnabled] = React.useState<Set<FillerCategoryId>>(() => new Set(DEFAULT_FILLER_CATEGORIES));
  const matches = fillerMatches([row(["呃", "那个", "人", "嗯"])]);
  return <FillerPicker matches={matches} enabled={enabled} onEnabledChange={setEnabled} onSelect={(chosen) => onSelect(chosen.map((m) => m.key))} />;
}

describe("口癖选择", () => {
  it("先预览、默认不含歧义词;打开那一类之后才一起选中", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);
    await user.click(screen.getByRole("button", { name: /fillers/ }));
    const preview = screen.getByRole("list", { name: "fillerPreview" });
    expect(preview.textContent).toContain("呃");
    expect(preview.querySelectorAll("mark")).toHaveLength(2);
    await user.click(screen.getByRole("switch", { name: "fillerCategory_ambiguousZh" }));
    expect(preview.querySelectorAll("mark")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: /fillerSelect/ }));
    expect(onSelect).toHaveBeenCalledWith(["c:s:0", "c:s:1", "c:s:3"]);
  });

  it("弹层里那颗「选中」铺满这一列 —— 和上面的类别开关同宽", async () => {
    const user = userEvent.setup();
    render(<Harness onSelect={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /fillers/ }));
    const select = screen.getByRole("button", { name: /fillerSelect/ });
    //: 弹层内容 `flex flex-col`,按钮是直接一项 → 列的 stretch 把它拉满;不往控件自己身上写宽度。
    expect(select.parentElement).toHaveClass("flex", "flex-col");
    expect(select).not.toHaveClass("w-full");
  });

  it("入口是图标按钮:计数在角标里、名字和说明在 Hint 里,不是 title=", async () => {
    render(<Harness onSelect={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "fillers" });
    expect(trigger.getAttribute("aria-label")).toBe("fillers");
    // 可见的只有图标 + 数字角标;动作名不在按钮里。
    expect(trigger.textContent).toBe("2");
    expect(trigger.querySelector("[data-count-badge]")?.textContent).toBe("2");
    expect(trigger.hasAttribute("title")).toBe(false);
    const hint = await readHint(trigger);
    expect(hint).toContain("fillers");
    expect(hint).toContain("fillersHint");
  });
});
