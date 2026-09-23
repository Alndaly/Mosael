import React from "react";
import {
  AudioLines,
  AudioWaveform,
  Brain,
  Database,
  Download,
  Globe,
  ImageIcon,
  MessageSquare,
  Mic,
  Palette,
  ReceiptText,
  Scissors,
  Server,
  ShieldCheck,
  Speech,
  UserRound,
  Users,
  Video,
} from "lucide-react";

import type { Workspace } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { AccountSection } from "@/features/settings/AccountSection";
import { AgentMemorySection } from "@/features/settings/AgentMemorySection";
import { AgentVoiceSection } from "@/features/settings/AgentVoiceSection";
import { AiRuntimeSection } from "@/features/settings/AiRuntimeSection";
import { AppearanceSection, BackgroundSection, CustomCssSection } from "@/features/settings/AppearanceSection";
import { AsrModelsSection } from "@/features/settings/AsrModelsSection";
import { AutopilotRulesSection } from "@/features/settings/AutopilotRulesSection";
import { BackendSection, ProxySection } from "@/features/settings/BackendSection";
import { BuiltinTtsSection } from "@/features/settings/BuiltinTtsSection";
import { DataDiagnosticsSection } from "@/features/settings/DataDiagnosticsSection";
import { DenoiseEnginesSection } from "@/features/settings/DenoiseEnginesSection";
import { FeishuSection } from "@/features/settings/FeishuSection";
import { InstallSourceSection } from "@/features/settings/InstallSourceSection";
import { ProviderDefaultsSection } from "@/features/settings/ProviderDefaultsSection";
import { AssetLinkStorageSection } from "@/features/settings/AssetLinkStorageSection";
import { ProviderPricingSection } from "@/features/settings/ProviderPricingSection";
import { ProviderProfilesSection } from "@/features/settings/ProviderProfilesSection";
import { SeparationEnginesSection } from "@/features/settings/SeparationEnginesSection";
import { TeamSection } from "@/features/settings/TeamSection";
import { VoiceCloneSection } from "@/features/settings/VoiceCloneSection";
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
    ],
  },
  {
    // 「用哪家的哪个模型、花多少钱」—— 全是云端连接。
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
        render: (ctx) => (
          <>
            {providerPage("video", "providerVideoTitle", "providerVideoDesc")(ctx)}
            {/* 只收链接的输入(Seedance 的参考视频)用哪一家存储换直链 —— 个人选择,和默认模型同类。 */}
            <AssetLinkStorageSection />
          </>
        ),
      },
      {
        // **只放云端的配音与播客连接。** 内置配音引擎、声音克隆是本机的,归「本机引擎」;
        // 语音对话是智能体的一种说话方式,归「智能体」。
        id: "provider-audio",
        label: "providerAudioTitle",
        icon: <AudioLines size={14} />,
        capabilities: ["tts", "podcast", "audio"],
        render: ({ t }) => (
          <>
            <ProviderProfilesSection capability="tts" title={t("providerTtsTitle")} description={t("providerTtsDesc")} />
            <ProviderProfilesSection
              capability="podcast"
              title={t("providerPodcastTitle")}
              description={t("providerPodcastDesc")}
            />
          </>
        ),
      },
      {
        id: "provider-pricing",
        label: "providerPricingTitle",
        icon: <ReceiptText size={14} />,
        render: ({ workspace }) => <ProviderPricingSection workspace={workspace} />,
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
        id: "agent-autopilot",
        label: "autopilotTitle",
        icon: <ShieldCheck size={14} />,
        render: ({ workspace }) => <AutopilotRulesSection workspace={workspace} />,
      },
    ],
  },
  {
    // 「装在这台机器上跑的模型」。每种能力一页,共用的 pip 安装源单独一页 ——
    // 它被转写、克隆、分离三个引擎读,挂在哪一个名下都是错的说法。
    title: "studioSettingsLocalEngines",
    sections: [
      { id: "transcribe", label: "settingsTranscribeTitle", icon: <Mic size={14} />, render: () => <AsrModelsSection /> },
      {
        id: "dubbing",
        label: "settingsDubbingTitle",
        icon: <AudioLines size={14} />,
        render: ({ workspace }) => (
          <>
            <BuiltinTtsSection />
            <VoiceCloneSection />
            <VoiceLibrarySection workspace={workspace} />
          </>
        ),
      },
      {
        id: "separation",
        label: "separationTitle",
        icon: <Scissors size={14} />,
        render: () => <SeparationEnginesSection />,
      },
      {
        id: "denoise",
        label: "denoiseEnginesTitle",
        icon: <AudioWaveform size={14} />,
        render: () => <DenoiseEnginesSection />,
      },
      {
        id: "install-source",
        label: "installSourceTitle",
        icon: <Download size={14} />,
        render: () => <InstallSourceSection />,
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
        // 出站代理 + 失败重试:回答的是同一个问题 —— 所有 AI 调用怎么出去。
        id: "network",
        label: "settingsNetworkTitle",
        icon: <Globe size={14} />,
        render: () => (
          <>
            <ProxySection />
            <AiRuntimeSection />
          </>
        ),
      },
      {
        id: "backend",
        label: "settingsBackend",
        icon: <Server size={14} />,
        render: ({ workspace }) => <BackendSection workspace={workspace} />,
      },
      {
        id: "data",
        label: "dataDiagnosticsTitle",
        icon: <Database size={14} />,
        render: () => <DataDiagnosticsSection />,
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
