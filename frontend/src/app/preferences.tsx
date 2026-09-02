import React from "react";

import { messages, type MessageKey } from "@/app/messages";
import { setApiLocale } from "@/api/client";

type Theme = "light" | "dark" | "system";
type Locale = "zh-CN" | "en-US";

const STORAGE_KEY = "mosael.preferences";




type PreferencesContextValue = {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey) => string;
};

const PreferencesContext = React.createContext<PreferencesContextValue | null>(null);

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = React.useState<Theme>(() => readPreferences().theme);
  const [locale, setLocaleState] = React.useState<Locale>(() => readPreferences().locale);
  // 语言变了要告诉 api client:后端也有自己要翻的文案,而它靠请求头知道该说哪一种。
  React.useEffect(() => setApiLocale(locale), [locale]);

  React.useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const effective = theme === "system" ? (media.matches ? "dark" : "light") : theme;
      document.documentElement.classList.toggle("dark", effective === "dark");
      document.documentElement.dataset.theme = effective;
    };
    apply();
    document.documentElement.lang = locale;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme, locale }));
    if (theme === "system") {
      media.addEventListener("change", apply);
      return () => media.removeEventListener("change", apply);
    }
  }, [theme, locale]);

  const value = React.useMemo<PreferencesContextValue>(
    () => ({
      theme,
      setTheme: setThemeState,
      locale,
      setLocale: setLocaleState,
      t: (key) => messages[locale][key],
    }),
    [locale, theme],
  );

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences() {
  const value = React.useContext(PreferencesContext);
  if (!value) throw new Error("usePreferences must be used inside PreferencesProvider");
  return value;
}

export function useI18n() {
  return usePreferences().t;
}

/** 老版本创建的工作区名字是英文字面量;显示层按当前语言归一,不改数据。 */
const LEGACY_DEFAULT_WORKSPACE_NAMES = new Set(["Workspace", "Default workspace", "默认工作区"]);

export function displayWorkspaceName(name: string, t: (key: MessageKey) => string): string {
  return LEGACY_DEFAULT_WORKSPACE_NAMES.has(name) ? t("workspaceDefault") : name;
}

function readPreferences(): { theme: Theme; locale: Locale } {
  if (typeof window === "undefined") return { theme: "light", locale: "zh-CN" };
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<{
      theme: Theme;
      locale: Locale;
    }>;
    return {
      theme: parsed.theme === "dark" || parsed.theme === "system" ? parsed.theme : "light",
      locale: parsed.locale === "en-US" ? "en-US" : "zh-CN",
    };
  } catch {
    return { theme: "light", locale: "zh-CN" };
  }
}
