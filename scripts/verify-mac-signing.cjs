const { execFileSync } = require("node:child_process");
const path = require("node:path");
const { readWebAuthnKeychainGroup } = require("../electron/mac-signature.cjs");
const { build } = require("../package.json");

const appPath = process.argv[2];
if (process.platform !== "darwin" || !appPath) {
  throw new Error("Usage on macOS: node scripts/verify-mac-signing.cjs /path/to/Mosael.app");
}
execFileSync("/usr/bin/codesign", ["--verify", "--deep", "--strict", appPath], { stdio: "inherit" });
const group = readWebAuthnKeychainGroup(path.join(appPath, "Contents/MacOS/Mosael"), build.appId);
if (!group) throw new Error("The installed signature does not authorize Mosael's WebAuthn keychain group");
execFileSync("/usr/bin/xcrun", ["stapler", "validate", appPath], { stdio: "inherit" });
execFileSync("/usr/sbin/spctl", ["--assess", "--type", "execute", "--verbose=2", appPath], { stdio: "inherit" });
console.log(`Verified signed, notarized application with WebAuthn keychain group: ${group}`);
