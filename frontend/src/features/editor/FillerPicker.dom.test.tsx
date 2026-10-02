/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

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
});
