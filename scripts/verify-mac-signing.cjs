const { execFileSync, spawnSync } = require("node:child_process");
const path = require("node:path");
const { readWebAuthnKeychainGroup } = require("../electron/mac-signature.cjs");
const { build } = require("../package.json");

const appPath = process.argv[2];
const signatureOnly = process.argv[3] === "--signature-only";
if (process.platform !== "darwin" || !appPath || (process.argv[3] && !signatureOnly)) {
  throw new Error("Usage on macOS: node scripts/verify-mac-signing.cjs /path/to/Mosael.app [--signature-only]");
}
execFileSync("/usr/bin/codesign", ["--verify", "--deep", "--strict", appPath], { stdio: "inherit" });
const group = readWebAuthnKeychainGroup(path.join(appPath, "Contents/MacOS/Mosael"), build.appId);
if (!group) throw new Error("The installed signature does not authorize Mosael's WebAuthn keychain group");
const metadata = spawnSync("/usr/bin/codesign", ["--display", "--verbose=4", appPath], { encoding: "utf8" });
if (metadata.status !== 0 || !/^Timestamp=.+$/m.test(metadata.stderr)) throw new Error("Signed release application is missing its secure timestamp");
if (!signatureOnly) {
  execFileSync("/usr/bin/xcrun", ["stapler", "validate", appPath], { stdio: "inherit" });
  execFileSync("/usr/sbin/spctl", ["--assess", "--type", "execute", "--verbose=2", appPath], { stdio: "inherit" });
}
console.log(`Verified ${signatureOnly ? "signed artifact pending notarization" : "signed, notarized application"} with WebAuthn keychain group: ${group}`);
