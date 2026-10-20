/** @vitest-environment jsdom */
import React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { CONTROL_HEIGHT } from "@/components/ui/control-size";
import { SETTINGS_FIELD_WIDTH, SettingsGroup, SettingsItemRow } from "@/components/settings/settings-layout";

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

/**
 * 后端能力表**今天**登记的 7 项(`domain/capabilities.registered()`,按名字排):
 * 降噪、分离人声、文档解析、素材外链、配音、转写、翻译。骨架在数据到之前只能照**同一条常量**的组数铺 ——
 * 这里把它抄成真实数据的样子,两边组数对不上就是骨架没跟上能力表(测试会红)。
 */
const registered = [
  { capability: "audio_denoise", label: "降噪", description: "去底噪", current: null, automatic: null, options: [] },
  { capability: "audio_separation", label: "分离人声", description: "拆人声", current: null, automatic: null, options: [] },
  { capability: "document_parse", label: "文档解析", description: "转成 Markdown", current: null, automatic: null, options: [] },
  { capability: "public_url", label: "素材外链", description: "换直链", current: null, automatic: null, options: [] },
  { capability: "speech", label: "配音", description: "念字", current: null, automatic: null, defaultable: false, options: [] },
  { capability: "transcription", label: "转写", description: "听写成字", current: null, automatic: null, options: [] },
  { capability: "translation", label: "翻译", description: "译成中文", current: null, automatic: null, options: [] },
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

import { CAPABILITY_SKELETON_GROUPS, CapabilityProvidersSection } from "./CapabilityProvidersSection";

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

/** 挂一个一直不答的查询:停在骨架屏上,直到测试自己调用 answer。 */
function renderPendingSkeleton() {
  let answer!: (value: typeof registered) => void;
  listCapabilityChoices.mockImplementation(() => new Promise<typeof registered>((resolve) => { answer = resolve; }));
  const view = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  return { ...view, answer };
}

const skeletonGroups = (container: HTMLElement) =>
  [...container.querySelectorAll<HTMLElement>("[data-capability-skeleton-group]")];

/**
 * 维护者截图:「能力提供方这边的 Skeleton 是否有点问题」。骨架屏画成**一排一样长的条**、
 * 第一块还是一大块矩形,而真实页是「一项能力一组」:组标题 + 一两行说明 +「用哪一家」一行 + 用在哪的标签排。
 * 下面几条把这件事钉在结构上。
 */
it("骨架的组数和真实能力表的组数一致 —— 加载完原地换上,不多不少", async () => {
  //: 7 = 后端能力表今天登记的项数(`domain/capabilities.registered()`)。骨架照同一条常量铺;
  //: 常量与真实数据组数对不上时这条会红,提醒去补 `CAPABILITY_SKELETON_GROUPS` 那一行。
  const { container, answer } = renderPendingSkeleton();
  expect(skeletonGroups(container)).toHaveLength(registered.length);
  expect(registered).toHaveLength(CAPABILITY_SKELETON_GROUPS.length);
  answer(registered);
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  expect(container.querySelectorAll('[data-slot="settings-group"]')).toHaveLength(registered.length);
});

it("每组骨架的内部照真实结构:标题行(名字 + 当前选择)+ 说明 + 控件行 + 收起的「用在哪」", async () => {
  const { container } = renderPendingSkeleton();
  const groups = skeletonGroups(container);
  expect(groups.length).toBeGreaterThan(0);
  groups.forEach((group, index) => {
    //: 骨架组就是真页的 `SettingsGroup`(同一个 data-slot),卡片外壳才落得上。
    expect(group.getAttribute("data-slot")).toBe("settings-group");
    const title = group.querySelector('[data-slot="settings-group-title"] [data-capability-skeleton-title]');
    expect(title).not.toBeNull();
    expect(title!.className).toContain("h-5");
    expect(title!.className).not.toContain("w-full");
    //: 标题行里还占着「现在用谁」那一格 —— 真页的当前选择就在名字旁边。
    expect(group.querySelector('[data-slot="settings-group-adornment"] [data-capability-skeleton-current]')).not.toBeNull();
    const lines = group.querySelectorAll('[data-slot="settings-group-description"] [data-capability-skeleton-description]');
    expect(lines.length).toBeGreaterThanOrEqual(1);
    expect(lines.length).toBeLessThanOrEqual(2);
    const row = group.querySelector('[data-slot="settings-item-row"]');
    expect(row).not.toBeNull();
    expect(row!.querySelector('[data-slot="settings-item-label"] [data-capability-skeleton-label]')).not.toBeNull();
    //: 「用在哪」不再是一排标签:有用法的那几组只占一行摘要,收起时一颗标签都没有。
    expect(group.querySelectorAll("[data-capability-skeleton-tag]")).toHaveLength(0);
    expect(group.querySelector("[data-capability-skeleton-uses]") !== null).toBe(CAPABILITY_SKELETON_GROUPS[index].uses > 0);
  });
});

it("每组高度不同:有下拉的组多一块和下拉同宽同高的控件,没下拉的组没有;说明有的两行", () => {
  const { container } = renderPendingSkeleton();
  const groups = skeletonGroups(container);
  const withPicker = groups.filter((group) => group.querySelector("[data-capability-skeleton-control]"));
  const withoutPicker = groups.filter((group) => !group.querySelector("[data-capability-skeleton-control]"));
  //: 别 7 组一模一样:分离人声、配音那两组真页没有下拉。
  expect(withPicker.length).toBeGreaterThan(0);
  expect(withoutPicker.length).toBeGreaterThan(0);
  for (const group of withPicker) {
    const control = group.querySelector<HTMLElement>("[data-capability-skeleton-control]")!;
    expect(control.className).toContain(CONTROL_HEIGHT.md);
    expect(control.className).toContain(SETTINGS_FIELD_WIDTH);
    //: 有下拉的组还带一行说明(「没配好的」/「点了会怎样」),和真页那一行一样。
    expect(group.querySelectorAll("[data-capability-skeleton-description]").length).toBeGreaterThanOrEqual(1);
  }
  //: 没有下拉的组,那一行只有左边一行字 —— 少了右侧那一块,整组就比有下拉的矮。
  for (const group of withoutPicker) {
    expect(group.querySelector('[data-slot="settings-item-control"]')).toBeNull();
    expect(group.querySelectorAll('[data-slot="settings-item-label"] [data-capability-skeleton-label]')).toHaveLength(1);
  }
  const lineCounts = groups.map((group) => group.querySelectorAll("[data-capability-skeleton-description]").length);
  expect(new Set(lineCounts).size).toBeGreaterThan(1);
  expect(lineCounts).toContain(1);
  expect(lineCounts).toContain(2);
  //: 只有真页有「用在哪」的那两组占着摘要行 —— 卡片因此也不会一样高。
  expect(groups.filter((group) => group.querySelector("[data-capability-skeleton-uses]")).length)
    .toBe(CAPABILITY_SKELETON_GROUPS.filter((shape) => shape.uses > 0).length);
});

it("第一块不是一大块矩形:从组标题 + 一句说明开始,和真页开头一样", () => {
  const { container } = renderPendingSkeleton();
  const first = skeletonGroups(container)[0];
  expect(first.querySelector('[data-slot="settings-group-title"] [data-capability-skeleton-title]')).not.toBeNull();
  expect(first.querySelectorAll('[data-slot="settings-group-description"] [data-capability-skeleton-description]').length)
    .toBeGreaterThanOrEqual(1);
  //: 骨架里没有比一行标题还高的大灰块(那一版是第一块一大片矩形)。
  for (const bar of first.querySelectorAll<HTMLElement>('[data-slot="skeleton"]')) {
    expect(bar.className).not.toMatch(/\b(?:min-)?h-(?:1[2-9]|[2-9]\d)\b/);
  }
});

it("加载中有语义:role=status + aria-busy + aria-live;灰条盖住不念,加载完整块切走", async () => {
  const { container, answer } = renderPendingSkeleton();
  const loading = container.querySelector("[data-capability-loading]");
  expect(loading).not.toBeNull();
  expect(loading!.getAttribute("role")).toBe("status");
  expect(loading!.getAttribute("aria-busy")).toBe("true");
  expect(loading!.getAttribute("aria-live")).toBe("polite");
  expect(loading!.textContent).toBe("pageLoading");
  //: 一屏灰条不该被读屏一条条念成内容。
  expect(container.querySelector("[data-capability-skeleton-content]")?.getAttribute("aria-hidden")).toBe("true");
  answer(registered);
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  expect(container.querySelector("[data-capability-loading]")).toBeNull();
});

it("prefers-reduced-motion:扫光整条撤掉;这页不另改动画", () => {
  //: `.skeleton` 的样子在 design/tokens.css,减少动态时 `::after` 的扫光不跑 —— 骨架只用 <Skeleton>、
  //: 不自己挂 `animate-*`。设计棘轮 design/compiledCascade.test.ts / design/skeletons.test.ts 同一条。
  const tokens = readFileSync(join(import.meta.dirname, "../../design/tokens.css"), "utf8");
  expect(tokens).toMatch(
    /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.skeleton::after\s*\{[^}]*display: none;[^}]*animation: none;/,
  );
  const source = readFileSync(join(import.meta.dirname, "CapabilityProvidersSection.tsx"), "utf8");
  expect(source).not.toMatch(/\banimate-(?:pulse|none|spin)\b/);
});

it("骨架组的壳就是真页卡片 SettingsGroup 那一套:外壳/抬头/标题/内容不是另写的一套间距", () => {
  const { container } = renderPendingSkeleton();
  const skeleton = skeletonGroups(container)[0];
  const real = render(
    <SettingsGroup card title="真页的一组" description="这一组是干什么的">
      <SettingsItemRow label="用哪一家" />
    </SettingsGroup>,
  ).container;
  const realGroup = real.querySelector<HTMLElement>('[data-slot="settings-group"]')!;
  expect(skeleton.className).toBe(realGroup.className);
  expect(skeleton.querySelector('[data-slot="settings-group-header"]')!.className)
    .toBe(real.querySelector('[data-slot="settings-group-header"]')!.className);
  expect(skeleton.querySelector('[data-slot="settings-group-title"]')!.className)
    .toBe(real.querySelector('[data-slot="settings-group-title"]')!.className);
  expect(skeleton.querySelector('[data-slot="settings-group-content"]')!.className)
    .toBe(real.querySelector('[data-slot="settings-group-content"]')!.className);
  //: 说明那一格只多一层 `grid gap-1.5`(几条灰条要竖着排),真页的类名一个不少。
  const realDescription = real.querySelector<HTMLElement>('[data-slot="settings-group-description"]')!;
  const skeletonDescription = skeleton.querySelector<HTMLElement>('[data-slot="settings-group-description"]')!;
  for (const token of realDescription.className.split(/\s+/)) {
    expect(skeletonDescription.className.split(/\s+/)).toContain(token);
  }
});

/**
 * 真页的说明在 0bb1a33f3(管理页)/ 本笔(设置页)拿掉了写死的 `max-w-2xl` —— 整页宽的面板里,
 * 42rem 的天花板就是维护者截图里那句「描述右侧有很大的间距」。骨架是**同一格**的占位:
 * 真页不自带宽度上限,骨架多留一条 `max-w-*` 就是在加载完的一瞬间把行宽从窄换到宽。
 */
it("说明那一格骨架不很多留一条宽度上限:真页已经没有 42rem 的天花板", () => {
  const { container } = renderPendingSkeleton();
  const skeleton = skeletonGroups(container)[0];
  const real = render(<SettingsGroup card title="真页的一组" description="这一组是干什么的" />).container;
  const realDescription = real.querySelector<HTMLElement>('[data-slot="settings-group-description"]')!;
  const skeletonDescription = skeleton.querySelector<HTMLElement>('[data-slot="settings-group-description"]')!;
  for (const node of [realDescription, skeletonDescription]) {
    expect(node.className.split(/\s+/).filter((token) => token.startsWith("max-w-"))).toEqual([]);
  }
  //: 骨架那一格仍是真页同一组类名 + 把几条灰条竖起来的那层 `grid gap-1.5`。
  const skeletonTokens = skeletonDescription.className.split(/\s+/);
  expect(skeletonTokens).toContain("grid");
  expect(skeletonTokens).toContain("gap-1.5");
  for (const token of realDescription.className.split(/\s+/)) {
    expect(skeletonTokens).toContain(token);
  }
});

it("真实页的数据到了:标题/说明/控件行/「用在哪」都在,骨架整块退场", async () => {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  const groups = [...container.querySelectorAll<HTMLElement>('[data-slot="settings-group"]')];
  expect(groups).toHaveLength(listed.length);
  for (const group of groups) {
    expect(group.querySelector('[data-slot="settings-group-title"]')).not.toBeNull();
    expect(group.querySelector('[data-slot="settings-group-description"]')).not.toBeNull();
    expect(group.querySelector('[data-slot="settings-item-row"]')).not.toBeNull();
  }
  //: 接口给了 `used_by` 的只有降噪和配音两处 —— 两行摘要,收起时一颗标签都不展开。
  expect(container.querySelectorAll("[data-capability-uses-summary]")).toHaveLength(2);
  expect(container.querySelectorAll("[data-capability-uses]")).toHaveLength(0);
  expect(container.querySelector("[data-capability-loading]")).toBeNull();
  expect(container.querySelector("[data-capability-skeleton-group]")).toBeNull();
});

/**
 * 维护者原话:「能力提供方这个页面 UI 非常差劲 —— 排版很乱让人无从下手」。截图里七项能力一组挨一组,
 * 组间只有一条发丝线,整页读起来是一份长列表,看不出「这是 7 个彼此独立的能力」。
 * 下面几条把这个新排版钉在结构上(一项能力一张卡片 + 标题行写当前选择 + 操作是控件行 + 用在哪收起)。
 */
it("每一项能力是一张卡片:七张卡片各自分区,不再靠组间发丝线", async () => {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  const cards = [...container.querySelectorAll<HTMLElement>("[data-settings-card]")];
  expect(cards).toHaveLength(listed.length);
  for (const card of cards) {
    //: 卡片仍是 `SettingsGroup` 那一节(标题/说明/控件行都在这套零件里),只套上卡片的壳。
    expect(card.getAttribute("data-slot")).toBe("settings-group");
    expect(card.className).toContain("rounded-lg");
    expect(card.className).toContain("border-border");
    expect(card.className).toContain("bg-panel");
    expect(card.querySelector('[data-slot="settings-group-header"]')).not.toBeNull();
    expect(card.querySelector('[data-slot="settings-group-content"]')).not.toBeNull();
  }
  //: 卡片装在**自己的容器**里,不是 `SettingsSectionStack` 的直接孩子 ——
  //: 那条「相邻两节画一条发丝线」的 CSS 因此落不到它们身上。
  const wrapper = cards[0].parentElement!;
  expect(wrapper.hasAttribute("data-capability-cards")).toBe(true);
  expect(wrapper.className.split(/\s+/)).toEqual(expect.arrayContaining(["grid", "gap-4"]));
  expect([...wrapper.children].filter((child) => child.hasAttribute("data-settings-card"))).toHaveLength(listed.length);
});

it("标题行就写着现在用谁:能力名旁边就是当前选择,不用往下找下拉", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  const cardOf = (name: string) => screen.getByText(name).closest('[data-slot="settings-group"]') as HTMLElement;

  //: 降噪没点名,自动用的就是内置那一档。
  const denoise = cardOf("降噪");
  expect(denoise.querySelector('[data-slot="settings-group-title"]')!.textContent).toBe("降噪");
  expect(denoise.querySelector("[data-capability-current]")!.textContent).toBe("内置降噪");
  const denoiseTitleLine = denoise.querySelector('[data-slot="settings-group-title"]')!.parentElement!;
  expect(denoiseTitleLine.textContent).toContain("降噪");
  expect(denoiseTitleLine.textContent).toContain("内置降噪");

  //: 只有一家可用的:标题行直接写是哪一家。
  expect(cardOf("分离人声").querySelector("[data-capability-current]")!.textContent).toBe("Demucs(本机)");

  //: 一家都没有的:写「未指定」,不是一个空格子。
  expect(cardOf("素材外链").querySelector("[data-capability-current]")!.textContent).toBe("capabilityUnset");

  //: 没有默认的能力:说清它是由每个入口点名的,不是「未指定」。
  expect(cardOf("配音").querySelector("[data-capability-current]")!.textContent).toBe("capabilityNoDefaultShort");
});

it("「用哪一家」是控件行的标签:14px 深色,和组说明的灰不同级", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  const denoise = screen.getByText("降噪").closest('[data-slot="settings-group"]') as HTMLElement;
  const label = denoise.querySelector<HTMLElement>("[data-capability-control-label]")!;
  expect(label.className.split(/\s+/)).toEqual(expect.arrayContaining(["text-ui-sm", "font-medium", "text-foreground"]));
  expect(label.className).not.toContain("text-muted-foreground");
  //: 组说明仍是那一档灰;字号/颜色/字重三者里至少两项和控件标签分开。
  const description = denoise.querySelector<HTMLElement>('[data-slot="settings-group-description"]')!;
  expect(description.className).toContain("text-muted-foreground");
  expect(description.className).not.toContain("text-foreground");
  expect(label.className).toContain("text-ui-sm");
  expect(description.className).toContain("text-ui-sm");
  expect(label.className).toContain("font-medium");
  expect(description.className).not.toContain("font-medium");
});

it("「去插件市场找」统一钉在卡片右上:每一张的同一格,不在说明下面", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  const cards = [...document.querySelectorAll<HTMLElement>("[data-settings-card]")];
  expect(cards).toHaveLength(listed.length);
  for (const card of cards) {
    const header = card.querySelector<HTMLElement>('[data-slot="settings-group-header"]')!;
    //: 抬头是两列:左边标题/说明,右边动作 —— 动作不会因为说明长就折到下一行。
    expect(header.className).toContain("grid-cols-[minmax(0,1fr)_auto]");
    const actions = card.querySelector<HTMLElement>('[data-slot="settings-group-actions"]')!;
    expect(actions.parentElement).toBe(header);
    expect(within(actions).getByRole("button", { name: /capabilityFindPlugins/ })).toBeTruthy();
    //: 动作不是说明下面那一行的一部分:它在抬头里,和标题同一格的高度起点。
    expect(actions.closest('[data-slot="settings-group-content"]')).toBeNull();
  }
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

it("后端一项能力都没登记:给一句空态,不是一片空白", async () => {
  //: `GET /api/settings/capabilities` 空 = 后端**一项走挑法的能力都没登记**(domain/capabilities.registered()),
  //: 不是"某项能力还没有连接" —— 后者在组里已经有一句 capabilityNone。空表是这一版没登记,先说清再给下一步。
  listCapabilityChoices.mockResolvedValue([]);
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("capabilityEmpty")).toBeInTheDocument();
  expect(screen.getByText("capabilityEmptyNote")).toBeInTheDocument();
  expect(container.querySelector('[data-slot="settings-empty"]')).not.toBeNull();
  expect(container.querySelector("[data-capability-loading]")).toBeNull();
});

it("一项能力一组;文档解析不定就是本地解析,外链一家都没有时说去建一个", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("文档解析")).toBeTruthy());
  expect(screen.getByText("素材外链")).toBeTruthy();
  expect(screen.getAllByText("本地解析").length).toBeGreaterThan(0);
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
  //: 是哪一家写在标题行(「分离人声 · Demucs(本机)」),控件行不摆一个灰掉的下拉,
  //: 只用一句话说清为什么只有它。
  expect(group.querySelector("[data-capability-current]")?.textContent).toBe("Demucs(本机)");
  expect(group.querySelector('[data-slot="settings-item-control"]')).toBeNull();
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

it("「用在哪」默认收成一行摘要,点开才列出接口给的那几处;接口没给就不画这一行", async () => {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("降噪")).toBeTruthy());
  const denoise = screen.getByText("降噪").closest('[data-slot="settings-group"]') as HTMLElement;
  //: 收起时不挂载那一排标签 —— 它不再和「用哪一家」争注意力。
  expect(denoise.querySelectorAll("[data-capability-uses]")).toHaveLength(0);
  const summary = denoise.querySelector<HTMLElement>("[data-capability-uses-summary]")!;
  expect(summary.dataset.capabilityUseCount).toBe("3");
  const trigger = within(summary).getByRole("button");
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(trigger.textContent).toContain("capabilityUsesCount");

  //: 点开:照接口给的逐条列,数据一个不多一个不少。
  fireEvent.click(trigger);
  await waitFor(() => expect(denoise.querySelectorAll("[data-capability-uses]")).toHaveLength(1));
  const lists = denoise.querySelectorAll("[data-capability-uses]");
  expect([...lists[0].querySelectorAll<HTMLElement>("[data-capability-use]")].map((one) => one.dataset.capabilityUse)).toEqual(["app", "workflow", "agent"]);
  expect(lists[0].textContent).toContain("工作流节点「降噪」的「引擎」");
  expect(trigger.getAttribute("aria-expanded")).toBe("true");

  //: 再收起:标签又回到底下,摘要仍是一行。
  fireEvent.click(trigger);
  await waitFor(() => expect(denoise.querySelectorAll("[data-capability-uses]")).toHaveLength(0));

  //: 分离人声、文档解析、外链的样例数据没给 used_by —— 那几组不画这一行。
  expect(container.querySelectorAll("[data-capability-uses-summary]")).toHaveLength(2);
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
  //: 配音那一处用法也收在摘要里,点开才列。
  const summary = group.querySelector<HTMLElement>("[data-capability-uses-summary]")!;
  expect(summary.dataset.capabilityUseCount).toBe("1");
  fireEvent.click(within(summary).getByRole("button"));
  await waitFor(() => expect(group.querySelectorAll("[data-capability-use]")).toHaveLength(1));
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

it("有几家、却一家都没配好时按能力说:转写不提「桶和密钥」,素材外链才提(体检 UM-06)", async () => {
  //: 全新部署上转写的本机引擎都没装:此前第一句是「还没有配好的存储 —— 去「插件」页填上桶和密钥」,把想转写的人指去了对象存储。
  listCapabilityChoices.mockImplementation(async () => [
    { capability: "transcribe", label: "转写", description: "听写成字", current: null, automatic: null,
      options: [
        { id: "builtin:funasr", name: "FunASR", builtin: true, missing: ["运行环境"] },
        { id: "builtin:whisperx", name: "WhisperX", builtin: true, missing: ["运行环境"] },
      ] },
    { capability: "public_url", label: "素材外链", description: "换直链", current: null, automatic: null,
      options: [{ id: "oss", name: "阿里云 OSS", builtin: false, missing: ["bucket"] }] },
  ]);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilityProvidersSection />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("转写")).toBeTruthy());
  const transcribe = screen.getByText("转写").closest('[data-slot="settings-group"]') as HTMLElement;
  expect(transcribe.textContent).toContain("capabilityNoneReady");
  expect(transcribe.textContent).not.toContain("assetLinkNoneReady");
  expect(within(transcribe).getAllByText("capabilityBuiltinUnready")).toHaveLength(2);
  const link = screen.getByText("素材外链").closest('[data-slot="settings-group"]') as HTMLElement;
  expect(link.textContent).toContain("assetLinkNoneReady");
});
