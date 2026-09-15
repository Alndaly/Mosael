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
}

export interface LivePanelCard {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  header: number;
  radius: number;
}

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
  inspect(accountId: string, platform: string): Promise<boolean>;
  navigate(url: string): Promise<void>;
  back(): Promise<void>;
  forward(): Promise<void>;
  reload(): Promise<void>;
  hideView(): Promise<void>;
  onViewState(callback: (state: PublishViewState) => void): () => void;
  onPanels(callback: (cards: LivePanelCard[]) => void): () => void;
  setPanelLayout(patch: { x?: number; y?: number; width?: number; height?: number }): Promise<void>;
  closePanel(id: string): Promise<void>;
}

export interface MosaelBrowserBridge {
  onFrame(callback: (frame: LiveViewFrame) => void): () => void;
  openLogin(opts: {
    partition: string;
    url: string;
    name?: string;
    proxy?: string | null;
  }): Promise<{ ok: boolean; error?: string }>;
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

