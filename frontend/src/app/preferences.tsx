import React from "react";

import { messages, type MessageKey } from "@/app/messages";
import { INTERFACE_FONTS, loadInterfaceFont, normalizeInterfaceFont, type InterfaceFont } from "@/app/interfaceFonts";
import { useQueryClient } from "@tanstack/react-query";

import { setApiLocale } from "@/api/client";

type Theme = "light" | "dark" | "system";
type Locale = "zh-CN" | "en-US";

const STORAGE_KEY = "mosael.preferences";




type PreferencesContextValue = {
  font: InterfaceFont;
  setFont: (font: InterfaceFont) => void;
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
  const [font, setFontState] = React.useState<InterfaceFont>(() => readPreferences().font);
  React.useLayoutEffect(() => {
    document.documentElement.style.setProperty("--font-sans", INTERFACE_FONTS.find((entry) => entry.id === font)!.family);
    document.documentElement.dataset.font = font;
    void loadInterfaceFont(font).catch(() => { /* Keep the readable fallback if a local font cannot load. */ });
  }, [font]);
  const [theme, setThemeState] = React.useState<Theme>(() => readPreferences().theme);
  const [locale, setLocaleState] = React.useState<Locale>(() => readPreferences().locale);
  //: 免提浮标要不要浮着。**本地偏好**:同一个账号在两台机器上,想不想要一颗浮窗完全可以不同,
  //: 而它不影响任何服务端行为(音色、开不开口那些在 settings/agent-voice)。
  const [voiceDock, setVoiceDockState] = React.useState<boolean>(() => readPreferences().voiceDock);
  /*
   * 语言变了要做两件事。
   *
   * 一是告诉 api client:后端也有自己要翻的文案(插件的字段名、工作流的节点名、发布平台的
   * 说明、任务消息),它靠请求头知道该说哪一种。
   *
   * 二是**把已经缓存的答案作废**。少了这一步,切过语言的页面还留着上一种语言的数据:
   * 插件那几个查询是 `staleTime: Infinity`,不手动刷新页面就永远不会再问一次 —— 实测切到
   * 英文再切回中文,插件详情里仍然写着 `Blender host` / `Connection port`,而后端对
   * `Accept-Language: zh-CN` 明明返回的是「Blender 主机」「连接端口」。
   *
   * 工作流那边是把 locale 拼进 queryKey 解决的(见 WorkflowsView)。那样更精确,但要求**每个**
   * 取后端翻译内容的地方都记得带上它 —— 漏一处就错一处,而漏的那处不会报错。在这里统一作废
   * 一次,是结构上的解法:切语言是低频动作,重新取一遍的代价远小于"混着两种语言"。
   */
  const queryClient = useQueryClient();
  const localeSettled = React.useRef(false);
  React.useEffect(() => {
    setApiLocale(locale);
    // 首次挂载不作废:那时缓存本来就是空的,白跑一趟全量重取。
    if (!localeSettled.current) {
      localeSettled.current = true;
      return;
    }
    void queryClient.invalidateQueries();
  }, [locale, queryClient]);

  React.useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const effective = theme === "system" ? (media.matches ? "dark" : "light") : theme;
      document.documentElement.classList.toggle("dark", effective === "dark");
      document.documentElement.dataset.theme = effective;
    };
    apply();
    document.documentElement.lang = locale;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme, locale, voiceDock, font }));
    if (theme === "system") {
      media.addEventListener("change", apply);
      return () => media.removeEventListener("change", apply);
    }
  }, [theme, locale, voiceDock, font]);

  const value = React.useMemo<PreferencesContextValue>(
    () => ({
      font,
      setFont: setFontState,
      theme,
      setTheme: setThemeState,
      voiceDock,
      setVoiceDock: setVoiceDockState,
      locale,
      setLocale: setLocaleState,
      t: (key) => messages[locale][key],
    }),
    [locale, theme, voiceDock, font],
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

function readPreferences(): { font: InterfaceFont; theme: Theme; locale: Locale; voiceDock: boolean } {
  if (typeof window === "undefined") return { font: "default", theme: "light", locale: "zh-CN", voiceDock: false };
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<{
      font: InterfaceFont;
      theme: Theme;
      locale: Locale;
      voiceDock: boolean;
    }>;
    return {
      font: normalizeInterfaceFont(parsed.font),
      theme: parsed.theme === "dark" || parsed.theme === "system" ? parsed.theme : "light",
      locale: parsed.locale === "en-US" ? "en-US" : "zh-CN",
      //: 默认不浮 —— 一颗常驻的浮窗该由人主动要,而不是装完就在那儿。
      voiceDock: parsed.voiceDock === true,
    };
  } catch {
    return { font: "default", theme: "light", locale: "zh-CN", voiceDock: false };
  }
}
