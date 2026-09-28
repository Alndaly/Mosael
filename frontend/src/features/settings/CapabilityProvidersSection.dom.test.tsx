/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

/**
 * 「能力提供方」照后端的能力表列(ADR 0031 §5):一项能力一组。有内置实现的(文档解析)不定就是内置的;
 * 没有的(素材外链)一家都没有时说去哪儿建。
 */

const listed = [
  { capability: "document_parse", label: "文档解析", description: "转成 Markdown", current: null, automatic: "builtin:local",
    options: [{ id: "builtin:local", name: "本地解析", builtin: true, missing: [] }, { id: "m1", name: "MinerU 云端", builtin: false, missing: [] }] },
  { capability: "public_url", label: "素材外链", description: "换直链", current: null, automatic: null, options: [] },
];
vi.mock("@/api/client", () => ({ api: vi.fn(async () => listed) }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { CapabilityProvidersSection } from "./CapabilityProvidersSection";

it("一项能力一组;文档解析不定就是本地解析,外链一家都没有时说去建一个", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("文档解析")).toBeTruthy());
  expect(screen.getByText("素材外链")).toBeTruthy();
  expect(screen.getByText("本地解析")).toBeTruthy();
  expect(screen.getByText("assetLinkNone")).toBeTruthy();
});
