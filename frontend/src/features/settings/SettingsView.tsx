import React from "react";
import {
  AudioLines,
  Brain,
  ImageIcon,
  MessageSquare,
  Mic,
  Palette,
  ReceiptText,
  RefreshCw,
  Server,
  ShieldCheck,
  UserRound,
  Users,
  Video,
} from "lucide-react";

import type { Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";
import { COMPACT_SIDEBAR_BOUNDS, useResizableSidebar } from "@/lib/useResizableSidebar";
import { AccountSection } from "@/features/settings/AccountSection";
import { AgentMemorySection } from "@/features/settings/AgentMemorySection";
import { AiRuntimeSection } from "@/features/settings/AiRuntimeSection";
import { AppearanceSection, BackgroundSection, CustomCssSection } from "@/features/settings/AppearanceSection";
import { AsrModelsSection } from "@/features/settings/AsrModelsSection";
import { AutopilotRulesSection } from "@/features/settings/AutopilotRulesSection";
import { BackendSection } from "@/features/settings/BackendSection";
import { BuiltinTtsSection } from "@/features/settings/BuiltinTtsSection";
import { FeishuSection } from "@/features/settings/FeishuSection";
import { ProviderDefaultsSection } from "@/features/settings/ProviderDefaultsSection";
import { ProviderPricingSection } from "@/features/settings/ProviderPricingSection";
import { ProviderProfilesSection } from "@/features/settings/ProviderProfilesSection";
import { TeamSection } from "@/features/settings/TeamSection";
import { SettingsSectionStack } from "@/features/settings/ui";
import { VoiceCloneSection } from "@/features/settings/VoiceCloneSection";
import { VoiceLibrarySection } from "@/features/settings/VoiceLibrarySection";

type SectionId =
  | "account"
  | "team"
  | "appearance"
  | "provider-chat"
  | "provider-image"
  | "provider-video"
  | "provider-audio"
  | "provider-pricing"
  | "ai-runtime"
  | "agent-memory"
  | "agent-autopilot"
  | "transcribe"
  | "voice"
  | "feishu"
  | "backend";

const SECTION_IDS: SectionId[] = [
  "account",
  "team",
  "appearance",
  "provider-chat",
  "provider-image",
  "provider-video",
  "provider-audio",
  "provider-pricing",
  "ai-runtime",
  "agent-memory",
  "agent-autopilot",
  "transcribe",
  "voice",
  "feishu",
  "backend",
];

const SECTION_STORAGE_KEY = "mosael:settings-section";

export function SettingsView({ workspace }: { workspace: Workspace }) {
  // 导航项是短标签,不是长内容 —— 用紧凑档,宽度让给右边真正在配的东西。
  const sidebar = useResizableSidebar("settings", COMPACT_SIDEBAR_BOUNDS);
  const t = useI18n();
  const [focusProviderCapability, setFocusProviderCapability] = React.useState<string | null>(null);
  const [section, setSectionState] = React.useState<SectionId>(() => {
    const saved = localStorage.getItem(SECTION_STORAGE_KEY);
    return saved && SECTION_IDS.includes(saved as SectionId) ? (saved as SectionId) : "account";
  });
  // Persist the open section so a refresh returns to the same tab (mirrors the editor).
  const setSection = (id: SectionId) => {
    localStorage.setItem(SECTION_STORAGE_KEY, id);
    setSectionState(id);
  };

  // 深链:别处(如工作流「模型未配置」提示)→ mosael:open-settings 直达对应分区。
  React.useEffect(() => {
    const onOpen = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      const [id, focus] = String(detail || "").split(":");
      if (id === "providers") {
        const next =
          focus === "chat"
            ? "provider-chat"
            : focus === "image"
              ? "provider-image"
              : focus === "video"
                ? "provider-video"
                : focus === "tts" || focus === "podcast" || focus === "audio"
                  ? "provider-audio"
                  : "provider-chat";
        setSection(next);
        setFocusProviderCapability(focus || null);
        return;
      }
      if (SECTION_IDS.includes(id as SectionId)) {
        setSection(id as SectionId);
        setFocusProviderCapability(focus ?? null);
      }
    };
    window.addEventListener("mosael:open-settings", onOpen);
    return () => window.removeEventListener("mosael:open-settings", onOpen);
  }, []);

  const nav: Array<{ id: SectionId; label: string; icon: React.ReactNode }> = [
    { id: "account", label: t("settingsAccount"), icon: <UserRound size={14} /> },
    { id: "team", label: t("teamTitle"), icon: <Users size={14} /> },
    { id: "appearance", label: t("settingsAppearance"), icon: <Palette size={14} /> },
    { id: "provider-chat", label: t("providerChatTitle"), icon: <MessageSquare size={14} /> },
    { id: "provider-image", label: t("providerImageTitle"), icon: <ImageIcon size={14} /> },
    { id: "provider-video", label: t("providerVideoTitle"), icon: <Video size={14} /> },
    { id: "provider-audio", label: t("providerAudioTitle"), icon: <AudioLines size={14} /> },
    { id: "provider-pricing", label: t("providerPricingTitle"), icon: <ReceiptText size={14} /> },
    // 重试对**所有** AI 供应商调用生效(对话/生图/生视频/语音/向量化),所以自成一节。
    // 原本挂在「AI 对话」下面,位置本身就在说"只管对话",而它从来不是。
    { id: "ai-runtime", label: t("aiRuntimeTitle"), icon: <RefreshCw size={14} /> },
    // 记忆和供应商/重试挨着:它们都是"智能体怎么工作"的设置,而不是某种能力的配置。
    { id: "agent-memory", label: t("agentMemoryTitle"), icon: <Brain size={14} /> },
    // 放行准则和记忆并排:同样是"智能体怎么工作"的设置,而不是某种能力的配置。
    { id: "agent-autopilot", label: t("autopilotTitle"), icon: <ShieldCheck size={14} /> },
    { id: "transcribe", label: t("asrModelsTitle"), icon: <Mic size={14} /> },
    { id: "voice", label: t("voiceCloneTitle"), icon: <AudioLines size={14} /> },
    { id: "feishu", label: t("feishuTitle"), icon: <MessageSquare size={14} /> },
    // 部署与本地后端挨着:两者说的都是"这台后端",而不是某个工作区。
    { id: "backend", label: t("settingsBackend"), icon: <Server size={14} /> },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2 [&>*]:shrink-0">
      <div className="relative grid min-h-0 flex-1 items-stretch gap-2 max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)]"
        style={{ gridTemplateColumns: `${sidebar.width}px minmax(0, 1fr)` }}>
        <nav className="grid min-h-0 content-start gap-0.5 overflow-y-auto rounded-md border border-border bg-panel p-1.5 shadow-[var(--shadow-panel)] max-[880px]:inline-flex max-[880px]:w-fit max-[880px]:max-w-full max-[880px]:gap-0 max-[880px]:overflow-x-auto max-[880px]:overflow-y-hidden max-[880px]:rounded max-[880px]:p-0 max-[880px]:[&>*+*]:border-l max-[880px]:[&>*+*]:border-border" aria-label={t("settingsTitle")}>
          {nav.map((item) => (
            <button
              key={item.id}
              type="button"
              className={cn(
                "flex cursor-pointer items-center gap-[9px] rounded-md border-0 bg-transparent px-2.5 py-1.5 text-left text-ui-md text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-foreground max-[880px]:shrink-0 max-[880px]:gap-1.5 max-[880px]:whitespace-nowrap max-[880px]:rounded-none max-[880px]:px-2.5 max-[880px]:py-[5px] max-[880px]:text-ui-sm",
                section === item.id && "bg-accent font-[550] text-accent-foreground hover:bg-accent hover:text-accent-foreground",
              )}
              onClick={() => {
                setFocusProviderCapability(null);
                setSection(item.id);
              }}
            >
              {item.icon} {item.label}
            </button>
          ))}
        </nav>
        {/* 边缘拖动 —— 和别处同一套(lib/useResizableSidebar)。 */}
        <div {...sidebar.handleProps} />
        {/* 右栏是**一块占满高度的面板**,内部滚动 —— 和插件页、定时任务页同一套。此前它跟着
            内容走,内容少时就是半截,而左边是个完整的带边框面板。 */}
        <SettingsSectionStack className="min-h-0 min-w-0 overflow-y-auto rounded-md border border-border bg-panel px-3.5 py-3 shadow-[var(--shadow-panel)]">
          {section === "account" && <AccountSection />}
          {section === "team" && <TeamSection workspace={workspace} />}
          {section === "appearance" && (
            <>
              <AppearanceSection />
              <BackgroundSection />
              <CustomCssSection />
            </>
          )}
          {section === "provider-chat" && (
            <>
              <ProviderDefaultsSection capabilities={["chat"]} focusCapability={focusProviderCapability} />
              <ProviderProfilesSection
                capability="chat"
                title={t("providerChatTitle")}
                description={t("providerChatDesc")}
              />
            </>
          )}
          {section === "ai-runtime" && <AiRuntimeSection />}
          {section === "agent-memory" && <AgentMemorySection workspace={workspace} />}
          {section === "agent-autopilot" && <AutopilotRulesSection workspace={workspace} />}
          {section === "provider-image" && (
            <>
              <ProviderDefaultsSection capabilities={["image"]} focusCapability={focusProviderCapability} />
              <ProviderProfilesSection
                capability="image"
                title={t("providerImageTitle")}
                description={t("providerImageDesc")}
              />
            </>
          )}
          {section === "provider-video" && (
            <>
              <ProviderDefaultsSection capabilities={["video"]} focusCapability={focusProviderCapability} />
              <ProviderProfilesSection
                capability="video"
                title={t("providerVideoTitle")}
                description={t("providerVideoDesc")}
              />
            </>
          )}
          {section === "provider-audio" && (
            <>
              <BuiltinTtsSection onOpenVoiceClone={() => setSection("voice")} />
              <ProviderProfilesSection
                capability="tts"
                title={t("providerTtsTitle")}
                description={t("providerTtsDesc")}
              />
              <ProviderProfilesSection
                capability="podcast"
                title={t("providerPodcastTitle")}
                description={t("providerPodcastDesc")}
              />
            </>
          )}
          {section === "provider-pricing" && <ProviderPricingSection workspace={workspace} />}
          {section === "transcribe" && <AsrModelsSection />}
          {section === "voice" && (
            <>
              <VoiceCloneSection />
              {/* 引擎/权重是这一页的上半截,音色是下半截 —— 此前只有上半截,而"用哪把嗓子"
                  得去剪辑页的配音面板里管(要先打开一个项目才够得着)。 */}
              <VoiceLibrarySection workspace={workspace} />
            </>
          )}
          {section === "feishu" && <FeishuSection workspace={workspace} />}
          {section === "backend" && <BackendSection workspace={workspace} />}
        </SettingsSectionStack>
      </div>
    </div>
  );
}
