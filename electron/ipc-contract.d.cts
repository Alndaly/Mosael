export const IPC: {
  readonly invoke: Readonly<{
    checkUpdates: "mosael:check-updates";
    recordingStatus: "recording-permissions:status";
    recordingRequest: "recording-permissions:request";
    recordingOpenSettings: "recording-permissions:open-settings";
    getOpenAtLogin: "system:getOpenAtLogin";
    setOpenAtLogin: "system:setOpenAtLogin";
    customCssRead: "customCss:read";
    customCssPath: "customCss:path";
    customCssOpen: "customCss:open";
    customCssReveal: "customCss:reveal";
    publishLogin: "publish:login";
    publishOpenPage: "publish:openPage";
    publishInspect: "publish:inspect";
    publishNavigate: "publish:navigate";
    publishBack: "publish:back";
    publishForward: "publish:forward";
    publishReload: "publish:reload";
    publishHideView: "publish:hideView";
    publishPanelLayout: "publish:panelLayout";
    publishClosePanel: "publish:closePanel";
    browserOpenLogin: "browser:openLogin";
  }>;
  readonly send: Readonly<{
    titleOverlay: "mosael:title-overlay";
    systemStatus: "system:status";
    systemNotify: "system:notify";
  }>;
  readonly event: Readonly<{
    fullscreen: "mosael:fullscreen";
    openTasks: "mosael:open-tasks";
    deepLink: "mosael:deep-link";
    openFiles: "mosael:open-files";
    updateAvailable: "mosael:update-available";
    customCss: "mosael:custom-css";
    publishView: "publish:view";
    publishPanels: "publish:panels";
    browserFrame: "browser:frame";
  }>;
};

export function parsePublishTarget(value: unknown, channel: string): { accountId: string; platform: string };
export function parseUrlRequest(value: unknown, channel: string): { url: string };
export function parsePanelId(value: unknown): { id: string };
export function parsePanelLayout(value: unknown): Partial<Record<"x" | "y" | "width" | "height", number>>;
export function parseBrowserLogin(value: unknown): {
  partition: string;
  url: string;
  name: string;
  proxy: string | null;
};
export function parseTitleOverlay(value: unknown): { color: string; symbolColor: string };
export function parseSystemStatus(value: unknown): { runningJobs: number; progress?: number | null };
export function parseTaskNotice(value: unknown): { title: string; body: string };
