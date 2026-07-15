import React from "react";

type Theme = "light" | "dark";
type Locale = "zh-CN" | "en-US";

const STORAGE_KEY = "mibu.preferences";

const messages = {
  "zh-CN": {
    workspaceDefault: "默认工作区",
    projectDefault: "第一个项目",
    connecting: "正在连接后端...",
    welcomeText: "先创建一个工作区，开始搭建新的 AI 视频创作工作台。",
    createWorkspace: "创建默认工作区",
    noProject: "还没有项目",
    createProject: "新建项目",
    navEditor: "剪辑",
    navAi: "AI Studio",
    navScheduler: "定时任务",
    navPlugins: "插件",
    themeLight: "昼",
    themeDark: "夜",
    languageZh: "中",
    languageEn: "EN",
    emptyProject: "创建项目后开始剪辑",
    media: "素材",
    import: "导入",
    sample: "示例",
    sampleAsset: "示例素材",
    mainSequence: "主时间线",
    inspector: "检查器",
    sequence: "时间线",
    revision: "Revision",
    format: "规格",
    createMainSequence: "创建主时间线",
    emptyTimeline: "创建时间线后可拖入素材",
    aiDescription: "统一管理图片、视频生成模型和生成任务。",
    generateImage: "生成图片",
    generateVideo: "生成视频",
    models: "模型",
    generationQueue: "生成队列",
    noGenerationJobs: "还没有生成任务",
    schedulerTitle: "定时任务",
    schedulerDescription: "把渲染、生成、素材检查等后台工作统一排队。",
    createTask: "新建任务",
    hourlyRenderCheck: "每小时渲染检查",
    tasks: "任务",
    recentJobs: "最近 Job",
    noTasks: "还没有定时任务",
    noJobs: "还没有后台任务",
    manual: "manual",
    pluginsTitle: "插件",
    pluginsDescription: "扫描本地 manifest，暴露 Skill 和 Tool 给应用与外部智能体。",
    scanPlugins: "扫描插件",
    installed: "已安装",
    tools: "工具",
    invocations: "调用记录",
    grant: "授权",
    enabled: "已启用",
    enable: "启用",
    invoke: "调用",
    noPlugins: "把插件目录放到 ~/.mibu-new/plugins 后点击扫描",
    noTools: "启用并授权插件后会显示可调用工具",
    noInvocations: "还没有工具调用记录",
    noPermissions: "无需权限",
    permissions: "权限",
  },
  "en-US": {
    workspaceDefault: "Default workspace",
    projectDefault: "First project",
    connecting: "Connecting to backend...",
    welcomeText: "Create a workspace to start building the new AI video studio.",
    createWorkspace: "Create workspace",
    noProject: "No project yet",
    createProject: "New project",
    navEditor: "Edit",
    navAi: "AI Studio",
    navScheduler: "Schedule",
    navPlugins: "Plugins",
    themeLight: "Light",
    themeDark: "Dark",
    languageZh: "中",
    languageEn: "EN",
    emptyProject: "Create a project to start editing",
    media: "Media",
    import: "Import",
    sample: "Sample",
    sampleAsset: "Sample asset",
    mainSequence: "Main timeline",
    inspector: "Inspector",
    sequence: "Timeline",
    revision: "Revision",
    format: "Format",
    createMainSequence: "Create timeline",
    emptyTimeline: "Create a timeline before adding media",
    aiDescription: "Manage image and video generation models and jobs.",
    generateImage: "Generate image",
    generateVideo: "Generate video",
    models: "Models",
    generationQueue: "Generation queue",
    noGenerationJobs: "No generation jobs",
    schedulerTitle: "Scheduler",
    schedulerDescription: "Queue renders, generation, and media checks as background work.",
    createTask: "New task",
    hourlyRenderCheck: "Hourly render check",
    tasks: "Tasks",
    recentJobs: "Recent jobs",
    noTasks: "No scheduled tasks",
    noJobs: "No background jobs",
    manual: "manual",
    pluginsTitle: "Plugins",
    pluginsDescription: "Scan local manifests and expose Skills and Tools to the app and agents.",
    scanPlugins: "Scan plugins",
    installed: "Installed",
    tools: "Tools",
    invocations: "Invocations",
    grant: "Grant",
    enabled: "Enabled",
    enable: "Enable",
    invoke: "Invoke",
    noPlugins: "Place plugins in ~/.mibu-new/plugins, then scan",
    noTools: "Enabled and approved plugins will expose tools here",
    noInvocations: "No tool invocations",
    noPermissions: "No permissions",
    permissions: "permissions",
  },
} as const;

type MessageKey = keyof typeof messages["zh-CN"];

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
