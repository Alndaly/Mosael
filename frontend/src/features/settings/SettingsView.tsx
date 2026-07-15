import { LogOut, MonitorCog, Moon, Palette, Server, Sun, UserRound } from "lucide-react";

import { API_BASE, type Workspace } from "@/api/client";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { FeishuSection } from "@/features/settings/FeishuSection";
import { ProviderProfilesSection } from "@/features/settings/ProviderProfilesSection";
import { Button } from "@/components/ui/button";

export function SettingsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const { theme, setTheme, locale, setLocale } = usePreferences();
  const { user, logout } = useAuth();

  return (
    <div className="feature-view">
      <div className="settings-sections">
        <section className="settings-section">
          <h2 className="section-label"><UserRound size={13} /> {t("settingsAccount")}</h2>
          <div className="settings-row">
            <span>{t("settingsUsername")}</span>
            <div className="settings-control">
              <code className="timecode">{user?.username}</code>
              <Button variant="outline" size="sm" onClick={() => void logout()}>
                <LogOut size={13} /> {t("signOut")}
              </Button>
            </div>
          </div>
        </section>
        <section className="settings-section">
          <h2 className="section-label"><Palette size={13} /> {t("settingsAppearance")}</h2>
          <div className="settings-row">
            <span>{t("settingsTheme")}</span>
            <div className="settings-control">
              <Button variant={theme === "light" ? "secondary" : "ghost"} size="sm" onClick={() => setTheme("light")}>
                <Sun size={14} /> {t("themeLight")}
              </Button>
              <Button variant={theme === "dark" ? "secondary" : "ghost"} size="sm" onClick={() => setTheme("dark")}>
                <Moon size={14} /> {t("themeDark")}
              </Button>
              <Button variant={theme === "system" ? "secondary" : "ghost"} size="sm" onClick={() => setTheme("system")}>
                <MonitorCog size={14} /> {t("themeSystem")}
              </Button>
            </div>
          </div>
          <div className="settings-row">
            <span>{t("settingsLanguage")}</span>
            <div className="settings-control">
              <Button variant={locale === "zh-CN" ? "secondary" : "ghost"} size="sm" onClick={() => setLocale("zh-CN")}>
                {t("languageZh")}
              </Button>
              <Button variant={locale === "en-US" ? "secondary" : "ghost"} size="sm" onClick={() => setLocale("en-US")}>
                {t("languageEn")}
              </Button>
            </div>
          </div>
        </section>

        <ProviderProfilesSection />

        <FeishuSection workspace={workspace} />

        <section className="settings-section">
          <h2 className="section-label"><Server size={13} /> {t("settingsBackend")}</h2>
          <div className="settings-row">
            <span>{t("settingsEndpoint")}</span>
            <code className="timecode">{API_BASE}</code>
          </div>
          <div className="settings-row">
            <span>{t("settingsWorkspace")}</span>
            <code className="timecode">{workspace.id}</code>
          </div>
        </section>
      </div>
    </div>
  );
}
