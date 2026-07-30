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
  };
}
