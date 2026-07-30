/// <reference types="vite/client" />

/** 构建时由 vite.config 从 package.json 注入的应用版本号。 */
declare const __APP_VERSION__: string;

/** 内嵌发布浏览器的视图状态(工具栏消费):可见性 + 当前地址/导航态。 */
interface PublishViewState {
  visible: boolean;
  accountId: string | null;
  accountName: string | null;
  url?: string;
  canGoBack?: boolean;
  canGoForward?: boolean;
  loading?: boolean;
}

/** Electron preload 暴露的发布执行器桥;浏览器环境下为 undefined。 */
interface OpenStudioPublishBridge {
  login: (accountId: string, platform: string) => Promise<void>;
  openPage: (accountId: string, platform: string) => Promise<void>;
  inspect: (accountId: string, platform: string) => Promise<boolean>;
  navigate: (url: string) => Promise<void>;
  back: () => Promise<void>;
  forward: () => Promise<void>;
  reload: () => Promise<void>;
  hideView: () => Promise<void>;
  onViewState: (callback: (state: PublishViewState) => void) => () => void;
  /** 悬浮卡片几何(主进程按窗口尺寸/叠放算好),渲染层照它画圆角、阴影与标题条。 */
  onPanels?: (callback: (cards: LivePanelCard[]) => void) => () => void;
  /** 拖动/缩放悬浮面板。x/y 是卡片左上角的绝对坐标;主进程会夹到窗口内并落盘。 */
  setPanelLayout?: (patch: { x?: number; y?: number; width?: number; height?: number }) => Promise<void>;
  /** 手动关闭某块面板:只撤面板,任务照常继续跑。 */
  closePanel?: (id: string) => Promise<void>;
}

/**
 * 自动化任务悬浮卡片的几何。原生 WebContentsView 画不了圆角与阴影(Electron 32 的 View 只有
 * setBackgroundColor / setBounds / setVisible),所以外壳由渲染层画在视图**下方** —— 子视图永远盖在
 * 宿主页面之上,于是卡片的圆角边框会在内嵌视图的四周露出来。坐标是窗口内容区的 CSS 像素。
 */
interface LivePanelCard {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  /** 顶部给标题条留出的高度 —— 原生视图从这条下面开始。 */
  header: number;
  radius: number;
}

/** 应用更新检查结果(Electron 主进程查 GitHub Releases)。 */
interface OpenStudioUpdateInfo {
  current?: string;
  latest?: string;
  hasUpdate?: boolean;
  url?: string;
  error?: string;
}

/** 自动化浏览器的实时预览帧。RPA / 智能体会话与发布任务共用这一条通道和同一个面板。 */
interface LiveViewFrame {
  sessionId: string;
  /** 画面。发布任务的后台视图常常取不到像素(见 electron/publish/publishWorker.ts 的 LiveMirror),此时只有步骤文案。 */
  dataUrl?: string;
  /** 当前步骤,如「B站 · 上传视频」。发布任务会带;RPA 会话不带。 */
  label?: string;
  url?: string;
  /** 已到终态(成功/失败):面板据此停掉「运行中」的转圈。 */
  settled?: boolean;
}

interface Window {
  openStudioPublish?: OpenStudioPublishBridge;
  openStudioBrowser?: {
    onFrame: (callback: (frame: LiveViewFrame) => void) => () => void;
    /** 通用池档案登录:在该档案分区开 app 内嵌视图登任意站点(与发布登录同一套视图),cookie 落分区。 */
    openLogin?: (opts: { partition: string; url: string; name?: string; proxy?: string | null }) => Promise<{ ok: boolean; error?: string }>;
  };
  openStudioDesktop?: {
    platform: string;
    setTitleOverlay?: (colors: { color: string; symbolColor: string }) => void;
    onFullscreen?: (callback: (fullscreen: boolean) => void) => () => void;
    checkUpdates?: () => Promise<OpenStudioUpdateInfo>;
    onUpdateAvailable?: (callback: (info: OpenStudioUpdateInfo) => void) => () => void;
    /** 把运行中的任务数推给主进程:托盘文案 + 有任务时阻止系统睡眠。 */
    reportStatus?: (status: { runningJobs: number; progress?: number | null }) => void;
    /** 任务结束时告知系统层;窗口有焦点时主进程会跳过(应用内已有 toast)。 */
    notifyTask?: (notice: { title: string; body?: string }) => void;
    getOpenAtLogin?: () => Promise<boolean | null>;
    setOpenAtLogin?: (enabled: boolean) => Promise<boolean | null>;
  };
}
