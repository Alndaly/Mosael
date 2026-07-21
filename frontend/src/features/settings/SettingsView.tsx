import React from "react";
import { useQuery } from "@tanstack/react-query";
import { AudioLines, Check, Database, ImageIcon, Loader2, LogOut, MessageSquare, Mic, MonitorCog, Moon, Palette, RotateCcw, Server, Sun, Upload, UserRound, Users, Video, X } from "lucide-react";
import { toast } from "sonner";

import { API_BASE, api, type Workspace } from "@/api/client";
import { BACKGROUND_PRESETS, type BackgroundKind, compressImageFile, useAppearance } from "@/app/appearance";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { compositorEnabled, compositorSupported, setCompositorEnabled } from "@/features/editor/playback/compositorFlag";
import type { components } from "@/api/generated/schema";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { FeishuSection } from "@/features/settings/FeishuSection";
import { AsrModelsSection } from "@/features/settings/AsrModelsSection";
import { VoiceCloneSection } from "@/features/settings/VoiceCloneSection";
import { KbEmbeddingSection } from "@/features/settings/KbEmbeddingSection";
import { TeamSection } from "@/features/settings/TeamSection";
import { ProviderDefaultsSection } from "@/features/settings/ProviderDefaultsSection";
import { ProviderProfilesSection } from "@/features/settings/ProviderProfilesSection";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ServerPicker } from "@/components/layout/ServerPicker";

type KbStatus = components["schemas"]["KbStatusOut"];

type SectionId =
  | "account"
  | "team"
  | "appearance"
  | "provider-chat"
  | "provider-image"
  | "provider-video"
  | "provider-embedding"
  | "provider-audio"
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
  "provider-embedding",
  "provider-audio",
  "transcribe",
  "voice",
  "feishu",
  "backend",
];

const SECTION_STORAGE_KEY = "mibu:settings-section";

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

  // 深链:别处(如工作流「模型未配置」提示)→ mibu:open-settings 直达对应分区。
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
                : focus === "embedding"
                  ? "provider-embedding"
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
    window.addEventListener("mibu:open-settings", onOpen);
    return () => window.removeEventListener("mibu:open-settings", onOpen);
  }, []);

  const nav: Array<{ id: SectionId; label: string; icon: React.ReactNode }> = [
    { id: "account", label: t("settingsAccount"), icon: <UserRound size={14} /> },
    { id: "team", label: t("teamTitle"), icon: <Users size={14} /> },
    { id: "appearance", label: t("settingsAppearance"), icon: <Palette size={14} /> },
    { id: "provider-chat", label: t("providerChatTitle"), icon: <MessageSquare size={14} /> },
    { id: "provider-image", label: t("providerImageTitle"), icon: <ImageIcon size={14} /> },
    { id: "provider-video", label: t("providerVideoTitle"), icon: <Video size={14} /> },
    { id: "provider-embedding", label: t("providerEmbeddingTitle"), icon: <Database size={14} /> },
    { id: "provider-audio", label: t("providerAudioTitle"), icon: <AudioLines size={14} /> },
    { id: "transcribe", label: t("asrModelsTitle"), icon: <Mic size={14} /> },
    { id: "voice", label: t("voiceCloneTitle"), icon: <AudioLines size={14} /> },
    { id: "feishu", label: t("feishuTitle"), icon: <MessageSquare size={14} /> },
    { id: "backend", label: t("settingsBackend"), icon: <Server size={14} /> },
  ];

  return (
    <div className="feature-view">
      <div className="settings-shell">
        <nav className="settings-nav" aria-label={t("settingsTitle")}>
          {nav.map((item) => (
            <button
              key={item.id}
              type="button"
              className={section === item.id ? "settings-nav-item active" : "settings-nav-item"}
              onClick={() => setSection(item.id)}
            >
              {item.icon} {item.label}
            </button>
          ))}
        </nav>
        <div className="settings-content">
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
              <ProviderDefaultsSection capabilities={["chat"]} focusCapability={focusProviderCapability ?? "chat"} />
              <ProviderProfilesSection
                capability="chat"
                title={t("providerChatTitle")}
                description={t("providerChatDesc")}
              />
            </>
          )}
          {section === "provider-image" && (
            <>
              <ProviderDefaultsSection capabilities={["image"]} focusCapability={focusProviderCapability ?? "image"} />
              <ProviderProfilesSection
                capability="image"
                title={t("providerImageTitle")}
                description={t("providerImageDesc")}
              />
            </>
          )}
          {section === "provider-video" && (
            <>
              <ProviderDefaultsSection capabilities={["video"]} focusCapability={focusProviderCapability ?? "video"} />
              <ProviderProfilesSection
                capability="video"
                title={t("providerVideoTitle")}
                description={t("providerVideoDesc")}
              />
            </>
          )}
          {section === "provider-embedding" && (
            <>
              <KbEmbeddingSection />
              <ProviderProfilesSection
                capability="embedding"
                title={t("providerEmbeddingTitle")}
                description={t("providerEmbeddingDesc")}
              />
            </>
          )}
          {section === "provider-audio" && (
            <>
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
  const { user, updateProfile, changePassword, logout } = useAuth();
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
        <div className="account-profile-head">
          <span className="account-avatar">{initial}</span>
          <div>
            <strong>{displayName}</strong>
            <small>@{profile.username || "account"}</small>
          </div>
          <span className={`account-save-state ${saveState}`} aria-live="polite">
            {saveState === "saving" ? (
              <>
                <Loader2 size={12} className="spin" /> {t("profileSaving")}
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
        <div className="account-form-grid">
          <label className="account-field">
            <span>{t("settingsUsername")}</span>
            <small>{t("settingsUsernameDesc")}</small>
            <Input
              value={profile.username}
              autoComplete="username"
              onChange={(event) => setProfile((current) => ({ ...current, username: event.target.value }))}
            />
          </label>
          <label className="account-field">
            <span>{t("displayName")}</span>
            <small>{t("displayNameDesc")}</small>
            <Input
              value={profile.display_name}
              autoComplete="name"
              onChange={(event) => setProfile((current) => ({ ...current, display_name: event.target.value }))}
            />
          </label>
          <label className="account-field account-field-wide">
            <span>{t("signature")}</span>
            <small>{t("signatureDesc")}</small>
            <Textarea
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
        <div className="account-password-card">
          <div className="account-password-head">
            <strong>{t("settingsPassword")}</strong>
            <small>{t("settingsPasswordDesc")}</small>
          </div>
          <div className="account-form-grid">
            <label className="account-field">
              <span>{t("currentPassword")}</span>
              <Input
                type="password"
                value={passwords.current}
                autoComplete="current-password"
                onChange={(event) => setPasswords((current) => ({ ...current, current: event.target.value }))}
              />
            </label>
            <label className="account-field">
              <span>{t("newPassword")}</span>
              <Input
                type="password"
                value={passwords.next}
                autoComplete="new-password"
                onChange={(event) => setPasswords((current) => ({ ...current, next: event.target.value }))}
              />
            </label>
            <label className="account-field">
              <span>{t("confirmPassword")}</span>
              <Input
                type="password"
                value={passwords.confirm}
                autoComplete="new-password"
                onChange={(event) => setPasswords((current) => ({ ...current, confirm: event.target.value }))}
              />
            </label>
            <div className="account-password-actions">
              <Button size="sm" disabled={!canUpdatePassword} onClick={() => void submitPassword()}>
                {passwordPending ? <Loader2 size={13} className="spin" /> : null} {t("updatePassword")}
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

function AppearanceSection() {
  const t = useI18n();
  const { theme, setTheme, locale, setLocale } = usePreferences();
  return (
    <SettingsGroup title={t("settingsAppearance")} description={t("settingsAppearanceDesc")}>
      <SettingsRow label={t("settingsTheme")} description={t("settingsThemeDesc")}>
        <div className="seg">
          <button
            type="button"
            className={theme === "light" ? "seg-btn active" : "seg-btn"}
            onClick={() => setTheme("light")}
          >
            <Sun size={13} /> {t("themeLight")}
          </button>
          <button
            type="button"
            className={theme === "dark" ? "seg-btn active" : "seg-btn"}
            onClick={() => setTheme("dark")}
          >
            <Moon size={13} /> {t("themeDark")}
          </button>
          <button
            type="button"
            className={theme === "system" ? "seg-btn active" : "seg-btn"}
            onClick={() => setTheme("system")}
          >
            <MonitorCog size={13} /> {t("themeSystem")}
          </button>
        </div>
      </SettingsRow>
      <SettingsRow label={t("settingsLanguage")} description={t("settingsLanguageDesc")}>
        <div className="seg">
          <button
            type="button"
            className={locale === "zh-CN" ? "seg-btn active" : "seg-btn"}
            onClick={() => setLocale("zh-CN")}
          >
            {t("languageZh")}
          </button>
          <button
            type="button"
            className={locale === "en-US" ? "seg-btn active" : "seg-btn"}
            onClick={() => setLocale("en-US")}
          >
            {t("languageEn")}
          </button>
        </div>
      </SettingsRow>
      <CompositorRow />
    </SettingsGroup>
  );
}

/** Opt-in switch for the WebCodecs canvas compositor (per-device localStorage). */
function CompositorRow() {
  const t = useI18n();
  const [on, setOn] = React.useState(compositorEnabled);
  const supported = compositorSupported();
  return (
    <SettingsRow label={t("previewCompositor")} description={t("previewCompositorDesc")}>
      <Switch
        checked={on && supported}
        disabled={!supported}
        onCheckedChange={(next) => {
          setCompositorEnabled(next);
          setOn(next);
        }}
      />
    </SettingsRow>
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
        <div className="seg">
          {(["none", "preset", "image"] as BackgroundKind[]).map((kind) => (
            <button
              key={kind}
              type="button"
              className={appearance.kind === kind ? "seg-btn active" : "seg-btn"}
              onClick={() => chooseKind(kind)}
            >
              {kind === "none" ? t("appearanceBgNone") : kind === "preset" ? t("appearanceBgPreset") : t("appearanceBgImage")}
            </button>
          ))}
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden-input"
            onChange={(event) => {
              void pickImage(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </div>
      </SettingsRow>

      {appearance.kind === "preset" && (
        <SettingsBlock>
          <div className="bg-presets">
            {BACKGROUND_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={appearance.preset === preset.id ? "bg-preset active" : "bg-preset"}
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
          <div className="bg-image-row">
            {appearance.image ? (
              <div className="bg-image-preview" style={{ backgroundImage: `url(${appearance.image})` }} />
            ) : (
              <div className="bg-image-empty">
                <ImageIcon size={16} /> {t("appearanceBgNoImage")}
              </div>
            )}
            <div className="bg-image-actions">
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
      <div className="appearance-slider">
        <Slider value={[value]} min={min} max={max} step={step} onValueChange={([v]) => onChange(v)} />
        <span className="appearance-slider-val">{format(value)}</span>
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

function BackendSection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const kbStatus = useQuery({
    queryKey: ["kb-status"],
    queryFn: () => api<KbStatus>("/api/kb/status"),
  });
  const tierBadge = (enabled: boolean | undefined) => (
    <Badge variant={enabled ? "default" : "secondary"}>{enabled ? t("kbStatusOn") : t("kbStatusOff")}</Badge>
  );
  return (
    <>
      <SettingsGroup title={t("settingsBackend")} description={t("settingsBackendDesc")}>
        <ServerSwitchRow />
        <SettingsRow label={t("settingsEndpoint")} description={t("settingsEndpointDesc")}>
          <code className="timecode sg-value">{API_BASE}</code>
        </SettingsRow>
        <SettingsRow label={t("settingsWorkspace")} description={t("settingsWorkspaceDesc")}>
          <code className="timecode sg-value">{workspace.id}</code>
        </SettingsRow>
        <SettingsRow label={t("settingsVersion")} description={t("settingsVersionDesc")}>
          <code className="timecode sg-value">v{__APP_VERSION__}</code>
        </SettingsRow>
      </SettingsGroup>
      <SettingsGroup title={t("kbStatusTitle")} description={t("kbStatusDesc")}>
        <SettingsRow label={t("kbStatusEngine")} description={t("kbStatusEngineDesc")}>
          <code className="timecode sg-value">{kbStatus.data?.convert_engine ?? "…"}</code>
        </SettingsRow>
        <SettingsRow label={t("kbStatusVector")} description={t("kbStatusVectorDesc")}>
          {kbStatus.data?.embedding_model && <code className="timecode sg-value">{kbStatus.data.embedding_model}</code>}
          {tierBadge(kbStatus.data?.vector_enabled)}
        </SettingsRow>
        <SettingsRow label={t("kbStatusGraph")} description={t("kbStatusGraphDesc")}>
          {tierBadge(kbStatus.data?.graph_enabled)}
        </SettingsRow>
      </SettingsGroup>
    </>
  );
}
