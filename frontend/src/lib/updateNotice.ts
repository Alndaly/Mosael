import { toast } from "sonner";

import type { MessageKey } from "@/app/messages";

/**
 * 应用内更新的提示只有一处:发现新版本、下载进度、下载完成都用同一个 toast id,
 * 后一步直接替换前一步,不会在右下角叠出两条互相打架的提示。
 *
 * 「打开发布页」只用于开发版 / 未打包环境:那里没有 electron-updater,不能下载安装。
 * 安装版一律走应用内下载,不把用户送去网页手动下载。
 */
type Translate = (key: MessageKey) => string;
type UpdateInfo = MosaelUpdateInfo;

const UPDATE_TOAST_ID = "mosael-app-update";
const AVAILABLE_DURATION = 15000;
const DOWNLOADING_DURATION = 10 * 60 * 1000;

export function supportsInAppUpdate(info: UpdateInfo | null | undefined): boolean {
  return Boolean(
    info?.supportsAutoInstall &&
      window.mosaelDesktop?.downloadUpdate &&
      window.mosaelDesktop?.installUpdate,
  );
}

function releaseUrl(info: UpdateInfo): string | undefined {
  return info.url || undefined;
}

function showDownloadError(t: Translate, info: UpdateInfo, message: string): void {
  const open = info.manualUrl
    ? { label: t("updateManualDownload"), url: info.manualUrl }
    : info.url
      ? { label: t("updateOpenRelease"), url: info.url }
      : null;
  toast.error(message, {
    id: UPDATE_TOAST_ID,
    description: info.error,
    action: open ? { label: open.label, onClick: () => window.open(open.url, "_blank") } : undefined,
  });
}

function showDeferred(t: Translate): void {
  toast(t("updateJobsRunning"), {
    id: UPDATE_TOAST_ID,
    description: t("updateInstallHint"),
    duration: AVAILABLE_DURATION,
    action: { label: t("updateInstallNow"), onClick: () => void startUpdateInstall(t) },
  });
}

export function announceUpdate(t: Translate, info: UpdateInfo): void {
  if (!info?.hasUpdate) return;
  const auto = supportsInAppUpdate(info);
  const url = releaseUrl(info);
  toast(t("updateAvailable").replace("{version}", info.latest ?? ""), {
    id: UPDATE_TOAST_ID,
    duration: AVAILABLE_DURATION,
    description: auto ? t("updateDownloadHint") : t("updateUnsupportedHint"),
    action: auto
      ? { label: t("updateDownload"), onClick: () => void startUpdateDownload(t) }
      : url
        ? { label: t("updateOpenRelease"), onClick: () => window.open(url, "_blank") }
        : undefined,
  });
}

export async function startUpdateDownload(t: Translate): Promise<UpdateInfo | undefined> {
  const download = window.mosaelDesktop?.downloadUpdate;
  if (!download) return undefined;
  toast.loading(t("updateDownloading").replace("{percent}", "0"), {
    id: UPDATE_TOAST_ID,
    duration: DOWNLOADING_DURATION,
  });
  try {
    const next = await download();
    if (next.error) showDownloadError(t, next, t("updateDownloadFailed"));
    return next;
  } catch (cause) {
    showDownloadError(
      t,
      { error: String((cause as Error)?.message ?? cause) },
      t("updateDownloadFailed"),
    );
    return undefined;
  }
}

export async function startUpdateInstall(t: Translate): Promise<UpdateInfo | undefined> {
  const install = window.mosaelDesktop?.installUpdate;
  if (!install) return undefined;
  try {
    const next = await install();
    if (next.error === "update_jobsRunning") showDeferred(t);
    else if (next.error) showDownloadError(t, next, t("updateInstallFailed"));
    return next;
  } catch (cause) {
    showDownloadError(
      t,
      { error: String((cause as Error)?.message ?? cause) },
      t("updateInstallFailed"),
    );
    return undefined;
  }
}

export function showUpdateProgress(t: Translate, info: UpdateInfo): void {
  switch (info.phase) {
    case "downloading":
      toast.loading(t("updateDownloading").replace("{percent}", String(info.percent ?? 0)), {
        id: UPDATE_TOAST_ID,
        duration: DOWNLOADING_DURATION,
      });
      break;
    case "downloaded":
      toast.success(t("updateDownloaded").replace("{version}", info.latest ?? ""), {
        id: UPDATE_TOAST_ID,
        description: t("updateInstallHint"),
        duration: Infinity,
        action: { label: t("updateInstallNow"), onClick: () => void startUpdateInstall(t) },
      });
      break;
    case "deferred":
      showDeferred(t);
      break;
    case "error":
      showDownloadError(t, info, t("updateDownloadFailed"));
      break;
  }
}
