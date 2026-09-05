import React from "react";

import { messages, type MessageKey } from "@/app/messages";
import { setApiLocale } from "@/api/client";

type Theme = "light" | "dark" | "system";
type Locale = "zh-CN" | "en-US";

const STORAGE_KEY = "mosael.preferences";




type PreferencesContextValue = {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  /** 免提浮标浮不浮着。本地偏好 —— 见 provider 里那段说明。 */
  voiceDock: boolean;
  setVoiceDock: (on: boolean) => void;
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey) => string;
};

const PreferencesContext = React.createContext<PreferencesContextValue | null>(null);

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = React.useState<Theme>(() => readPreferences().theme);
  const [locale, setLocaleState] = React.useState<Locale>(() => readPreferences().locale);
  //: 免提浮标要不要浮着。**本地偏好**:同一个账号在两台机器上,想不想要一颗浮窗完全可以不同,
  //: 而它不影响任何服务端行为(音色、开不开口那些在 settings/agent-voice)。
  const [voiceDock, setVoiceDockState] = React.useState<boolean>(() => readPreferences().voiceDock);
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
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme, locale, voiceDock }));
    if (theme === "system") {
      media.addEventListener("change", apply);
      return () => media.removeEventListener("change", apply);
    }
  }, [theme, locale, voiceDock]);

  const value = React.useMemo<PreferencesContextValue>(
    () => ({
      theme,
      setTheme: setThemeState,
      voiceDock,
      setVoiceDock: setVoiceDockState,
      locale,
      setLocale: setLocaleState,
      t: (key) => messages[locale][key],
    }),
    [locale, theme, voiceDock],
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

function readPreferences(): { theme: Theme; locale: Locale; voiceDock: boolean } {
  if (typeof window === "undefined") return { theme: "light", locale: "zh-CN", voiceDock: false };
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<{
      theme: Theme;
      locale: Locale;
      voiceDock: boolean;
    }>;
    return {
      theme: parsed.theme === "dark" || parsed.theme === "system" ? parsed.theme : "light",
      locale: parsed.locale === "en-US" ? "en-US" : "zh-CN",
      //: 默认不浮 —— 一颗常驻的浮窗该由人主动要,而不是装完就在那儿。
      voiceDock: parsed.voiceDock === true,
    };
  } catch {
    return { theme: "light", locale: "zh-CN", voiceDock: false };
  }
}
