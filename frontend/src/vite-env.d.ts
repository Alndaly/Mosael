/// <reference types="vite/client" />

/** 构建时由 vite.config 从 package.json 注入的应用版本号。 */
declare const __APP_VERSION__: string;

/** Electron preload 暴露的发布执行器桥;浏览器环境下为 undefined。 */
interface MibuPublishBridge {
  login: (accountId: string, platform: string) => Promise<void>;
  openPage: (accountId: string, platform: string) => Promise<void>;
  hideView: () => Promise<void>;
  onViewState: (
    callback: (state: { visible: boolean; accountId: string | null; accountName: string | null }) => void,
  ) => () => void;
}

interface Window {
  mibuPublish?: MibuPublishBridge;
}
