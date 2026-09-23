const { execFileSync, spawnSync } = require("node:child_process");
const fs = require("node:fs");
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
// 权限位不在签名的封印范围内,所以上面几道都看不见它。823cd31c 之后云端打的包都是 drwx------
// (打包步骤里一句 umask 077 罩住了整个输出):只有拖它进 /Applications 的那个账户打得开。
const closed = [];
(function walk(entry) {
  const stat = fs.lstatSync(entry);
  if (stat.isSymbolicLink()) return;
  const needs = stat.isDirectory() || stat.mode & 0o100 ? 0o005 : 0o004;
  if ((stat.mode & needs) !== needs) closed.push(`${(stat.mode & 0o777).toString(8)} ${path.relative(appPath, entry) || "."}`);
  if (stat.isDirectory()) for (const name of fs.readdirSync(entry)) walk(path.join(entry, name));
})(appPath);
if (closed.length) throw new Error(`Other macOS accounts cannot open ${closed.length} bundle entries, e.g.\n  ${closed.slice(0, 5).join("\n  ")}`);
if (!signatureOnly) {
  execFileSync("/usr/bin/xcrun", ["stapler", "validate", appPath], { stdio: "inherit" });
  execFileSync("/usr/sbin/spctl", ["--assess", "--type", "execute", "--verbose=2", appPath], { stdio: "inherit" });
}
console.log(`Verified ${signatureOnly ? "signed artifact pending notarization" : "signed, notarized application"} with WebAuthn keychain group: ${group}`);
