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
vi.mock("@/features/settings/AppearanceSection", () => ({
  AppearanceSection: () => null,
  BackgroundSection: () => null,
  CustomCssSection: () => null,
}));
vi.mock("@/features/settings/AutopilotRulesSection", () => ({ AutopilotRulesSection: () => null }));
vi.mock("@/features/settings/BackendSection", () => ({ BackendSection: () => null }));
vi.mock("@/features/settings/BuiltinTtsSection", () => ({ BuiltinTtsSection: () => null }));
vi.mock("@/features/settings/FeishuSection", () => ({ FeishuSection: () => null }));
vi.mock("@/features/settings/ProviderDefaultsSection", () => ({ ProviderDefaultsSection: () => null }));
vi.mock("@/features/settings/ProviderProfilesSection", () => ({ ProviderProfilesSection: () => null }));
vi.mock("@/features/settings/TeamSection", () => ({ TeamSection: () => null }));
vi.mock("@/features/settings/VoiceLibrarySection", () => ({ VoiceLibrarySection: () => null }));

import { ALL_SECTIONS, SETTINGS_GROUPS, resolveSettingsLink } from "./settingsSections";

const groupOf = (id: string) => SETTINGS_GROUPS.find((group) => group.sections.some((one) => one.id === id))?.title;

describe("设置页结构", () => {
  it("每一页只出现一次", () => {
    const ids = ALL_SECTIONS.map((one) => one.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("只有部署管理员写得了的几页不在设置里", () => {
    //: 成本规则、出站代理与重试、安装源、数据与诊断,以及转写、人声分离、降噪三页本机引擎的安装,
    //: 后端都只许部署管理员写(ensure_deployment_admin)。摆在设置页时普通成员看得到表单、一点就 403 ——
    //: 它们在管理页(features/admin/AdminView,本机引擎在「引擎」tab)。
    const ids = ALL_SECTIONS.map((one) => one.id);
    for (const gone of ["provider-pricing", "network", "ai-runtime", "install-source", "data", "transcribe", "separation", "denoise"]) {
      expect(ids, gone).not.toContain(gone);
    }
  });

  it("配音那一页剩下的是这个工作区的音色库,归「个人与工作区」", () => {
    //: 声音克隆的引擎、解释器、下载源存在整台部署共用的一行配置里,只许部署管理员写 —— 搬去了管理页。
    //: 音色库是工作区的东西,留在这里;不再有「本机引擎」这一组(它剩下的只有安装)。
    expect(groupOf("dubbing")).toBe("studioSettingsPersonal");
    expect(SETTINGS_GROUPS.map((group) => group.title)).not.toContain("studioSettingsLocalEngines");
  });

  it("云端供应商组里只有云端连接", () => {
    //: 语音对话是智能体的说话方式,内置配音与音色库不是云端连接 —— 都不该出现在「AI 供应商」下面。
    expect(groupOf("agent-voice")).toBe("studioSettingsAgent");
    expect(groupOf("dubbing")).not.toBe("studioSettingsProviders");
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
    //: AI 生成 → 音频里「克隆要先有音色」的「管理音色」发的就是它。
    ["dubbing", "dubbing"],
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
    //: 挪去管理页的那几页也一样:不在设置里给一个「最接近的」替身。引擎没装的提示走的是
    //: gotoAdmin("engines")(管理员)或一句说明(成员),不再发这几条设置深链。
    for (const moved of ["provider-pricing", "transcribe", "separation", "denoise"]) {
      expect(resolveSettingsLink(moved), moved).toBeNull();
    }
  });
});
