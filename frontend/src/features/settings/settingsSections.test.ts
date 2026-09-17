/**
 * 设置页的结构是**一份声明**,这里钉住它说的是真话。
 *
 * 上一版的毛病都是"东西放在它不属于的地方":人声分离因为"也是本机跑的音频模型"被放进「转写模型」;
 * pip 镜像只出现在声音克隆表单里,而转写和分离装依赖时读的是同一份;「语音与服务」组里装着飞书
 * 机器人和数据诊断。判据不能是"某个组件在某个文件里",而是**用户按意图去找时找得到**。
 */
import { describe, expect, it, vi } from "vitest";

// 各页组件本身不在这里渲染 —— 只要声明。把重的依赖桩掉,免得为了读一张表去拉整个界面。
vi.mock("@/features/settings/AccountSection", () => ({ AccountSection: () => null }));
vi.mock("@/features/settings/AgentMemorySection", () => ({ AgentMemorySection: () => null }));
vi.mock("@/features/settings/AgentVoiceSection", () => ({ AgentVoiceSection: () => null }));
vi.mock("@/features/settings/AiRuntimeSection", () => ({ AiRuntimeSection: () => null }));
vi.mock("@/features/settings/AppearanceSection", () => ({
  AppearanceSection: () => null,
  BackgroundSection: () => null,
  CustomCssSection: () => null,
}));
vi.mock("@/features/settings/AsrModelsSection", () => ({ AsrModelsSection: () => null }));
vi.mock("@/features/settings/AutopilotRulesSection", () => ({ AutopilotRulesSection: () => null }));
vi.mock("@/features/settings/BackendSection", () => ({ BackendSection: () => null, ProxySection: () => null }));
vi.mock("@/features/settings/BuiltinTtsSection", () => ({ BuiltinTtsSection: () => null }));
vi.mock("@/features/settings/DataDiagnosticsSection", () => ({ DataDiagnosticsSection: () => null }));
vi.mock("@/features/settings/FeishuSection", () => ({ FeishuSection: () => null }));
vi.mock("@/features/settings/InstallSourceSection", () => ({ InstallSourceSection: () => null }));
vi.mock("@/features/settings/ProviderDefaultsSection", () => ({ ProviderDefaultsSection: () => null }));
vi.mock("@/features/settings/ProviderPricingSection", () => ({ ProviderPricingSection: () => null }));
vi.mock("@/features/settings/ProviderProfilesSection", () => ({ ProviderProfilesSection: () => null }));
vi.mock("@/features/settings/SeparationEnginesSection", () => ({ SeparationEnginesSection: () => null }));
vi.mock("@/features/settings/TeamSection", () => ({ TeamSection: () => null }));
vi.mock("@/features/settings/VoiceCloneSection", () => ({ VoiceCloneSection: () => null }));
vi.mock("@/features/settings/VoiceLibrarySection", () => ({ VoiceLibrarySection: () => null }));

import { ALL_SECTIONS, SETTINGS_GROUPS, resolveSettingsLink } from "./settingsSections";

const groupOf = (id: string) => SETTINGS_GROUPS.find((group) => group.sections.some((one) => one.id === id))?.title;

describe("设置页结构", () => {
  it("每一页只出现一次", () => {
    const ids = ALL_SECTIONS.map((one) => one.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("人声分离有自己的一页,不和转写挤在一起", () => {
    //: 它们唯一的共同点是"在这台机器上跑",那是实现上的共性,不是用户找它时想的东西。
    expect(ALL_SECTIONS.some((one) => one.id === "separation")).toBe(true);
    expect(ALL_SECTIONS.find((one) => one.id === "separation")).not.toBe(
      ALL_SECTIONS.find((one) => one.id === "transcribe"),
    );
  });

  it("安装源是独立的一页,和三个本机引擎同组", () => {
    //: 它被转写、克隆、分离三个引擎共用 —— 挂在哪一个名下都是错的说法。
    const engines = ["transcribe", "dubbing", "separation", "install-source"];
    const groups = new Set(engines.map(groupOf));
    expect(groups.size).toBe(1);
    expect([...groups][0]).toBe("studioSettingsLocalEngines");
  });

  it("代理和重试在同一页", () => {
    //: 两者回答的是同一个问题:所有 AI 调用怎么出去。此前重试独占一页,代理挂在「本地后端」下面。
    expect(ALL_SECTIONS.some((one) => one.id === "network")).toBe(true);
    expect(ALL_SECTIONS.some((one) => one.id === "ai-runtime")).toBe(false);
  });

  it("云端供应商组里只有云端连接", () => {
    //: 语音对话是智能体的说话方式,内置配音与克隆是本机的 —— 都不该出现在「AI 供应商」下面。
    expect(groupOf("agent-voice")).toBe("studioSettingsAgent");
    expect(groupOf("dubbing")).toBe("studioSettingsLocalEngines");
  });
});

describe("深链", () => {
  it.each([
    ["providers", "provider-chat"],
    ["providers:chat", "provider-chat"],
    ["providers:image", "provider-image"],
    ["providers:video", "provider-video"],
    ["providers:tts", "provider-audio"],
    ["providers:podcast", "provider-audio"],
    ["provider-pricing", "provider-pricing"],
    ["separation", "separation"],
  ])("%s 落到 %s", (link, id) => {
    //: 这几个是代码里实际发出去的深链 —— 页挪了位置,它们必须还落得到。
    expect(resolveSettingsLink(link)?.id).toBe(id);
  });

  it("供应商深链带着要聚焦的能力", () => {
    expect(resolveSettingsLink("providers:image")?.focus).toBe("image");
  });

  it("认不出来的原地不动,不瞎跳", () => {
    //: 跳到一个无关的页比不跳更让人摸不着头脑。
    expect(resolveSettingsLink("没有这一页")).toBeNull();
    expect(resolveSettingsLink("providers:没有这种能力")).toBeNull();
  });
});
