/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { EntitySummary } from "@/api/client";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));

import { ComposerChips } from "@/features/agent/ComposerChips";
import { entityMentionChips } from "./EntityMention";

const summary = (extra: Partial<EntitySummary>): EntitySummary => ({
  id: "e1",
  kind: "character",
  parent_id: null,
  parent_name: "",
  name: "张三",
  cover_asset_id: null,
  tags: [],
  reference_count: 0,
  variant_count: 0,
  updated_at: "2026-11-02T00:00:00Z",
  ...extra,
} as EntitySummary);

describe("资产引用小条", () => {
  it("姿势引用内部带小勾选，勾上才把姿势图当普通参考图", async () => {
    const onChange = vi.fn();
    const chips = entityMentionChips([summary({ id: "p1", kind: "pose", name: "站姿" })], vi.fn(), {
      pose: { checked: false, supported: false, onChange },
    });
    render(<ComposerChips chips={chips} />);

    const toggle = screen.getByRole("checkbox", { name: "genPoseAsReference" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    //: 模型不收姿势参考时不是普通空圈,而是一枚警告图标;点击它才明确改成普通参考图。
    expect(toggle.parentElement?.querySelector(".lucide-circle-alert")).toBeTruthy();
    await userEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("悬停说明会区分模型收不收姿势参考", async () => {
    const chips = entityMentionChips([summary({ id: "p1", kind: "pose", name: "站姿" })], vi.fn(), {
      pose: { checked: false, supported: false, onChange: vi.fn() },
    });
    render(<ComposerChips chips={chips} />);
    await userEvent.hover(screen.getByRole("checkbox", { name: "genPoseAsReference" }));
    expect(await screen.findByText("genPoseReferenceUnsupported")).toBeInTheDocument();
  });

  it("点引用小条会打开预览，而不是只做删除", async () => {
    const onPreview = vi.fn();
    const chips = entityMentionChips([summary({ id: "c1", kind: "character" })], vi.fn(), { onPreview });
    render(<ComposerChips chips={chips} />);
    await userEvent.click(screen.getByRole("button", { name: "@张三" }));
    expect(onPreview).toHaveBeenCalledWith(expect.objectContaining({ id: "c1" }));
  });

  it("非姿势引用内部不出现这个开关", () => {
    const chips = entityMentionChips([summary({ id: "c1", kind: "character" })], vi.fn(), {
      pose: { checked: false, supported: true, onChange: vi.fn() },
    });
    render(<ComposerChips chips={chips} />);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("多个姿势引用只挂一个开关，因为请求只有一档发送方式", () => {
    const chips = entityMentionChips(
      [
        summary({ id: "p1", kind: "pose", name: "站姿" }),
        summary({ id: "p2", kind: "pose", name: "坐姿" }),
      ],
      vi.fn(),
      { pose: { checked: false, supported: true, onChange: vi.fn() } },
    );
    render(<ComposerChips chips={chips} />);
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });
});
