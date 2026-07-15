import React from "react";
import { KeyRound, LogOut, MessageSquare, MonitorCog, Moon, Palette, Server, Sun, UserRound } from "lucide-react";

import { API_BASE, type Workspace } from "@/api/client";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { FeishuSection } from "@/features/settings/FeishuSection";
import { ProviderProfilesSection } from "@/features/settings/ProviderProfilesSection";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { Button } from "@/components/ui/button";

type SectionId = "account" | "appearance" | "providers" | "feishu" | "backend";

export function SettingsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const [section, setSection] = React.useState<SectionId>("account");

  const nav: Array<{ id: SectionId; label: string; icon: React.ReactNode }> = [
    { id: "account", label: t("settingsAccount"), icon: <UserRound size={14} /> },
    { id: "appearance", label: t("settingsAppearance"), icon: <Palette size={14} /> },
    { id: "providers", label: t("settingsProviders"), icon: <KeyRound size={14} /> },
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
          {section === "providers" && <ProviderProfilesSection />}
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

function BackendSection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  return (
    <SettingsGroup title={t("settingsBackend")} description={t("settingsBackendDesc")}>
      <SettingsRow label={t("settingsEndpoint")} description={t("settingsEndpointDesc")}>
        <code className="timecode sg-value">{API_BASE}</code>
      </SettingsRow>
      <SettingsRow label={t("settingsWorkspace")} description={t("settingsWorkspaceDesc")}>
        <code className="timecode sg-value">{workspace.id}</code>
      </SettingsRow>
    </SettingsGroup>
  );
}
