import React from "react";
import {
  AudioLines,
  AudioWaveform,
  Brain,
  Link2,
  ImageIcon,
  MessageSquare,
  Mic,
  Palette,
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
import { AppearanceSection, BackgroundSection, CustomCssSection } from "@/features/settings/AppearanceSection";
import { AsrModelsSection } from "@/features/settings/AsrModelsSection";
import { AutopilotRulesSection } from "@/features/settings/AutopilotRulesSection";
import { BackendSection } from "@/features/settings/BackendSection";
import { BuiltinTtsSection } from "@/features/settings/BuiltinTtsSection";
import { DenoiseEnginesSection } from "@/features/settings/DenoiseEnginesSection";
import { FeishuSection } from "@/features/settings/FeishuSection";
import { ProviderDefaultsSection } from "@/features/settings/ProviderDefaultsSection";
import { CapabilityProvidersSection } from "@/features/settings/CapabilityProvidersSection";
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
 *
 * **只放每个成员自己能改的东西。** 后端只许部署管理员写的(成本规则、出站代理与重试、安装源、
 * 数据与诊断)在管理页(features/admin/AdminView):摆在这里时普通成员看得到表单、一保存就 403。
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
        // **只放云端的配音与播客连接。** 内置配音引擎、声音克隆是本机的,归「本机引擎」;
        // 语音对话是智能体的一种说话方式,归「智能体」。
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
        id: "agent-autopilot",
        label: "autopilotTitle",
        icon: <ShieldCheck size={14} />,
        render: ({ workspace }) => <AutopilotRulesSection workspace={workspace} />,
      },
    ],
  },
  {
    // 「装在这台机器上跑的模型」,每种能力一页。三个引擎共用的 pip 安装源是部署级的设置
    // (只有部署管理员写得了),在管理页的「部署设置」里。
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
