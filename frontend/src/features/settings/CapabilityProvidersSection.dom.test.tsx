/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

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
  { capability: "speech", label: "配音", description: "念字", current: null, automatic: null, defaultable: false,
    options: [
      { id: "builtin:clone", name: "本地音色克隆", builtin: true, missing: [] },
      { id: "builtin:openai", name: "OpenAI", builtin: true, missing: ["还没配好这家的连接"] },
    ],
    used_by: [{ kind: "app", label: "剪辑页字幕:「配音」" }] },
  { capability: "public_url", label: "素材外链", description: "换直链", current: null, automatic: null, options: [] },
];
const { listCapabilityChoices } = vi.hoisted(() => ({ listCapabilityChoices: vi.fn() }));
vi.mock("@/api/domains/capabilities", () => ({ listCapabilityChoices, setCapabilityDefault: vi.fn() }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
const { findPluginsFor } = vi.hoisted(() => ({ findPluginsFor: vi.fn() }));
vi.mock("@/lib/deepLink", () => ({ findPluginsFor }));
//: 下拉在 jsdom 里点不开;这里只关心**给了哪几项**,所以把选项平铺出来。
vi.mock("@/components/ui/option-picker", () => ({
  OptionPicker: ({ options }: { options: Array<{ value: string; label: string }> }) => (
    <ul data-picker="">{options.map((one) => <li key={one.value} data-value={one.value}>{one.label}</li>)}</ul>
  ),
}));

import { CapabilityProvidersSection } from "./CapabilityProvidersSection";

beforeEach(() => {
  listCapabilityChoices.mockReset();
  listCapabilityChoices.mockImplementation(async () => listed);
});

it("后端还在答的那几秒是骨架屏,不是一片白;答了原地换上", async () => {
  //: 用户:「能力提供方这个页面要加载很久,会有很长时间的白屏,也没有 Skeleton 或者 loading」。
  let answer!: (value: typeof listed) => void;
  listCapabilityChoices.mockImplementation(() => new Promise((resolve) => { answer = resolve; }));
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  expect(container.querySelector("[data-capability-loading]")?.getAttribute("aria-busy")).toBe("true");
  answer(listed);
  await waitFor(() => expect(screen.getByText("文档解析")).toBeTruthy());
  expect(container.querySelector("[data-capability-loading]")).toBeNull();
});

it("加载失败说出来、能重试,不是一片白", async () => {
  listCapabilityChoices.mockRejectedValue(new Error("boom"));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("button", { name: /retry|重试/i })).toBeTruthy();
});

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
  const denoise = screen.getByText("降噪").closest('[data-slot="settings-group"]') as HTMLElement;
  const picker = denoise.querySelector<HTMLElement>("[data-picker]")!;
  expect([...picker.querySelectorAll("li")].map((one) => one.textContent)).toEqual(["内置降噪", "DeepFilterNet", "云端降噪"]);
  expect(within(denoise).getByText("capabilityBuiltinUnready")).toBeTruthy();
  expect(container.querySelectorAll("[data-picker]").length).toBeGreaterThan(1);
});

it("每项能力下面列「用在哪」,照接口给的逐条列;接口没给就不画这一行", async () => {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  const denoise = screen.getByText("降噪").closest('[data-slot="settings-group"]') as HTMLElement;
  const lists = denoise.querySelectorAll("[data-capability-uses]");
  expect(lists).toHaveLength(1);
  //: 分离人声、文档解析、外链的样例数据没给 used_by —— 那几组不画这一行。
  expect(container.querySelectorAll("[data-capability-uses]")).toHaveLength(2);
  expect([...lists[0].querySelectorAll<HTMLElement>("[data-capability-use]")].map((one) => one.dataset.capabilityUse)).toEqual(["app", "workflow", "agent"]);
  expect(lists[0].textContent).toContain("工作流节点「降噪」的「引擎」");
});

it("没有默认的能力(配音)不摆选择器:列有哪几家、缺什么、用在哪", async () => {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("配音")).toBeTruthy());
  const group = screen.getByText("配音").closest('[data-slot="settings-group"]') as HTMLElement;
  expect(group.querySelector("[data-picker]")).toBeNull();
  expect(group.textContent).toContain("capabilityNoDefault");
  expect(group.querySelector("[data-capability-ready]")?.textContent).toBe("本地音色克隆");
  expect(group.textContent).toContain("capabilityBuiltinUnready");
  expect(group.querySelectorAll("[data-capability-use]")).toHaveLength(1);
  expect(container.querySelectorAll("[data-picker]").length).toBeGreaterThan(0);
});

it("每项能力都能去插件市场找「谁还能做这件事」,带着这项能力去", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("配音")).toBeTruthy());
  expect(screen.getAllByRole("button", { name: /capabilityFindPlugins/ })).toHaveLength(listed.length);
  const speech = screen.getByText("配音").closest('[data-slot="settings-group"]') as HTMLElement;
  within(speech).getByRole("button", { name: /capabilityFindPlugins/ }).click();
  expect(findPluginsFor).toHaveBeenCalledWith("speech");
});
