import React from "react";
import {
  AudioLines,
  Brain,
  Link2,
  ImageIcon,
  MessageSquare,
  Palette,
  Server,
  ShieldCheck,
  Sparkles,
  Speech,
  UserRound,
  Users,
  Video,
} from "lucide-react";

import type { Workspace } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { AccountSection } from "@/features/settings/AccountSection";
import { AgentMemorySection } from "@/features/settings/AgentMemorySection";
import { AgentSkillsSection } from "@/features/settings/AgentSkillsSection";
import { AgentVoiceSection } from "@/features/settings/AgentVoiceSection";
import { AppearanceSection, BackgroundSection, CustomCssSection } from "@/features/settings/AppearanceSection";
import { AutopilotRulesSection } from "@/features/settings/AutopilotRulesSection";
import { BackendSection } from "@/features/settings/BackendSection";
import { BuiltinTtsSection } from "@/features/settings/BuiltinTtsSection";
import { FeishuSection } from "@/features/settings/FeishuSection";
import { ProviderDefaultsSection } from "@/features/settings/ProviderDefaultsSection";
import { CapabilityProvidersSection } from "@/features/settings/CapabilityProvidersSection";
import { ProviderProfilesSection } from "@/features/settings/ProviderProfilesSection";
import { TeamSection } from "@/features/settings/TeamSection";
import { VoiceLibrarySection } from "@/features/settings/VoiceLibrarySection";

/**
 * 设置页的**唯一一份结构声明**:有哪些组、每组有哪些页、每页渲染什么。
 *
 * 此前这件事分在四处:导航数组、分组 id 列表、`SECTION_IDS`、一长串 `section === "…" &&`。
 * 加一页要改四处,漏一处的后果是静默的 —— 页面在、导航里没有;或者导航里有、深链跳不进去。
 * 现在导航、内容、搜索、深链解析都从这一份推出来。
 *
 * **分组按用户找它时在想什么,不按它在代码里挨着谁。** 反例就是上一版:人声分离因为"也是
 * 本机跑的音频模型"被放进「转写模型」;pip 镜像因为"克隆先有了它"只出现在声音克隆表单里,
 * 而转写和分离装依赖时读的是同一份;「语音与服务」组里装着飞书机器人和数据诊断。
 *
 * **只放每个成员自己能改的东西。** 后端只许部署管理员写的(成本规则、出站代理与重试、数据与诊断,
 * 以及本机引擎 —— 转写、声音克隆、人声分离、降噪的安装与下载源、pip 下载源)在管理页
 * (features/admin/AdminView):摆在这里时普通成员看得到表单、一点就 403。本机引擎因此不再是
 * 这里的一组:转写、人声分离、降噪三页除了安装什么都没有,整页搬走;配音那一页剩下的音色库
 * 是这个工作区的东西,留下,归「个人与工作区」。
 */

export type SettingsContext = {
  workspace: Workspace;
  t: (key: MessageKey) => string;
  /** 深链带来的"聚焦哪个能力"(`providers:image`),只有供应商页读。 */
  focusCapability: string | null;
};

export type SettingsSection = {
  id: string;
  label: MessageKey;
  icon: React.ReactNode;
  /** 这一页配置的是哪几种供应商能力 —— `providers:<能力>` 深链据此落到它。 */
  capabilities?: readonly string[];
  render: (ctx: SettingsContext) => React.ReactNode;
};

export type SettingsGroup = { title: MessageKey; sections: readonly SettingsSection[] };

/** 「某种能力的供应商」一页的固定形状:默认模型在上,连接列表在下。 */
function providerPage(capability: string, title: MessageKey, description: MessageKey) {
  return ({ focusCapability, t }: SettingsContext) => (
    <>
      <ProviderDefaultsSection capabilities={[capability]} focusCapability={focusCapability} />
      <ProviderProfilesSection capability={capability} title={t(title)} description={t(description)} />
    </>
  );
}

export const SETTINGS_GROUPS: readonly SettingsGroup[] = [
  {
    title: "studioSettingsPersonal",
    sections: [
      { id: "account", label: "settingsAccount", icon: <UserRound size={14} />, render: () => <AccountSection /> },
      {
        id: "team",
        label: "teamTitle",
        icon: <Users size={14} />,
        render: ({ workspace }) => <TeamSection workspace={workspace} />,
      },
      {
        id: "appearance",
        label: "settingsAppearance",
        icon: <Palette size={14} />,
        render: () => (
          <>
            <AppearanceSection />
            <BackgroundSection />
            <CustomCssSection />
          </>
        ),
      },
      {
        // 这个工作区的音色库,加上不用连接就能配音的几个内置引擎现在能不能用(只读)。
        // 本地克隆引擎怎么装、用哪个解释器和下载源是部署级的,在管理页「引擎」。
        id: "dubbing",
        label: "settingsDubbingTitle",
        icon: <AudioLines size={14} />,
        render: ({ workspace }) => (
          <>
            <BuiltinTtsSection />
            <VoiceLibrarySection workspace={workspace} />
          </>
        ),
      },
    ],
  },
  {
    // 「用哪家的哪个模型」—— 全是云端连接。花多少钱(成本规则)只有部署管理员写得了,在管理页。
    title: "studioSettingsProviders",
    sections: [
      {
        id: "provider-chat",
        label: "providerChatTitle",
        icon: <MessageSquare size={14} />,
        capabilities: ["chat"],
        render: providerPage("chat", "providerChatTitle", "providerChatDesc"),
      },
      {
        id: "provider-image",
        label: "providerImageTitle",
        icon: <ImageIcon size={14} />,
        capabilities: ["image"],
        render: providerPage("image", "providerImageTitle", "providerImageDesc"),
      },
      {
        id: "provider-video",
        label: "providerVideoTitle",
        icon: <Video size={14} />,
        capabilities: ["video"],
        render: providerPage("video", "providerVideoTitle", "providerVideoDesc"),
      },
      {
        // **只放云端的配音与播客连接。** 内置配音引擎与音色库在「个人与工作区 → 配音与音色」,
        // 本地克隆引擎的安装在管理页;语音对话是智能体的一种说话方式,归「智能体」。
        id: "provider-audio",
        label: "providerAudioTitle",
        icon: <AudioLines size={14} />,
        capabilities: ["tts", "podcast", "audio"],
        render: ({ t, focusCapability }) => (
          <>
            <ProviderProfilesSection capability="tts" title={t("providerTtsTitle")} description={t("providerTtsDesc")} />
            <ProviderProfilesSection
              capability="podcast"
              title={t("providerPodcastTitle")}
              description={t("providerPodcastDesc")}
            />
            {/* 音乐与音效是**生成**(和图像、视频同一条管线,ADR 0022),所以它有自己的默认模型。 */}
            <ProviderDefaultsSection capabilities={["audio"]} focusCapability={focusCapability} />
            <ProviderProfilesSection
              capability="audio"
              title={t("providerMusicTitle")}
              description={t("providerMusicDesc")}
            />
          </>
        ),
      },
    ],
  },
  {
    // 「智能体怎么工作」—— 不是某种能力的配置。
    title: "studioSettingsAgent",
    sections: [
      {
        id: "agent-voice",
        label: "agentVoiceTitle",
        icon: <Speech size={14} />,
        render: ({ workspace }) => <AgentVoiceSection workspaceId={workspace.id} />,
      },
      {
        id: "agent-memory",
        label: "agentMemoryTitle",
        icon: <Brain size={14} />,
        render: ({ workspace }) => <AgentMemorySection workspace={workspace} />,
      },
      {
        // 技能(ADR 0040):做某一类事的方法,用到时才读。和记忆挨着 —— 两者常被问「有什么不一样」,
        // 页首的说明各自讲清楚:记忆每轮都在、必须短;技能只在做那件事时才读。
        id: "agent-skills",
        label: "agentSkillsTitle",
        icon: <Sparkles size={14} />,
        render: ({ workspace }) => <AgentSkillsSection workspace={workspace} />,
      },
      {
        id: "agent-autopilot",
        label: "autopilotTitle",
        icon: <ShieldCheck size={14} />,
        render: ({ workspace }) => <AutopilotRulesSection workspace={workspace} />,
      },
    ],
  },
  {
    title: "studioSettingsSystem",
    sections: [
      {
        id: "feishu",
        label: "feishuTitle",
        icon: <MessageSquare size={14} />,
        render: ({ workspace }) => <FeishuSection workspace={workspace} />,
      },
      {
        // **自己一页,不挂在某一种模型下面。** 宿主的几项能力(素材外链、文档解析……)各用哪一家,回答的是
        // 「这件事交给哪一家做」—— 按后端的能力表列,多一项能力这里不用改(ADR 0031 §5)。
        id: "capabilities",
        label: "capabilityProvidersTitle",
        icon: <Link2 size={14} />,
        render: () => <CapabilityProvidersSection />,
      },
      {
        id: "backend",
        label: "settingsBackend",
        icon: <Server size={14} />,
        render: ({ workspace }) => <BackendSection workspace={workspace} />,
      },
    ],
  },
];

export const ALL_SECTIONS: readonly SettingsSection[] = SETTINGS_GROUPS.flatMap((group) => group.sections);

export const DEFAULT_SECTION_ID = ALL_SECTIONS[0].id;

/**
 * 深链(`mosael:open-settings` 的 detail)→ 哪一页 + 聚焦哪个能力。
 *
 * 三种写法:`<页 id>`、`providers`(第一个供应商页)、`providers:<能力>`(配置那种能力的那一页)。
 * 能力到页的映射**不另立一张表**,读的是每页自己声明的 `capabilities`。认不出来返回 null,
 * 调用方原地不动 —— 跳到一个无关的页比不跳更让人摸不着头脑。
 */
export function resolveSettingsLink(detail: string): { id: string; focus: string | null } | null {
  const [head, focus = ""] = String(detail || "").split(":");
  if (head === "providers") {
    const target = focus
      ? ALL_SECTIONS.find((section) => section.capabilities?.includes(focus))
      : ALL_SECTIONS.find((section) => section.capabilities?.length);
    return target ? { id: target.id, focus: focus || null } : null;
  }
  const direct = ALL_SECTIONS.find((section) => section.id === head);
  return direct ? { id: direct.id, focus: focus || null } : null;
}
