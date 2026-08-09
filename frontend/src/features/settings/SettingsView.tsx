import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Camera, Check, Database, ImageIcon, Loader2, LogOut, MessageSquare, Mic, MonitorCog, Moon, Palette, ReceiptText, RefreshCw, RotateCcw, Server, Sun, Upload, UserRound, Users, Video, X,
  Brain,
  ShieldCheck,} from "lucide-react";
import { toast } from "sonner";

import { API_BASE, api, userAvatarUrl, type Workspace } from "@/api/client";
import { BACKGROUND_PRESETS, type BackgroundKind, compressImageFile, useAppearance } from "@/app/appearance";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import type { components } from "@/api/generated/schema";

type NetworkConfig = components["schemas"]["NetworkConfigOut"];
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { FeishuSection } from "@/features/settings/FeishuSection";
import { AsrModelsSection } from "@/features/settings/AsrModelsSection";
import { VoiceCloneSection } from "@/features/settings/VoiceCloneSection";
import { AgentMemorySection } from "@/features/settings/AgentMemorySection";
import { AutopilotRulesSection } from "@/features/settings/AutopilotRulesSection";
import { AiRuntimeSection } from "@/features/settings/AiRuntimeSection";
import { TeamSection } from "@/features/settings/TeamSection";
import { ProviderDefaultsSection } from "@/features/settings/ProviderDefaultsSection";
import { ProviderPricingSection } from "@/features/settings/ProviderPricingSection";
import { ProviderProfilesSection } from "@/features/settings/ProviderProfilesSection";
import { BuiltinTtsSection } from "@/features/settings/BuiltinTtsSection";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ServerPicker } from "@/components/layout/ServerPicker";
import { cn } from "@/lib/utils";


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

const SECTION_STORAGE_KEY = "openstudio:settings-section";

export function SettingsView({ workspace }: { workspace: Workspace }) {
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

  // 深链:别处(如工作流「模型未配置」提示)→ openstudio:open-settings 直达对应分区。
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
    window.addEventListener("openstudio:open-settings", onOpen);
    return () => window.removeEventListener("openstudio:open-settings", onOpen);
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
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0">
      <div className="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)] items-stretch gap-2 max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)]">
        <nav className="grid content-start gap-0.5 rounded-lg border border-border bg-panel p-1.5 max-[880px]:inline-flex max-[880px]:w-fit max-[880px]:max-w-full max-[880px]:gap-0 max-[880px]:overflow-x-auto max-[880px]:overflow-y-hidden max-[880px]:rounded max-[880px]:p-0 max-[880px]:[&>*+*]:border-l max-[880px]:[&>*+*]:border-border" aria-label={t("settingsTitle")}>
          {nav.map((item) => (
            <button
              key={item.id}
              type="button"
              className={cn(
                "flex cursor-pointer items-center gap-[9px] rounded-md border-0 bg-transparent px-2.5 py-1.5 text-left text-[13px] text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-foreground max-[880px]:shrink-0 max-[880px]:gap-1.5 max-[880px]:whitespace-nowrap max-[880px]:rounded-none max-[880px]:px-2.5 max-[880px]:py-[5px] max-[880px]:text-[12.5px]",
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
        <div className="grid min-w-0 content-start gap-5 overflow-y-auto px-0.5 pb-2.5 pt-1">
          {section === "account" && <AccountSection />}
          {section === "team" && <TeamSection workspace={workspace} />}
          {section === "appearance" && (
            <>
              <AppearanceSection />
              <BackgroundSection />
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
          {section === "voice" && <VoiceCloneSection />}
          {section === "feishu" && <FeishuSection workspace={workspace} />}
          {section === "backend" && <BackendSection workspace={workspace} />}
        </div>
      </div>
    </div>
  );
}

function AccountSection() {
  const t = useI18n();
  const { user, updateProfile, changePassword, updateAvatar, logout } = useAuth();
  const [profile, setProfile] = React.useState(() => profileFromUser(user));
  const [saveState, setSaveState] = React.useState<"saved" | "saving" | "error">("saved");
  const [passwords, setPasswords] = React.useState({ current: "", next: "", confirm: "" });
  const [passwordPending, setPasswordPending] = React.useState(false);
  const lastSavedRef = React.useRef(profileKey(profile));

  React.useEffect(() => {
    const next = profileFromUser(user);
    setProfile(next);
    lastSavedRef.current = profileKey(next);
    setSaveState("saved");
  }, [user?.id, user?.username, user?.display_name, user?.signature]);

  React.useEffect(() => {
    const next = normalizeProfile(profile);
    const nextKey = profileKey(next);
    if (next.username.length < 2 || next.display_name.length < 1) return;
    if (nextKey === lastSavedRef.current) {
      setSaveState("saved");
      return;
    }
    setSaveState("saving");
    const timer = window.setTimeout(async () => {
      try {
        const saved = await updateProfile(next);
        lastSavedRef.current = profileKey(profileFromUser(saved));
        setSaveState("saved");
      } catch (error) {
        setSaveState("error");
        toast.error((error as Error).message || t("profileSaveFailed"));
      }
    }, 650);
    return () => window.clearTimeout(timer);
  }, [profile, t, updateProfile]);

  const canUpdatePassword =
    passwords.current.length >= 4 &&
    passwords.next.length >= 4 &&
    passwords.next === passwords.confirm &&
    !passwordPending;

  const submitPassword = async () => {
    if (passwords.next !== passwords.confirm) {
      toast.error(t("passwordMismatch"));
      return;
    }
    if (passwords.next.length < 4) {
      toast.error(t("passwordTooShort"));
      return;
    }
    setPasswordPending(true);
    try {
      await changePassword(passwords.current, passwords.next);
      setPasswords({ current: "", next: "", confirm: "" });
      toast.success(t("passwordUpdated"));
    } catch (error) {
      toast.error((error as Error).message || t("passwordUpdateFailed"));
    } finally {
      setPasswordPending(false);
    }
  };

  const displayName = profile.display_name || profile.username || "M";
  const initial = displayName.slice(0, 1).toUpperCase();
  const avatarSrc = user?.avatar_key && user.id ? userAvatarUrl(user.id, user.avatar_key) : "";
  const avatarInputRef = React.useRef<HTMLInputElement | null>(null);
  const [avatarPending, setAvatarPending] = React.useState(false);
  const pickAvatar = async (file: File) => {
    setAvatarPending(true);
    try {
      await updateAvatar(file);
      toast.success(t("avatarUpdated"));
    } catch (error) {
      toast.error(t("avatarUpdateFailed"), { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setAvatarPending(false);
    }
  };

  return (
    <SettingsGroup
      title={t("settingsAccount")}
      description={t("settingsAccountDesc")}
      actions={
        <Button variant="outline" size="sm" onClick={() => void logout()}>
          <LogOut size={13} /> {t("signOut")}
        </Button>
      }
    >
      <SettingsBlock>
        <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3">
          <button
            type="button"
            className="group/avatar relative inline-flex h-[38px] w-[38px] cursor-pointer items-center justify-center overflow-hidden rounded-xl border-0 bg-accent p-0 font-bold text-accent-foreground shadow-[var(--shadow-panel)]"
            title={t("avatarChange")}
            aria-label={t("avatarChange")}
            disabled={avatarPending}
            onClick={() => avatarInputRef.current?.click()}
          >
            {avatarSrc ? <img src={avatarSrc} className="h-full w-full object-cover" alt="" /> : initial}
            <span className="absolute inset-0 grid place-items-center bg-[rgb(0_0_0/0.45)] text-white opacity-0 transition-opacity duration-100 group-hover/avatar:opacity-100">
              {avatarPending ? <Loader2 size={13} className="animate-openstudio-spin" /> : <Camera size={13} />}
            </span>
          </button>
          <input
            ref={avatarInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void pickAvatar(file);
            }}
          />
          <div className="[&_small]:text-xs [&_small]:leading-[1.45] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:text-sm [&_strong]:font-[650]">
            <strong>{displayName}</strong>
            <small>@{profile.username || "account"}</small>
          </div>
          <span
            className={cn(
              "inline-flex items-center gap-[5px] whitespace-nowrap text-xs text-muted-foreground",
              saveState === "saved" && "text-success",
              saveState === "error" && "text-destructive",
            )}
            aria-live="polite"
          >
            {saveState === "saving" ? (
              <>
                <Loader2 size={12} className="animate-openstudio-spin" /> {t("profileSaving")}
              </>
            ) : saveState === "error" ? (
              t("profileSaveFailed")
            ) : (
              <>
                <Check size={12} /> {t("profileSaved")}
              </>
            )}
          </span>
        </div>
      </SettingsBlock>
      <SettingsBlock>
        <div className="grid grid-cols-2 gap-3">
          <label className="grid min-w-0 gap-1.5 [&>span]:text-[12.5px] [&>span]:font-semibold [&_small]:text-xs [&_small]:leading-[1.45] [&_small]:text-muted-foreground">
            <span>{t("settingsUsername")}</span>
            <small>{t("settingsUsernameDesc")}</small>
            <Input
              value={profile.username}
              autoComplete="username"
              onChange={(event) => setProfile((current) => ({ ...current, username: event.target.value }))}
            />
          </label>
          <label className="grid min-w-0 gap-1.5 [&>span]:text-[12.5px] [&>span]:font-semibold [&_small]:text-xs [&_small]:leading-[1.45] [&_small]:text-muted-foreground">
            <span>{t("displayName")}</span>
            <small>{t("displayNameDesc")}</small>
            <Input
              value={profile.display_name}
              autoComplete="name"
              onChange={(event) => setProfile((current) => ({ ...current, display_name: event.target.value }))}
            />
          </label>
          <label className="col-span-full grid min-w-0 gap-1.5 [&>span]:text-[12.5px] [&>span]:font-semibold [&_small]:text-xs [&_small]:leading-[1.45] [&_small]:text-muted-foreground">
            <span>{t("signature")}</span>
            <small>{t("signatureDesc")}</small>
            <Textarea
              className="resize-y"
              rows={3}
              maxLength={500}
              value={profile.signature}
              placeholder={t("signaturePlaceholder")}
              onChange={(event) => setProfile((current) => ({ ...current, signature: event.target.value }))}
            />
          </label>
        </div>
      </SettingsBlock>
      <SettingsBlock>
        <div className="grid gap-3">
          <div className="[&_small]:text-xs [&_small]:leading-[1.45] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:text-sm [&_strong]:font-[650]">
            <strong>{t("settingsPassword")}</strong>
            <small>{t("settingsPasswordDesc")}</small>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid min-w-0 gap-1.5 [&>span]:text-[12.5px] [&>span]:font-semibold [&_small]:text-xs [&_small]:leading-[1.45] [&_small]:text-muted-foreground">
              <span>{t("currentPassword")}</span>
              <Input
                type="password"
                value={passwords.current}
                autoComplete="current-password"
                onChange={(event) => setPasswords((current) => ({ ...current, current: event.target.value }))}
              />
            </label>
            <label className="grid min-w-0 gap-1.5 [&>span]:text-[12.5px] [&>span]:font-semibold [&_small]:text-xs [&_small]:leading-[1.45] [&_small]:text-muted-foreground">
              <span>{t("newPassword")}</span>
              <Input
                type="password"
                value={passwords.next}
                autoComplete="new-password"
                onChange={(event) => setPasswords((current) => ({ ...current, next: event.target.value }))}
              />
            </label>
            <label className="grid min-w-0 gap-1.5 [&>span]:text-[12.5px] [&>span]:font-semibold [&_small]:text-xs [&_small]:leading-[1.45] [&_small]:text-muted-foreground">
              <span>{t("confirmPassword")}</span>
              <Input
                type="password"
                value={passwords.confirm}
                autoComplete="new-password"
                onChange={(event) => setPasswords((current) => ({ ...current, confirm: event.target.value }))}
              />
            </label>
            <div className="flex items-end justify-end">
              <Button size="sm" disabled={!canUpdatePassword} onClick={() => void submitPassword()}>
                {passwordPending ? <Loader2 size={13} className="animate-openstudio-spin" /> : null} {t("updatePassword")}
              </Button>
            </div>
          </div>
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}

function profileFromUser(user: ReturnType<typeof useAuth>["user"]) {
  return {
    username: user?.username ?? "",
    display_name: user?.display_name || user?.username || "",
    signature: user?.signature ?? "",
  };
}

function normalizeProfile(profile: { username: string; display_name: string; signature: string }) {
  const username = profile.username.trim().toLowerCase();
  return {
    username,
    display_name: profile.display_name.trim() || username,
    signature: profile.signature.trim(),
  };
}

function profileKey(profile: { username: string; display_name: string; signature: string }) {
  return `${profile.username}\n${profile.display_name}\n${profile.signature}`;
}

/** 开机自启(仅桌面端渲染,且开发模式下主进程不暴露——那时 execPath 是裸 Electron)。
 *  和「关窗收进托盘」是一对:后者让应用关窗后还活着,前者让它开机就活着。定时任务依赖
 *  后端进程存活(后端是主进程 spawn 的子进程),两者缺一,到点就不会触发。 */
function StartupRow() {
  const t = useI18n();
  const get = window.openStudioDesktop?.getOpenAtLogin;
  const set = window.openStudioDesktop?.setOpenAtLogin;
  // null = 还没问到;false/true = 支持且当前值;"unsupported" = 主进程说这个环境不提供
  // (开发模式:execPath 是裸 Electron,写进登录项会污染开发机)。
  const [enabled, setEnabled] = React.useState<boolean | null | "unsupported">(null);
  React.useEffect(() => {
    if (!get) return;
    void get().then((value) => setEnabled(value === null || value === undefined ? "unsupported" : value));
  }, [get]);
  if (!get || !set || enabled === "unsupported") return null;
  return (
    <SettingsRow label={t("settingsStartup")} description={t("settingsStartupDesc")}>
      <Switch
        checked={enabled ?? false}
        disabled={enabled === null}
        // 用系统回读的值落地,而不是乐观置位:写登录项可能被系统策略拒绝(受管理的设备上
        // 常见),那时开关该弹回去,而不是显示成开着、实际没生效。
        onCheckedChange={(next) => void set(next).then((value) => setEnabled(value ?? "unsupported"))}
      />
    </SettingsRow>
  );
}

/** 检查更新(仅桌面端渲染):查 GitHub Releases 比对版本,发现新版给「查看」入口。
 *  未签名的 mac 包装不了静默自动安装,这里是诚实的降级——提示 + 打开发布页。 */
function UpdateCheckButton() {
  const t = useI18n();
  const [checking, setChecking] = React.useState(false);
  const check = window.openStudioDesktop?.checkUpdates;
  if (!check) return null;
  return (
    <Button
      size="sm"
      variant="outline"
      className="h-7"
      disabled={checking}
      onClick={async () => {
        setChecking(true);
        try {
          const info = await check();
          if (info.error) toast.error(t("updateCheckFailed"));
          else if (info.hasUpdate) {
            toast(t("updateAvailable").replace("{version}", info.latest ?? ""), {
              duration: 12000,
              action: { label: t("updateView"), onClick: () => window.open(info.url, "_blank") },
            });
          } else {
            // 带上比对到的版本号:光说「已是最新」在版本号本身有问题时毫无信息量,
            // 用户没法判断它到底比了什么。
            toast.success(`${t("updateUpToDate")} · v${info.latest ?? info.current ?? ""}`);
          }
        } finally {
          setChecking(false);
        }
      }}
    >
      {checking ? <Loader2 size={13} className="animate-openstudio-spin" /> : <RefreshCw size={13} />}
      {t("updateCheck")}
    </Button>
  );
}

function AppearanceSection() {
  const t = useI18n();
  const { theme, setTheme, locale, setLocale } = usePreferences();
  return (
    <SettingsGroup title={t("settingsAppearance")} description={t("settingsAppearanceDesc")}>
      <SettingsRow label={t("settingsTheme")} description={t("settingsThemeDesc")}>
        <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border">
          <button
            type="button"
            className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", theme === "light" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
            onClick={() => setTheme("light")}
          >
            <Sun size={13} /> {t("themeLight")}
          </button>
          <button
            type="button"
            className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", theme === "dark" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
            onClick={() => setTheme("dark")}
          >
            <Moon size={13} /> {t("themeDark")}
          </button>
          <button
            type="button"
            className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", theme === "system" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
            onClick={() => setTheme("system")}
          >
            <MonitorCog size={13} /> {t("themeSystem")}
          </button>
        </div>
      </SettingsRow>
      <SettingsRow label={t("settingsLanguage")} description={t("settingsLanguageDesc")}>
        <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border">
          <button
            type="button"
            className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", locale === "zh-CN" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
            onClick={() => setLocale("zh-CN")}
          >
            {t("languageZh")}
          </button>
          <button
            type="button"
            className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", locale === "en-US" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
            onClick={() => setLocale("en-US")}
          >
            {t("languageEn")}
          </button>
        </div>
      </SettingsRow>
    </SettingsGroup>
  );
}

/** 自定义外观:整体背景(渐变预设 / 上传图片)+ 表面透明度、磨玻璃模糊、背景压暗。
    全部即时预览,存 localStorage(逐设备)。无背景时应用保持原不透明外观。 */
function BackgroundSection() {
  const t = useI18n();
  const appearance = useAppearance();
  const fileRef = React.useRef<HTMLInputElement>(null);
  const active = appearance.kind !== "none" && !(appearance.kind === "image" && !appearance.image);

  const pickImage = async (file: File | undefined) => {
    if (!file) return;
    try {
      appearance.setImage(await compressImageFile(file));
    } catch (error) {
      toast.error((error as Error).message);
    }
  };
  const chooseKind = (kind: BackgroundKind) => {
    if (kind === "image" && !appearance.image) fileRef.current?.click();
    else appearance.update({ kind });
  };

  return (
    <SettingsGroup title={t("appearanceBgTitle")} description={t("appearanceBgDesc")}>
      <SettingsRow label={t("appearanceBgSource")} description={t("appearanceBgSourceDesc")}>
        <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border">
          {(["none", "preset", "image"] as BackgroundKind[]).map((kind) => (
            <button
              key={kind}
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", appearance.kind === kind && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              onClick={() => chooseKind(kind)}
            >
              {kind === "none" ? t("appearanceBgNone") : kind === "preset" ? t("appearanceBgPreset") : t("appearanceBgImage")}
            </button>
          ))}
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(event) => {
              void pickImage(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </div>
      </SettingsRow>

      {appearance.kind === "preset" && (
        <SettingsBlock>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-2">
            {BACKGROUND_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={cn(
                  "relative h-14 cursor-pointer overflow-hidden rounded-lg border border-border bg-cover bg-center transition-[box-shadow,transform] duration-[120ms] hover:-translate-y-px [&>span]:absolute [&>span]:bottom-1.5 [&>span]:left-[7px] [&>span]:text-[11px] [&>span]:font-semibold [&>span]:text-white [&>span]:[text-shadow:0_1px_3px_rgba(0,0,0,0.55)]",
                  appearance.preset === preset.id && "border-primary shadow-[0_0_0_2px_var(--primary)]",
                )}
                style={{ backgroundImage: preset.css }}
                onClick={() => appearance.update({ preset: preset.id })}
              >
                <span>{preset.label}</span>
              </button>
            ))}
          </div>
        </SettingsBlock>
      )}

      {appearance.kind === "image" && (
        <SettingsBlock>
          <div className="flex items-center gap-3">
            {appearance.image ? (
              <div className="h-[72px] w-32 shrink-0 rounded-lg border border-border bg-cover bg-center" style={{ backgroundImage: `url(${appearance.image})` }} />
            ) : (
              <div className="flex h-[72px] w-32 shrink-0 items-center gap-1.5 rounded-lg border border-dashed border-border-strong px-2.5 text-[11.5px] text-muted-foreground">
                <ImageIcon size={16} /> {t("appearanceBgNoImage")}
              </div>
            )}
            <div className="flex flex-col items-start gap-1.5">
              <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                <Upload size={13} /> {appearance.image ? t("appearanceBgReplace") : t("appearanceBgUpload")}
              </Button>
              {appearance.image && (
                <Button variant="ghost" size="sm" onClick={() => appearance.clearImage()}>
                  <X size={13} /> {t("appearanceBgRemove")}
                </Button>
              )}
            </div>
          </div>
        </SettingsBlock>
      )}

      {active && (
        <>
          <SliderRow
            label={t("appearanceOpacity")}
            value={appearance.surfaceOpacity}
            min={0.35}
            max={1}
            step={0.01}
            format={(v) => `${Math.round(v * 100)}%`}
            onChange={(v) => appearance.update({ surfaceOpacity: v })}
          />
          <SliderRow
            label={t("appearanceBlur")}
            value={appearance.blur}
            min={0}
            max={32}
            step={1}
            format={(v) => `${Math.round(v)}px`}
            onChange={(v) => appearance.update({ blur: v })}
          />
          <SliderRow
            label={t("appearanceDim")}
            value={appearance.dim}
            min={0}
            max={0.75}
            step={0.01}
            format={(v) => `${Math.round(v * 100)}%`}
            onChange={(v) => appearance.update({ dim: v })}
          />
        </>
      )}

      <SettingsRow label={t("appearanceReset")} description={t("appearanceResetDesc")}>
        <Button variant="outline" size="sm" onClick={() => appearance.reset()}>
          <RotateCcw size={13} /> {t("appearanceReset")}
        </Button>
      </SettingsRow>
    </SettingsGroup>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  onChange: (value: number) => void;
}) {
  return (
    <SettingsRow label={label}>
      <div className="flex min-w-[220px] items-center gap-2.5">
        <Slider value={[value]} min={min} max={max} step={step} onValueChange={([v]) => onChange(v)} />
        <span className="w-[42px] text-right text-xs tabular-nums text-muted-foreground">{format(value)}</span>
      </div>
    </SettingsRow>
  );
}

/** 本地/远程服务器切换,与登录页复用同一 ServerPicker(探活 + 强连兜底 + 整页重载)。 */
function ServerSwitchRow() {
  const t = useI18n();
  return (
    <SettingsRow label={t("serverSwitchLabel")} description={t("serverSwitchDesc")}>
      <ServerPicker />
    </SettingsRow>
  );
}

/** 出站代理。挂在「本地后端」下:它和端点、开机自启一样是实例级的基础设施设置,
 *  为一个字段单开一个导航项不值得。 */
function ProxySection() {
  const t = useI18n();
  const qc = useQueryClient();
  const config = useQuery({
    queryKey: ["network-config"],
    queryFn: () => api<NetworkConfig>("/api/settings/network"),
  });
  const [form, setForm] = React.useState<{ proxy_url: string; no_proxy: string } | null>(null);
  const current = form ?? {
    proxy_url: config.data?.proxy_url ?? "",
    no_proxy: config.data?.no_proxy ?? "",
  };
  const save = useMutation({
    mutationFn: () =>
      api<NetworkConfig>("/api/settings/network", { method: "PUT", body: JSON.stringify(current) }),
    onSuccess: (next) => {
      setForm(null);
      qc.setQueryData(["network-config"], next);
    },
  });
  const dirty =
    form !== null &&
    (form.proxy_url !== (config.data?.proxy_url ?? "") || form.no_proxy !== (config.data?.no_proxy ?? ""));

  return (
    <SettingsGroup title={t("proxyTitle")} description={t("proxyDesc")}>
      <SettingsRow label={t("proxyUrl")} description={t("proxyUrlDesc")}>
        <Input
          className="w-[320px] max-w-full"
          placeholder="http://127.0.0.1:7890"
          value={current.proxy_url}
          onChange={(e) => setForm({ ...current, proxy_url: e.target.value })}
        />
      </SettingsRow>
      <SettingsRow label={t("proxyNoProxy")} description={t("proxyNoProxyDesc")}>
        <Input
          className="w-[320px] max-w-full"
          placeholder="example.com, 10.0.0.0/8"
          value={current.no_proxy}
          onChange={(e) => setForm({ ...current, no_proxy: e.target.value })}
        />
      </SettingsRow>
      <SettingsRow label={t("proxyEffective")} description="">
        <code className="timecode max-w-[320px] truncate text-xs text-muted-foreground">
          {config.data?.effective_no_proxy || "…"}
        </code>
        <Button size="sm" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
          {t("save")}
        </Button>
      </SettingsRow>
    </SettingsGroup>
  );
}

function BackendSection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  return (
    <>
      <SettingsGroup title={t("settingsBackend")} description={t("settingsBackendDesc")}>
        <ServerSwitchRow />
        <SettingsRow label={t("settingsEndpoint")} description={t("settingsEndpointDesc")}>
          <code className="timecode max-w-[320px] truncate text-xs text-muted-foreground">{API_BASE}</code>
        </SettingsRow>
        <SettingsRow label={t("settingsWorkspace")} description={t("settingsWorkspaceDesc")}>
          <code className="timecode max-w-[320px] truncate text-xs text-muted-foreground">{workspace.id}</code>
        </SettingsRow>
        <StartupRow />
        <SettingsRow label={t("settingsVersion")} description={t("settingsVersionDesc")}>
          <code className="timecode max-w-[320px] truncate text-xs text-muted-foreground">v{__APP_VERSION__}</code>
          <UpdateCheckButton />
        </SettingsRow>
      </SettingsGroup>
      <ProxySection />
    </>
  );
}
