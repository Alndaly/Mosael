/// <reference types="vite/client" />

/** 构建时由 vite.config 从 package.json 注入的应用版本号。 */
declare const __APP_VERSION__: string;

interface ImportMetaEnv {
  /** 这一份前端连哪台后端(见 api/transport.resolveApiBase):隔离环境、截图脚本起 Vite / 构建时给;打包发版不给。 */
  readonly VITE_MOSAEL_API_URL?: string;
}

type PublishViewState = import("../../electron/preload-api").PublishViewState;
type LivePanelCard = import("../../electron/preload-api").LivePanelCard;
type LivePanelHandle = import("../../electron/preload-api").LivePanelHandle;
type MosaelUpdateInfo = import("../../electron/preload-api").MosaelUpdateInfo;
type LiveViewFrame = import("../../electron/preload-api").LiveViewFrame;
type RecordingPermissionKind = import("../../electron/preload-api").RecordingPermissionKind;
type RecordingPermissionStatus = import("../../electron/preload-api").RecordingPermissionStatus;
/** ComfyUI 工作台的桥那边看到的(主进程规整过,见 electron/publish/comfyWorkbench)。 */
type ComfyWorkbenchState = import("../../electron/preload-api").ComfyWorkbenchState;
type ComfyWorkbenchEvent = import("../../electron/preload-api").ComfyWorkbenchEvent;
type ComfyWorkbenchExport = import("../../electron/preload-api").ComfyWorkbenchExport;
type ComfyWorkbenchCall = import("../../electron/preload-api").ComfyWorkbenchCall;
type ComfyWorkbenchCallResult = import("../../electron/preload-api").ComfyWorkbenchCallResult;

interface Window {
  mosaelPublish?: import("../../electron/preload-api").MosaelPublishBridge;
  mosaelBrowser?: import("../../electron/preload-api").MosaelBrowserBridge;
  mosaelDesktop?: import("../../electron/preload-api").MosaelDesktopBridge;
  mosaelPageTools?: import("../../electron/preload-api").MosaelPageToolsBridge;
}
