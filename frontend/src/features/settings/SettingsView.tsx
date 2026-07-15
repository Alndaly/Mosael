import { Moon, Sun } from "lucide-react";

import { API_BASE, type Workspace } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";

export function SettingsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const { theme, setTheme, locale, setLocale } = usePreferences();

  return (
    <div className="feature-view">
      <header className="feature-head">
        <div>
          <h1>{t("settingsTitle")}</h1>
          <p>{t("settingsDescription")}</p>
        </div>
      </header>

      <div className="settings-sections">
        <section className="settings-section">
          <h2 className="section-label">{t("settingsAppearance")}</h2>
          <div className="settings-row">
            <span>{t("settingsTheme")}</span>
            <div className="settings-control">
              <Button variant={theme === "light" ? "secondary" : "ghost"} size="sm" onClick={() => setTheme("light")}>
                <Sun size={14} /> {t("themeLight")}
              </Button>
              <Button variant={theme === "dark" ? "secondary" : "ghost"} size="sm" onClick={() => setTheme("dark")}>
                <Moon size={14} /> {t("themeDark")}
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

        <section className="settings-section">
          <h2 className="section-label">{t("settingsBackend")}</h2>
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
