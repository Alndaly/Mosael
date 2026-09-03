const BROWSER_DEVICE_ALIASES = new Set(["default", "communications"]);

/**
 * `enumerateDevices()` may expose browser-managed aliases alongside the physical devices.
 * The recorder already owns one synthetic “system default” option, so keeping those aliases
 * would duplicate the same device and can create two Select items with the same value.
 */
export function selectableRecordingDevices(
  devices: readonly MediaDeviceInfo[],
  kind: "audioinput" | "videoinput",
): MediaDeviceInfo[] {
  const seen = new Set<string>();
  return devices.filter((device) => {
    if (device.kind !== kind || !device.deviceId || BROWSER_DEVICE_ALIASES.has(device.deviceId)) return false;
    if (seen.has(device.deviceId)) return false;
    seen.add(device.deviceId);
    return true;
  });
}
