/// <reference types="vite/client" />

/** 构建时由 vite.config 从 package.json 注入的应用版本号。 */
declare const __APP_VERSION__: string;

type PublishViewState = import("../../electron/preload-api").PublishViewState;
type LivePanelCard = import("../../electron/preload-api").LivePanelCard;
type MosaelUpdateInfo = import("../../electron/preload-api").MosaelUpdateInfo;
type LiveViewFrame = import("../../electron/preload-api").LiveViewFrame;
type RecordingPermissionKind = import("../../electron/preload-api").RecordingPermissionKind;
type RecordingPermissionStatus = import("../../electron/preload-api").RecordingPermissionStatus;

interface Window {
  mosaelPublish?: import("../../electron/preload-api").MosaelPublishBridge;
  mosaelBrowser?: import("../../electron/preload-api").MosaelBrowserBridge;
  mosaelDesktop?: import("../../electron/preload-api").MosaelDesktopBridge;
}
