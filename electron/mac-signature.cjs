const { spawnSync } = require("node:child_process");

/** Read the installed executable's signature, not the build machine's environment. */
function readWebAuthnKeychainGroup(executable, bundleId, run = spawnSync) {
  const options = { encoding: "utf8", timeout: 5000, maxBuffer: 1024 * 1024 };
  try {
    const verified = run("/usr/bin/codesign", ["--verify", "--strict", executable], options);
    if (verified.status !== 0) return "";
    const signature = run("/usr/bin/codesign", [
      "--display", "--verbose=4", "--entitlements", ":-", "--xml", executable,
    ], options);
    if (signature.status !== 0) return "";
    const team = /^TeamIdentifier=([A-Z0-9]{10})$/m.exec(signature.stderr)?.[1];
    if (!team) return "";
    const plist = run("/usr/bin/plutil", ["-convert", "json", "-o", "-", "-"], {
      ...options, input: signature.stdout,
    });
    if (plist.status !== 0) return "";
    const entitlements = JSON.parse(plist.stdout);
    const group = `${team}.${bundleId}.webauthn`;
    if (entitlements["com.apple.application-identifier"] !== `${team}.${bundleId}`) return "";
    if (entitlements["com.apple.developer.team-identifier"] !== team) return "";
    return Array.isArray(entitlements["keychain-access-groups"])
      && entitlements["keychain-access-groups"].includes(group) ? group : "";
  } catch {
    // An unsigned development build or unavailable signature must not prevent startup.
    return "";
  }
}

module.exports = { readWebAuthnKeychainGroup };
