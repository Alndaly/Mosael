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
  { capability: "audio_denoise", label: "降噪", description: "去底噪", current: null, automatic: "builtin:ffmpeg",
    options: [
      { id: "builtin:ffmpeg", name: "内置降噪", builtin: true, missing: [] },
      { id: "builtin:deepfilternet", name: "DeepFilterNet", builtin: true, missing: [] },
      { id: "builtin:rnnoise", name: "RNNoise", builtin: true, missing: ["ffmpeg 不带这个滤镜"] },
      { id: "p1", name: "云端降噪", builtin: false, missing: [] },
    ],
    used_by: [
      { kind: "app", label: "素材库:降噪" },
      { kind: "workflow", label: "工作流节点「降噪」的「引擎」" },
      { kind: "agent", label: "智能体工具 denoise_audio" },
    ] },
  { capability: "document_parse", label: "文档解析", description: "转成 Markdown", current: null, automatic: "builtin:local",
    options: [{ id: "builtin:local", name: "本地解析", builtin: true, missing: [] }, { id: "m1", name: "MinerU 云端", builtin: false, missing: [] }] },
  { capability: "audio_separation", label: "分离人声", description: "拆人声", current: null, automatic: "builtin:demucs",
    options: [{ id: "builtin:demucs", name: "Demucs(本机)", builtin: true, missing: [] }] },
  { capability: "public_url", label: "素材外链", description: "换直链", current: null, automatic: null, options: [] },
];
vi.mock("@/api/domains/capabilities", () => ({ listCapabilityChoices: vi.fn(async () => listed), setCapabilityDefault: vi.fn() }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
//: 下拉在 jsdom 里点不开;这里只关心**给了哪几项**,所以把选项平铺出来。
vi.mock("@/components/ui/option-picker", () => ({
  OptionPicker: ({ options }: { options: Array<{ value: string; label: string }> }) => (
    <ul data-picker="">{options.map((one) => <li key={one.value} data-value={one.value}>{one.label}</li>)}</ul>
  ),
}));

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
  //: 一家都没有:给一个去插件页的入口,不摆一个点开是空的下拉。
  expect(screen.getByRole("link", { name: "capabilityGoPlugins" }).getAttribute("href")).toBe("#/plugins");
});

it("只有一家可用时直接写出是哪一家,不摆一个灰掉的下拉", async () => {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("分离人声")).toBeTruthy());
  const group = screen.getByText("分离人声").closest('[data-slot="settings-group"]') as HTMLElement;
  expect(group.querySelector("[data-picker]")).toBeNull();
  expect(group.querySelector('[data-slot="settings-item-state"]')?.textContent).toBe("Demucs(本机)");
  expect(group.textContent).toContain("capabilityOnlyOne");
  expect(container.querySelectorAll("[data-picker]")).toHaveLength(2);
});

it("几个内置实现并列可选:自动用的那个就是「不指定」,别的内置引擎和插件一样能点名;没配好的说清缺什么", async () => {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  const picker = container.querySelector<HTMLElement>("[data-picker]")!;
  expect([...picker.querySelectorAll("li")].map((one) => one.textContent)).toEqual(["内置降噪", "DeepFilterNet", "云端降噪"]);
  expect(screen.getByText("capabilityBuiltinUnready")).toBeTruthy();
});

it("每项能力下面列「用在哪」,照接口给的逐条列;接口没给就不画这一行", async () => {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  const lists = container.querySelectorAll("[data-capability-uses]");
  expect(lists).toHaveLength(1);
  expect([...lists[0].querySelectorAll<HTMLElement>("[data-capability-use]")].map((one) => one.dataset.capabilityUse)).toEqual(["app", "workflow", "agent"]);
  expect(lists[0].textContent).toContain("工作流节点「降噪」的「引擎」");
});
