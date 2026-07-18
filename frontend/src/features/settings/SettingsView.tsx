import React from "react";
import { useQuery } from "@tanstack/react-query";
import { KeyRound, LogOut, MessageSquare, Mic, MonitorCog, Moon, Palette, Server, Sun, UserRound } from "lucide-react";

import { API_BASE, api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { FeishuSection } from "@/features/settings/FeishuSection";
import { AsrModelsSection } from "@/features/settings/AsrModelsSection";
import { KbEmbeddingSection } from "@/features/settings/KbEmbeddingSection";
import { ProviderDefaultsSection } from "@/features/settings/ProviderDefaultsSection";
import { ProviderProfilesSection } from "@/features/settings/ProviderProfilesSection";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ServerPicker } from "@/components/layout/ServerPicker";

type KbStatus = components["schemas"]["KbStatusOut"];

type SectionId = "account" | "appearance" | "providers" | "transcribe" | "feishu" | "backend";

const SECTION_IDS: SectionId[] = ["account", "appearance", "providers", "transcribe", "feishu", "backend"];

export function SettingsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const [section, setSection] = React.useState<SectionId>("account");

  // 深链:别处(如工作流「模型未配置」提示)→ mibu:open-settings 直达对应分区。
  React.useEffect(() => {
    const onOpen = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (SECTION_IDS.includes(id as SectionId)) setSection(id as SectionId);
    };
    window.addEventListener("mibu:open-settings", onOpen);
    return () => window.removeEventListener("mibu:open-settings", onOpen);
  }, []);

  const nav: Array<{ id: SectionId; label: string; icon: React.ReactNode }> = [
    { id: "account", label: t("settingsAccount"), icon: <UserRound size={14} /> },
    { id: "appearance", label: t("settingsAppearance"), icon: <Palette size={14} /> },
    { id: "providers", label: t("settingsProviders"), icon: <KeyRound size={14} /> },
    { id: "transcribe", label: t("asrModelsTitle"), icon: <Mic size={14} /> },
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
          {section === "appearance" && <AppearanceSection />}
          {section === "providers" && (
            <>
              <ProviderProfilesSection />
              <ProviderDefaultsSection />
              <KbEmbeddingSection />
            </>
          )}
          {section === "transcribe" && <AsrModelsSection />}
          {section === "feishu" && <FeishuSection workspace={workspace} />}
          {section === "backend" && <BackendSection workspace={workspace} />}
        </div>
      </div>
    </div>
  );
}

function AccountSection() {
  const t = useI18n();
  const { user, logout } = useAuth();
  return (
    <SettingsGroup title={t("settingsAccount")} description={t("settingsAccountDesc")}>
      <SettingsRow label={t("settingsUsername")} description={t("settingsUsernameDesc")}>
        <code className="timecode sg-value">{user?.username}</code>
        <Button variant="outline" size="sm" onClick={() => void logout()}>
          <LogOut size={13} /> {t("signOut")}
        </Button>
      </SettingsRow>
    </SettingsGroup>
  );
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
    </SettingsGroup>
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
