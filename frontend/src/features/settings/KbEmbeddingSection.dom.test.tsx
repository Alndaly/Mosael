/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 嵌入配置没在工作时,这一屏必须说出来。
 *
 * 真实撞到的形状:用户删掉了那条 Ollama 连接。外键是 SET NULL,于是 `provider_profile_id`
 * 变成空,而 `model`(nomic-embed-text:latest)和 `dim`(768)原样留着。界面照常渲染出一个
 * 填得满满的表单,右下角写着"已保存" —— 而后端的 `enabled` 是 false,知识库检索**一点都没在跑**。
 *
 * 半截配置比空配置更坏:空的会让人去配,半截的让人以为配好了。
 */

const TEMPLATES: Record<string, string> = {
  kbEmbedTitle: "知识库嵌入",
  kbEmbedProvider: "嵌入供应商",
  kbEmbedModel: "嵌入模型",
  kbEmbedDim: "向量维度",
  kbEmbedRebuildNote: "更改后会在后台重嵌全部文档。",
  kbEmbedOff: "这套配置现在没有生效:先选一个嵌入供应商。",
  wfSavedShort: "已保存",
  wfSaving: "保存中",
};

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEMPLATES[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const profiles = [
  { id: "p1", name: "百炼qwen", enabled: true, capability_ids: ["chat", "embedding"] },
];

let config: Record<string, unknown> = {};

vi.mock("@/api/client", () => ({
  api: async (path: string) => {
    if (path.startsWith("/api/settings/kb-embedding")) return config;
    if (path.startsWith("/api/settings/providers")) return profiles;
    return {};
  },
}));

import { KbEmbeddingSection } from "@/features/settings/KbEmbeddingSection";

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <KbEmbeddingSection />
    </QueryClientProvider>,
  );
}

describe("知识库嵌入", () => {
  it("供应商没了但模型还留着时,明说它没在工作", async () => {
    // 删掉连接之后库里就是这个样子(FK SET NULL,model/dim 原样留着)。
    config = { provider_profile_id: null, model: "nomic-embed-text:latest", dim: 768, enabled: false };

    const { container } = renderSection();

    await waitFor(() => expect(screen.queryByText(TEMPLATES.kbEmbedModel)).toBeTruthy());
    expect(container.textContent).toContain(TEMPLATES.kbEmbedOff);
    expect(container.textContent).not.toContain("已保存");
  });

  it("配好了就不吓唬人", async () => {
    config = { provider_profile_id: "p1", model: "text-embedding-v3", dim: 1024, enabled: true };

    const { container } = renderSection();

    await waitFor(() => expect(screen.queryByText(TEMPLATES.kbEmbedModel)).toBeTruthy());
    expect(container.textContent).not.toContain(TEMPLATES.kbEmbedOff);
    expect(container.textContent).toContain("已保存");
  });
});
