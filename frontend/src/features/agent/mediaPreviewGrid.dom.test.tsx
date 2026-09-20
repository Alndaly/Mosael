/** @vitest-environment jsdom */
/**
 * 取不到的素材收成一行小字,不各占一张卡。
 *
 * 聊天记录逐字留着工具结果,里面的素材 id 是**当时的事实**:后来在素材库里删掉几个,那条旧消息
 * 下面就挂出一片和成功卡一样大的灰块。真机上一次 42 步的长对话挂了十七张 ——
 * 看上去像"坏了一大片",而它说的只是"这些你后来删了"。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const gone = new Set<string>();
//: 只替掉发请求那一个出口,模块里别的东西(URL 拼装、类型)保持原样 —— 整块替掉的话,
//: 渲染树里任何一个还没被 mock 到的导出都会让组件直接渲染不出来。
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  api: async (path: string) => {
    const id = path.split("/").pop() ?? "";
    if (gone.has(id)) throw new Error("404");
    return { id, name: `素材 ${id}`, kind: "image", workspace_id: "w" };
  },
}));

//: 灯箱要 Provider,这块测试不关心点开之后的事。
vi.mock("@/components/app/image-preview", () => ({
  useImagePreview: () => ({ openImagePreview: vi.fn() }),
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({ agentMediaDeleted: "{n} 个素材已删除" })[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ToolCalls } from "@/features/agent/ToolCalls";

function renderRows(ok: string[], missing: string[]) {
  gone.clear();
  for (const id of missing) gone.add(id);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToolCalls
        tools={[{
          id: "t1", name: "generate_image", status: "done",
          args: {}, result: { asset_ids: [...ok, ...missing] },
        }]}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("工具结果里的媒体预览", () => {
  it("删掉的素材收成一行,不占卡位", async () => {
    const view = renderRows(["live-1"], ["gone-1", "gone-2", "gone-3"]);
    // 图标和文字是两个节点,所以按容器文本找。
    await waitFor(() => expect(view.container.textContent).toContain("3 个素材已删除"));
    expect(view.container.querySelectorAll("img")).toHaveLength(1);
  });

  it("全都还在时不出现那行字", async () => {
    const view = renderRows(["live-1", "live-2"], []);
    await waitFor(() => expect(view.container.querySelectorAll("img")).toHaveLength(2));
    expect(view.container.textContent).not.toContain("已删除");
  });
});
