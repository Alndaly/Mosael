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

interface Window {
  mibuPublish?: MibuPublishBridge;
  mibuDesktop?: {
    platform: string;
    setTitleOverlay?: (colors: { color: string; symbolColor: string }) => void;
  };
}
