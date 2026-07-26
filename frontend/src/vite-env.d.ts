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
interface MibuPublishBridge {
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
interface MibuUpdateInfo {
  current?: string;
  latest?: string;
  hasUpdate?: boolean;
  url?: string;
  error?: string;
}

/** 自动化浏览器(RPA / 智能体)的实时预览帧。 */
interface BrowserFrame {
  sessionId: string;
  dataUrl: string;
}

interface Window {
  mibuPublish?: MibuPublishBridge;
  mibuBrowser?: {
    onFrame: (callback: (frame: BrowserFrame) => void) => () => void;
  };
  mibuDesktop?: {
    platform: string;
    setTitleOverlay?: (colors: { color: string; symbolColor: string }) => void;
    onFullscreen?: (callback: (fullscreen: boolean) => void) => () => void;
    checkUpdates?: () => Promise<MibuUpdateInfo>;
    onUpdateAvailable?: (callback: (info: MibuUpdateInfo) => void) => () => void;
  };
}
