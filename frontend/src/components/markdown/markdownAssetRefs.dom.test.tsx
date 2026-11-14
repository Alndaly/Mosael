/** @vitest-environment jsdom */
/**
 * 回复正文里引用的本机素材 `![说明](mosael-asset:<id>)` 按素材种类画:视频出播放器、音频出音频条、图照旧。
 * 此前一律当 `<img>`,引用一段视频就是一枚破图标(维护者截图:Remotion 渲好的片子在回复里看不了)。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: async (path: string) => {
    const id = path.split("/").pop() ?? "";
    const kind = id.startsWith("vid") ? "video" : id.startsWith("aud") ? "audio" : "image";
    return { id, name: `${id}.bin`, kind, workspace_id: "w" };
  },
}));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh-CN" }) }));

import { AgentMarkdown } from "./Markdown";

afterEach(cleanup);

function renderReply(text: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AgentMarkdown>{text}</AgentMarkdown>
    </QueryClientProvider>,
  );
}

it("引用一段视频:画成视频卡(播放器),不是一张取不到的图", async () => {
  const view = renderReply("渲好了:\n\n![随便 · Remotion 动画](mosael-asset:vid-1)\n\n片子内容……");
  await waitFor(() => expect(view.container.querySelector('[data-media-preview="vid-1"]')).not.toBeNull());
  expect(view.container.querySelector('[data-media-preview="vid-1"] video')).not.toBeNull();
  expect(view.container.querySelector('img[data-streamdown="image"]')).toBeNull();
});

it("引用一段音频:画成音频卡", async () => {
  const view = renderReply("![配音](mosael-asset:aud-1)");
  await waitFor(() => expect(view.container.querySelector('[data-media-preview="aud-1"]')).not.toBeNull());
  expect(view.container.querySelector('[data-media-preview="aud-1"] video')).toBeNull();
});

it("引用一张图:照旧是图(在素材卡里,点开进灯箱)", async () => {
  const view = renderReply("![海报](mosael-asset:img-1)");
  await waitFor(() => expect(view.container.querySelector('[data-media-preview="img-1"] img')).not.toBeNull());
});
