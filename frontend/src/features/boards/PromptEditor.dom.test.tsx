/** @vitest-environment jsdom */
import React from "react";
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { PromptEditor, type PromptDocument } from "./PromptEditor";

afterEach(cleanup);

const saved: PromptDocument = {
  type: "doc",
  content: [
    {
      type: "paragraph",
      content: [
        { type: "assetRef", attrs: { assetId: "asset-1", name: "森林.jpg" } },
        { type: "text", text: " 里的女孩换一套衣服" },
      ],
    },
  ],
};

function mount() {
  return render(
    <PromptEditor
      value="森林.jpg 里的女孩换一套衣服"
      document={saved}
      onChange={vi.fn()}
      placeholder="写点什么"
      candidates={() => []}
      onSubmit={vi.fn()}
      emptyHint={() => ""}
    />,
  );
}

describe("提示词素材引用水合", () => {
  it("取消聚焦并重新挂载后仍渲染素材 chip，而不是降级成文件名文本", async () => {
    const first = mount();
    await waitFor(() =>
      expect(first.container.querySelector('[data-asset-id="asset-1"]')).toHaveAttribute("data-asset-ref", ""),
    );
    first.unmount();

    const second = mount();
    await waitFor(() =>
      expect(second.container.querySelector('[data-asset-id="asset-1"]')).toHaveAttribute("data-asset-ref", ""),
    );
    expect(second.container.textContent).toContain("森林.jpg");
  });
});
