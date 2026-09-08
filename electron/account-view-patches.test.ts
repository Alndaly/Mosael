/**
 * 内嵌账号视图注进页面主世界的那段补丁(`account-view-preload.cjs` 的 STEALTH_JS)。
 *
 * 它是一段字符串,平时没有任何东西会执行它 —— 写错了只会表现为"某个平台的登录页行为怪怪的",
 * 而那种问题谁也不会想到来看这里。所以这里把字符串取出来,在一个假页面里真的跑一遍。
 *
 * 重点是 **WebAuthn 那一段**:内嵌视图里 passkey 三条路都走不通(平台认证器默认不受理、
 * 手机跨设备要一个 Electron 不提供的选择界面、多凭据选择没有监听者),而 Chromium 不会替我们
 * 报错 —— 页面就停在「Complete sign-in using your passkey」一直转。当场 reject 之后,
 * 站点自己的回退(密码 + 两步验证)才接得上。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

import { describe, expect, it } from "vitest";

const SOURCE = fs.readFileSync(
  path.resolve(__dirname, "account-view-preload.cjs"),
  "utf8",
);

function runPatches() {
  const match = SOURCE.match(/const STEALTH_JS = `([\s\S]*?)`;/);
  if (!match) throw new Error("找不到 STEALTH_JS —— 补丁的取法要跟着改");
  class FakeDomException extends Error {
    constructor(message: string, name: string) {
      super(message);
      this.name = name;
    }
  }
  const credentials = {
    get: async (options?: unknown) => ({ kind: "real-get", options }),
    create: async (options?: unknown) => ({ kind: "real-create", options }),
  };
  const navigator = {
    credentials,
    permissions: null,
    plugins: [] as unknown[],
    languages: ["en"],
  };
  const context: Record<string, unknown> = {
    window: {
      PublicKeyCredential: function PublicKeyCredential() {},
      chrome: undefined,
    },
    navigator,
    Navigator: { prototype: {} },
    DOMException: FakeDomException,
    Notification: { permission: "default" },
  };
  vm.createContext(context);
  vm.runInContext(match[1], context);
  return context as {
    window: { PublicKeyCredential: Record<string, () => Promise<boolean>> };
    navigator: typeof navigator;
  };
}

describe("内嵌账号视图的页面补丁", () => {
  it("passkey 请求当场被拒,而不是一直挂着", async () => {
    // 挂着才是最坏的:用户盯着一个转圈的「Verifying it's you…」,而右下角那个
    // 「Try another way」要靠他自己发现。
    const { navigator } = runPatches();
    await expect(navigator.credentials.get({ publicKey: {} })).rejects.toMatchObject({
      name: "NotAllowedError",
    });
    await expect(navigator.credentials.create({ publicKey: {} })).rejects.toMatchObject({
      name: "NotAllowedError",
    });
  });

  it("只拦 publicKey —— 密码和联合登录凭据照常走", async () => {
    const { navigator } = runPatches();
    await expect(navigator.credentials.get({ password: true })).resolves.toMatchObject({
      kind: "real-get",
    });
  });

  it("如实回答「这里没有认证器」", async () => {
    // 站点是先问再决定要不要走 passkey 的。答 true 再失败,比一开始就答 false 糟得多。
    const { window } = runPatches();
    await expect(
      window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable(),
    ).resolves.toBe(false);
    await expect(window.PublicKeyCredential.isConditionalMediationAvailable()).resolves.toBe(false);
  });

  it("反检测那几条还在", async () => {
    // 同一段脚本里的东西,别在改 WebAuthn 时把它们碰掉了。
    expect(SOURCE).toContain("webdriver");
    expect(SOURCE).toContain("WebGLRenderingContext");
  });
});
