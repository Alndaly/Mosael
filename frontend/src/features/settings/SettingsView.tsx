import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogOut, Moon, Sun } from "lucide-react";

import { API_BASE, api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { FeishuSection } from "@/features/settings/FeishuSection";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type CredentialStatus = components["schemas"]["CredentialStatusOut"];

export function SettingsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const { theme, setTheme, locale, setLocale } = usePreferences();
  const { user, logout } = useAuth();

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
          <h2 className="section-label">{t("settingsAccount")}</h2>
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

        <ProviderCredentials />

        <FeishuSection workspace={workspace} />

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

function ProviderCredentials() {
  const t = useI18n();
  const qc = useQueryClient();
  const [drafts, setDrafts] = React.useState<Record<string, string>>({});
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api<CredentialStatus[]>("/api/settings/credentials"),
  });
  const save = useMutation({
    mutationFn: ({ provider, secret }: { provider: string; secret: string }) =>
      api<CredentialStatus>("/api/settings/credentials", {
        method: "PUT",
        body: JSON.stringify({ provider, secret }),
      }),
    onSuccess: (_data, variables) => {
      setDrafts((current) => ({ ...current, [variables.provider]: "" }));
      void qc.invalidateQueries({ queryKey: ["credentials"] });
    },
  });

  return (
    <section className="settings-section">
      <h2 className="section-label">{t("settingsProviders")}</h2>
      {(credentials.data ?? [])
        .filter((item) => item.provider !== "mock")
        .map((item) => (
          <div className="settings-row" key={item.provider}>
            <span className="cred-name">
              <KeyRound size={13} /> {item.provider}
              {item.configured ? (
                <Badge variant="secondary">
                  {t("configured")} {item.hint}
                </Badge>
              ) : (
                <Badge variant="outline">{t("notConfigured")}</Badge>
              )}
            </span>
            <div className="settings-control">
              <Input
                type="password"
                className="cred-input"
                placeholder={t("providerKeyPlaceholder")}
                value={drafts[item.provider] ?? ""}
                onChange={(event) =>
                  setDrafts((current) => ({ ...current, [item.provider]: event.target.value }))
                }
              />
              <Button
                variant="outline"
                size="sm"
                disabled={!(drafts[item.provider] ?? "").trim() || save.isPending}
                onClick={() => save.mutate({ provider: item.provider, secret: drafts[item.provider].trim() })}
              >
                {t("save")}
              </Button>
            </div>
          </div>
        ))}
    </section>
  );
}
