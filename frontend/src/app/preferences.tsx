import React from "react";

import { messages, type MessageKey } from "@/app/messages";

type Theme = "light" | "dark";
type Locale = "zh-CN" | "en-US";

const STORAGE_KEY = "mibu.preferences";




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

  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.dataset.theme = theme;
    document.documentElement.lang = locale;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme, locale }));
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

function readPreferences(): { theme: Theme; locale: Locale } {
  if (typeof window === "undefined") return { theme: "light", locale: "zh-CN" };
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<{
      theme: Theme;
      locale: Locale;
    }>;
    return {
      theme: parsed.theme === "dark" ? "dark" : "light",
      locale: parsed.locale === "en-US" ? "en-US" : "zh-CN",
    };
  } catch {
    return { theme: "light", locale: "zh-CN" };
  }
}
