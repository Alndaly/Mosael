export const FRAME_CAPTURE_ORIGINS = ["<all_urls>"];

type PermissionRequester = (permissions: chrome.permissions.Permissions) => Promise<boolean>;

/**
 * A side panel can outlive the temporary `activeTab` grant that opened it. Request the
 * screenshot-only fallback permission while the capture button's user gesture is still active.
 */
export function requestFrameCapturePermission(
  requestPermission: PermissionRequester = (permissions) => chrome.permissions.request(permissions),
): Promise<boolean> {
  return requestPermission({ origins: [...FRAME_CAPTURE_ORIGINS] });
}
