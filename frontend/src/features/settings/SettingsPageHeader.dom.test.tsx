/** @vitest-environment jsdom */
/**
 * 设置页**没有独立的页头**:页头就是页里第一个 `SettingsGroup` 的标题。
 *
 * `SettingsView` 只渲染 `current.render(ctx)`(SettingsView.tsx:123-125),一个页头元素都不画;
 * 而 `SettingsSectionStack` 的 CSS 把第一个组的标题抬到 2xl、说明抬到 ui-md
 * (components/settings/settings-layout.tsx:445,那条断言在 ui.dom.test.tsx)。也就是说
 * 「这一页叫什么、这一页是干什么的」在界面上完全由**页里第一个组**回答。
 *
 * 于是这里逐页钉住:第一个组的标题 == 左侧导航里那一页的名字(`section.label`)。
 * 页头被某个子组顶掉的页(供应商四页曾经是「默认模型」;配音曾经是「内置配音引擎」,没有内置
 * 引擎时还会变成「音色库」;能力提供方曾经是后端给的能力名)都在这条上现形。
 *
 * **这条测试能成立的支点,是页头写在声明层**(`settingsSections.tsx`)。各页组件在这里全部
 * mock 成 `() => null`,留下来的组只可能来自那份结构声明自己 —— 所以页头若写在组件内部
 * (比如 `CapabilityProvidersSection` 的早返回之后),这条测试测不到它,**而且它在加载中
 * (`CapabilityGroupsSkeleton`)与出错(`PageLoadError`)时会跟着消失**。
 *
 * 反过来,声明层只写「这一页渲染哪个组件」的那些页,页头在组件里,这里一个组也看不到 ——
 * 它们进 `HEADER_IN_COMPONENT`,断言变成「声明层不许再画一个组」:页头只能有一个来源,
 * 两处都画的话页里就有两个「第一个组」。
 */
import React from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

//: 只要声明层 —— 各页组件是桩,免得为了读一张表去拉整个界面(同 settingsSections.test.ts 那套)。
vi.mock("@/features/settings/AccountSection", () => ({ AccountSection: () => null }));
vi.mock("@/features/settings/AgentMemorySection", () => ({ AgentMemorySection: () => null }));
vi.mock("@/features/settings/AgentSkillsSection", () => ({ AgentSkillsSection: () => null }));
vi.mock("@/features/settings/AgentVoiceSection", () => ({ AgentVoiceSection: () => null }));
vi.mock("@/features/settings/AppearanceSection", () => ({
  AppearanceSection: () => null,
  BackgroundSection: () => null,
  CustomCssSection: () => null,
}));
vi.mock("@/features/settings/AutopilotRulesSection", () => ({ AutopilotRulesSection: () => null }));
vi.mock("@/features/settings/BackendSection", () => ({ BackendSection: () => null }));
vi.mock("@/features/settings/BuiltinTtsSection", () => ({ BuiltinTtsSection: () => null }));
vi.mock("@/features/settings/CapabilityProvidersSection", () => ({ CapabilityProvidersSection: () => null }));
vi.mock("@/features/settings/FeishuSection", () => ({ FeishuSection: () => null }));
vi.mock("@/features/settings/LocalAppSection", () => ({ LocalAppSection: () => null }));
vi.mock("@/features/settings/ProviderDefaultsSection", () => ({ ProviderDefaultsSection: () => null }));
vi.mock("@/features/settings/ProviderProfilesSection", () => ({ ProviderProfilesSection: () => null }));
vi.mock("@/features/settings/TeamSection", () => ({ TeamSection: () => null }));
vi.mock("@/features/settings/VoiceLibrarySection", () => ({ VoiceLibrarySection: () => null }));

import { messages, type MessageKey } from "@/app/messages";

import { ALL_SECTIONS } from "./settingsSections";

const t = (key: MessageKey) => messages["zh-CN"][key];
//: 声明层的 render 只读得到 `workspace.id`(智能体语音那一页);组件本身是桩,不看这个对象。
const workspace = { id: "w1", name: "W" } as never;

/**
 * 页头由**页面组件自己**画的那几页:声明层只写「这一页渲染哪个组件」,组件里第一个
 * `SettingsGroup` 的标题就是页名。组件在这里是桩,所以它们声明层画不出组。
 *
 * **名单只减不增。** 把哪一页的页头搬进声明层(或者发现它其实该有页头),就把那一行删掉 ——
 * 留着的话它连"两个来源"都拦不住;反过来,新加的页不在这张名单里,就必须在声明层给出页头。
 */
const HEADER_IN_COMPONENT = new Set([
  "account", // AccountSection
  "team", // TeamSection
  "appearance", // AppearanceSection
  "agent-voice", // AgentVoiceSection
  "agent-memory", // AgentMemorySection
  "agent-skills", // AgentSkillsSection
  "agent-autopilot", // AutopilotRulesSection
  "feishu", // FeishuSection
  "backend", // BackendSection
  "local-app", // LocalAppSection
]);

afterEach(cleanup);

it("扫得到全部页面 —— 别变成空转", () => {
  expect(ALL_SECTIONS.length).toBeGreaterThan(10);
});

it("「页头在组件里」那张名单只减不增:里面每一页都还在", () => {
  const ids = new Set(ALL_SECTIONS.map((section) => section.id));
  expect([...HEADER_IN_COMPONENT].filter((id) => !ids.has(id))).toEqual([]);
});

for (const section of ALL_SECTIONS) {
  const inComponent = HEADER_IN_COMPONENT.has(section.id);
  it(`${section.id}:${inComponent ? "页头在组件里,声明层不许再画一个" : "页里第一个组的标题是页名"}`, () => {
    const { container } = render(<>{section.render({ workspace, t, focusCapability: null })}</>);
    const title = container.querySelector('[data-slot="settings-group-title"]');
    if (inComponent) {
      //: 这一页的页头在组件里(组件是桩)。声明层再画一个,页里就会有两个「第一个组」——
      //: 一个抬到 2xl 的页头只能有一个。
      expect(title, `${section.id} 的页头在组件里;声明层又画了一个组`).toBeNull();
      return;
    }
    expect(title?.textContent, `${section.id} 的页头应当是「${t(section.label)}」`).toBe(t(section.label));
  });
}
