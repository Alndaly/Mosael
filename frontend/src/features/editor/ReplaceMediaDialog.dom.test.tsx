/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

//: 服务端按种类筛:只交回这几种里的那些。
const library = [
  { id: "old", name: "原片", kind: "video" },
  { id: "new", name: "降噪版", kind: "video" },
  { id: "music", name: "BGM", kind: "audio" },
];
vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  listAssetPage: vi.fn(async (query: { kind?: string[] }) => ({
    items: library.filter((one) => !query.kind || query.kind.includes(one.kind)),
    next_cursor: null,
    total: 2,
  })),
}));

import { listAssetPage, type Sequence } from "@/api/client";
import { ReplaceMediaDialog } from "@/features/editor/ReplaceMediaDialog";

const clip = (id: string, asset: string, start: number) => ({ id, asset_id: asset, timeline_start: start, src_in: 0, src_out: 2, speed: 1 });
const sequence = {
  id: "s",
  workspace_id: "ws",
  project_id: "p",
  tracks: [{ id: "V1", kind: "video", clips: [clip("a", "old", 0), clip("b", "old", 5)] }],
} as unknown as Sequence;

describe("替换媒体", () => {
  it("只列这条轨放得下的素材;可以把用着同一份素材的片段一起换", async () => {
    const user = userEvent.setup();
    const onReplace = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ReplaceMediaDialog sequence={sequence} clipId="a" onCancel={vi.fn()} onReplace={onReplace} />
      </QueryClientProvider>,
    );
    await screen.findByRole("option", { name: "降噪版" });
    const options = screen.getAllByRole("option").map((one) => one.textContent);
    expect(options).toEqual(["降噪版"]);
    expect(vi.mocked(listAssetPage).mock.calls[0][0]).toMatchObject({ workspace_id: "ws", project_id: "p", kind: ["video", "image"] });
    await user.click(screen.getByRole("option", { name: "降噪版" }));
    await user.click(screen.getByRole("button", { name: "replaceMediaApply" }));
    expect(onReplace).toHaveBeenLastCalledWith({ asset_id: "new", clip_ids: ["a"] });
    await user.click(screen.getByRole("switch"));
    await user.click(screen.getByRole("button", { name: "replaceMediaApply" }));
    expect(onReplace).toHaveBeenLastCalledWith({ asset_id: "new", from_asset_id: "old" });
  });
});
