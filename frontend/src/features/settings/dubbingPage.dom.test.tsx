/** @vitest-environment jsdom */
/**
 * 设置 →「我的音色」这一页现在只剩一件事:这个工作区的音色库。
 *
 * 此前它叫「配音 + 音色」那种名字(旧页名,见 settingsPageName.test.ts),页里还单独有一组「内置配音引擎」(本地音色克隆 / Qwen3-TTS / Edge 各自一行
 * 「即开即用」)。那一组是**只读的现状说明**,而「这台机器上有哪几个引擎能用」属于「能力提供方 → 配音」
 * 那张卡(默认引擎就在那里选)。所以那一整块删掉,页名改成「我的音色」。
 *
 * 这里钉的是**用户看见的东西**:页头/侧栏叫「我的音色」、页里没有那一组、页说明不再回答「装了没有」。
 * 旧名一个都不留 —— 指路文案里残留旧页名,就是又把人指去一个不存在的地方(上一版 12 处旧节名这么坏的)。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

//: 页面组件在这里全是桩 —— 只留声明层与真正要验的那一块(内置配音引擎那一组**不桩**:
//: 它若还挂在页里,下面第一条就该红)。
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
vi.mock("@/features/settings/CapabilityProvidersSection", () => ({ CapabilityProvidersSection: () => null }));
vi.mock("@/features/settings/FeishuSection", () => ({ FeishuSection: () => null }));
vi.mock("@/features/settings/LocalAppSection", () => ({ LocalAppSection: () => null }));
vi.mock("@/features/settings/ProviderDefaultsSection", () => ({ ProviderDefaultsSection: () => null }));
vi.mock("@/features/settings/ProviderProfilesSection", () => ({ ProviderProfilesSection: () => null }));
vi.mock("@/features/settings/TeamSection", () => ({ TeamSection: () => null }));
vi.mock("@/features/settings/VoiceLibrarySection", () => ({ VoiceLibrarySection: () => null }));
vi.mock("@/app/auth", () => ({ useIsDeploymentAdmin: () => false }));
//: 那一组只读的引擎行读的是 /tts/engines —— 桩成一台什么都没装好的机器。
vi.mock("@/api/client", () => ({ listTtsEngines: async () => [] }));
//: 文案用真表:这几条断言说的是**用户读到的字**,不是键名。
vi.mock("@/app/preferences", async () => {
  const { zhCN } = await import("@/app/messages/zh-CN");
  return { useI18n: () => (key: string) => (zhCN as unknown as Record<string, string>)[key] ?? key };
});

import { messages } from "@/app/messages";
import { zhCN } from "@/app/messages/zh-CN";

import { ALL_SECTIONS } from "./settingsSections";

afterEach(cleanup);

const section = ALL_SECTIONS.find((one) => one.id === "dubbing")!;
const t = (key: keyof typeof zhCN) => zhCN[key];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      {section.render({ workspace: { id: "w1", name: "W" } as never, t: t as never, focusCapability: null })}
    </QueryClientProvider>,
  );
}

it("页里没有「内置配音引擎」那一组了:标题、说明、三条「即开即用」一起走", () => {
  const { container } = renderPage();
  expect(container.textContent).not.toContain("内置配音引擎");
  expect(container.textContent).not.toContain("即开即用");
  //: 只剩一页头 + 这一工作区的音色库(`VoiceLibrarySection` 在这里是桩,它自己那一节另测)。
  expect(container.querySelectorAll('[data-slot="settings-group"]')).toHaveLength(1);
});

it("侧栏与页头都叫「我的音色」,页说明只说这个工作区有哪些音色、怎么建", () => {
  //: 侧栏那一项读的就是 `section.label` —— 页头也从同一个键来(settingsSections 的空组),
  //: 两处不会各写一遍再分叉。
  expect(zhCN[section.label]).toBe("我的音色");
  const { container } = renderPage();
  const title = container.querySelector('[data-slot="settings-group-title"]');
  expect(title?.textContent).toBe("我的音色");
  const description = container.querySelector('[data-slot="settings-group-description"]')?.textContent ?? "";
  expect(description).toContain("这个工作区有哪些音色、怎么建");
  //: 「装了没有」那半句是内置引擎那一组的,跟着一起删了。
  expect(description).not.toContain("装了没有");
  expect(description).not.toContain("内置配音引擎");
  //: 中英同改:两份文案表的键集与页名要一致。
  expect(messages["en-US"][section.label]).toBe("My voices");
});

it("页说明不再把「装了没有」和「有哪些音色」并列:一句话只说后者", () => {
  const description = zhCN.settingsDubbingPageDesc;
  expect(description.split("，").length).toBeLessThanOrEqual(2);
  expect(description).not.toContain("装了没有");
  expect(description).not.toContain("(内置配音引擎)");
});
