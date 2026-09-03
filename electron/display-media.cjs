/**
 * Build the grant returned to Electron's display-media handler.
 *
 * Electron exposes system loopback audio through this handler on Windows. On
 * macOS 15+ the native system picker owns that choice and bypasses the handler;
 * older macOS releases do not expose a supported loopback grant here.
 */
function createDisplayMediaGrant(source, { audioRequested, platform = process.platform }) {
  const grant = { video: source };
  if (audioRequested && platform === "win32") grant.audio = "loopback";
  return grant;
}

module.exports = { createDisplayMediaGrant };
