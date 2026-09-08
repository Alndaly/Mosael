/**
 * 内嵌浏览器里的 passkey 接线。
 *
 * 这条链**今天开不起来**(应用未签名),所以它更需要被盯着:一个开不起来的功能,写错了也
 * 没有任何地方会报错 —— 等到哪天真去签名,才发现 keychain group 和 entitlement 对不上,
 * 而那时的症状只是"Touch ID 没反应"。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const SOURCE = fs.readFileSync(path.join(ROOT, "electron/webauthn.cjs"), "utf8");
const ENTITLEMENTS = fs.readFileSync(path.join(ROOT, "build/entitlements.mac.plist"), "utf8");
const PACKAGE = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));

describe("passkey 的三个前提", () => {
  it("keychain group 和 entitlement、appId 三处对得上", () => {
    // 传给 configureWebAuthn 的 group **必须**出现在 entitlement 里,而它是拿 appId 拼的。
    // 三处任意一处改了名字而另两处没跟上,结果都是"静默不生效"。
    const appId = PACKAGE.build.appId as string;
    expect(SOURCE).toContain(`const BUNDLE_ID = "${appId}"`);
    expect(SOURCE).toContain("${TEAM_ID}.${BUNDLE_ID}.webauthn");
    expect(ENTITLEMENTS).toContain(`${appId}.webauthn`);
    expect(ENTITLEMENTS).toContain("keychain-access-groups");
  });

  it("打包配置真的会带上这份 entitlement", () => {
    // 文件写好了但没挂进 build.mac,等于没写。
    expect(PACKAGE.build.mac.entitlements).toBe("build/entitlements.mac.plist");
    expect(PACKAGE.build.mac.entitlementsInherit).toBe("build/entitlements.mac.plist");
    expect(PACKAGE.build.mac.hardenedRuntime).toBe(true);
  });

  it("hardened runtime 下 Electron 起得来", () => {
    // 少了这三条,签名之后渲染进程直接起不来 —— 比 passkey 用不了严重得多。
    for (const key of [
      "com.apple.security.cs.allow-jit",
      "com.apple.security.cs.allow-unsigned-executable-memory",
      "com.apple.security.cs.disable-library-validation",
    ])
      expect(ENTITLEMENTS).toContain(key);
  });

  it("没签名时不去调 configureWebAuthn,而不是调了再失败", () => {
    // 没有 TEAM_ID 就没有合法的 group。调一次抛一次异常没有意义,日志里还多一条噪音。
    expect(SOURCE).toContain("if (!TEAM_ID) return \"\"");
    expect(SOURCE).toContain("process.platform !== \"darwin\"");
  });
});

describe("多凭据选择", () => {
  it("一定会回调,包括出错的那一路", () => {
    // **不回调请求就永远挂着** —— 正是这一整轮要消灭的那种状态。
    const handler = SOURCE.slice(SOURCE.indexOf("select-webauthn-account"));
    expect(handler).toContain("callback(accounts[0]?.credentialId)");
    expect(handler).toContain("callback(picked < labels.length");
    expect(handler.slice(handler.indexOf("catch"))).toContain("callback(undefined)");
  });

  it("每个分区只接一次", () => {
    // openView 和 configureAccount 都会调它,重复接会让一次请求弹出多个选择框。
    expect(SOURCE).toContain("__mosaelWebauthnBound");
  });
});
