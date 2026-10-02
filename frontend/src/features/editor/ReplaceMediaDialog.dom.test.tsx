/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import type { Asset, Sequence } from "@/api/client";
import { ReplaceMediaDialog } from "@/features/editor/ReplaceMediaDialog";

const clip = (id: string, asset: string, start: number) => ({ id, asset_id: asset, timeline_start: start, src_in: 0, src_out: 2, speed: 1 });
const sequence = {
  id: "s",
  tracks: [{ id: "V1", kind: "video", clips: [clip("a", "old", 0), clip("b", "old", 5)] }],
} as unknown as Sequence;
const assets = [
  { id: "old", name: "原片", kind: "video" },
  { id: "new", name: "降噪版", kind: "video" },
  { id: "music", name: "BGM", kind: "audio" },
] as unknown as Asset[];

describe("替换媒体", () => {
  it("只列这条轨放得下的素材;可以把用着同一份素材的片段一起换", async () => {
    const user = userEvent.setup();
    const onReplace = vi.fn();
    render(<ReplaceMediaDialog sequence={sequence} clipId="a" assets={assets} onCancel={vi.fn()} onReplace={onReplace} />);
    const options = screen.getAllByRole("option").map((one) => one.textContent);
    expect(options).toEqual(["降噪版"]);
    await user.click(screen.getByRole("option", { name: "降噪版" }));
    await user.click(screen.getByRole("button", { name: "replaceMediaApply" }));
    expect(onReplace).toHaveBeenLastCalledWith({ asset_id: "new", clip_ids: ["a"] });
    await user.click(screen.getByRole("switch"));
    await user.click(screen.getByRole("button", { name: "replaceMediaApply" }));
    expect(onReplace).toHaveBeenLastCalledWith({ asset_id: "new", from_asset_id: "old" });
  });
});
