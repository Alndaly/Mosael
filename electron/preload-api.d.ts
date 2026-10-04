/** The one type contract shared by the privileged preload implementation and renderer. */

export type RecordingPermissionKind = "camera" | "microphone" | "screen";
export type RecordingPermissionStatus = "not-determined" | "granted" | "denied" | "restricted" | "unknown";

export interface PublishViewState {
  visible: boolean;
  accountId: string | null;
  accountName: string | null;
  url?: string;
  canGoBack?: boolean;
  canGoForward?: boolean;
  loading?: boolean;
  /** 页面标题(页面工具把它记进出处)。 */
  title?: string;
  /** 视图的会话分区:页面工具据此找回对应的浏览器池档案。 */
  partition?: string | null;
}

export interface LivePanelCard {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  header: number;
  radius: number;
  muted: boolean;
  /** 指针停在这张卡片的网页(原生视图)上 —— 渲染层自己看不见那一块。 */
  hovered: boolean;
}

/** 悬浮面板的缩放手柄:四角 + 四边,按罗盘方位命名。 */
export type LivePanelHandle = "n" | "ne" | "e" | "se" | "s" | "sw" | "w" | "nw";

/**
 * 面板几何的一次改动。`{ x, y }`:拖标题条挪到这里。带 `handle`:拖这个手柄缩放,矩形是指针要的
 * 大小与位置(不带约束)—— 比例(宽高联动)、上下限、窗口边界与锚点都由主进程定。
 */
export type LivePanelLayoutChange =
  | { x: number; y: number }
  | { handle: LivePanelHandle; x: number; y: number; width: number; height: number };

export interface MosaelUpdateInfo {
  current?: string;
  latest?: string;
  hasUpdate?: boolean;
  url?: string;
  error?: string;
}

export interface LiveViewFrame {
  sessionId: string;
  dataUrl?: string;
  label?: string;
  url?: string;
  settled?: boolean;
}

export interface MosaelPublishBridge {
  login(accountId: string, platform: string): Promise<void>;
  openPage(accountId: string, platform: string): Promise<void>;
  /** 退出登录:清掉这个账号分区里的 cookie/存储,账号回到「需登录」。 */
  signOut(accountId: string, platform: string): Promise<void>;
  inspect(accountId: string, platform: string): Promise<boolean>;
  navigate(url: string): Promise<void>;
  back(): Promise<void>;
  forward(): Promise<void>;
  reload(): Promise<void>;
  hideView(): Promise<void>;
  onViewState(callback: (state: PublishViewState) => void): () => void;
  onPanels(callback: (cards: LivePanelCard[]) => void): () => void;
  setPanelLayout(change: LivePanelLayoutChange): Promise<void>;
  closePanel(id: string): Promise<void>;
  setPanelMuted(id: string, muted: boolean): Promise<void>;
}

export interface MosaelBrowserBridge {
  onFrame(callback: (frame: LiveViewFrame) => void): () => void;
  openLogin(opts: {
    partition: string;
    url: string;
    name?: string;
    proxy?: string | null;
    /** 视图还开着就原样亮出来(回到上次那一页);否则打开 url。 */
    resume?: boolean;
  }): Promise<{ ok: boolean; error?: string }>;
  /** 清掉一个通用档案里存着的全部登录数据(cookie / 本地存储 / 缓存)。 */
  clearProfile(partition: string): Promise<void>;
}

/** 页面工具作用的那一页。 */
export interface PageToolsPage {
  url: string;
  title: string;
}

/** 一次截屏的结果:PNG 字节 + 出处。 */
export interface PageCaptureResult {
  bytes: Uint8Array;
  width: number;
  height: number;
  /** 整页长图比上限长,只截了前面一段。 */
  truncated: boolean;
  page: PageToolsPage;
  capturedAt: string;
}

export type PageVideoKind = "direct" | "hls" | "dash";

export interface PageVideoCandidate {
  url: string;
  kind: PageVideoKind;
  from: "element" | "network" | "meta";
  mime: string;
  bytes: number | null;
  width: number;
  height: number;
  duration: number | null;
  /** 受保护(DRM / 加密流):不给下载。 */
  protection: "drm" | "encrypted" | null;
}

export interface PageVideoProbe {
  page: PageToolsPage;
  candidates: PageVideoCandidate[];
  /** 页面上有播放器正在放 DRM 内容。 */
  drm: boolean;
  /** 播放器用的是 MSE 分段流,而网络里没看到能下载的地址。 */
  streamOnly: boolean;
}

export interface PageImageEntry {
  url: string;
  width: number;
  height: number;
  alt: string;
}

export type PageFetchedImage =
  | { url: string; ok: true; bytes: Uint8Array; mime: string }
  | { url: string; ok: false; reason: "failed" | "too_large" | "not_image" | "not_listed" };

/**
 * 浏览器会话顶栏的页面工具。**都作用于前台那个内嵌视图**(主进程自己认是哪个)。
 * 失败时 reject 的消息里带 `page-tools: <原因码>`(no_page / capture_failed / full_page_unavailable)。
 */
export interface MosaelPageToolsBridge {
  capture(mode: "visible" | "full"): Promise<PageCaptureResult>;
  /** 框选第一步:冻结画面并藏起网页,交回那一帧。 */
  beginRegion(): Promise<{ frame: string; width: number; height: number }>;
  /** 框选第二步:按比例(0–1)裁出那一块;null 是取消。网页亮回来。 */
  finishRegion(selection: { x: number; y: number; width: number; height: number } | null): Promise<PageCaptureResult | null>;
  probeVideos(): Promise<PageVideoProbe>;
  listImages(): Promise<{ page: PageToolsPage; images: PageImageEntry[] }>;
  /** 只取最近一次 listImages 列出过的地址。 */
  fetchImages(urls: string[]): Promise<PageFetchedImage[]>;
  /** 侧栏开合:网页右侧让出这么宽(像素)。 */
  setInset(right: number): Promise<void>;
}

export interface MosaelDesktopBridge {
  platform: string;
  setTitleOverlay(colors: { color: string; symbolColor: string }): void;
  onFullscreen(callback: (fullscreen: boolean) => void): () => void;
  checkUpdates(): Promise<MosaelUpdateInfo>;
  onUpdateAvailable(callback: (info: MosaelUpdateInfo) => void): () => void;
  reportStatus(status: { runningJobs: number; progress?: number | null }): void;
  notifyTask(notice: { title: string; body?: string }): void;
  getOpenAtLogin(): Promise<{ enabled: boolean; needsApproval: boolean } | null>;
  setOpenAtLogin(enabled: boolean): Promise<{ enabled: boolean; needsApproval: boolean } | null>;
  recordingPermissions: {
    getStatus(kind: RecordingPermissionKind): Promise<RecordingPermissionStatus>;
    request(kind: Exclude<RecordingPermissionKind, "screen">): Promise<boolean | null>;
    openSettings(kind: RecordingPermissionKind): Promise<boolean>;
  };
  data: {
    exportDiagnostics(): Promise<{ status: "saved" | "cancelled"; path?: string }>;
    createBackup(token: string): Promise<{ status: "saved" | "cancelled"; path?: string }>;
    applyRestore(stageId: string): Promise<{ status: "restarting" }>;
  };
  customCss: {
    read(): Promise<string>;
    path(): Promise<string>;
    open(): Promise<string>;
    reveal(): Promise<string>;
    onChange(callback: (css: string) => void): () => void;
  };
}
