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

function stealthSource(): string {
  const match = SOURCE.match(/const STEALTH_JS = `([\s\S]*?)`;/);
  if (!match) throw new Error("找不到 STEALTH_JS —— 补丁的取法要跟着改");
  return match[1];
}

function runPatches({ platformAuthenticator }: { platformAuthenticator: boolean }) {
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
      PublicKeyCredential: Object.assign(function PublicKeyCredential() {}, {
        isUserVerifyingPlatformAuthenticatorAvailable: () => Promise.resolve(platformAuthenticator),
      }),
      chrome: undefined,
    },
    setTimeout,
    navigator,
    Navigator: { prototype: {} },
    DOMException: FakeDomException,
    Notification: { permission: "default" },
  };
  vm.createContext(context);
  vm.runInContext(stealthSource(), context);
  return context as {
    window: { PublicKeyCredential: Record<string, () => Promise<boolean>> };
    navigator: typeof navigator;
  };
}

describe("内嵌账号视图的页面补丁", () => {
  it("没有平台认证器时,passkey 请求当场被拒", async () => {
    // 没有认证器时剩下的只可能是 hybrid(手机扫码),而 Electron 没有暴露任何挂钩去承载它 ——
    // 请求会那么悬着,页面停在「Verifying it's you…」一直转,右下角那个「Try another way」
    // 得靠用户自己发现。当场 reject,站点自己的回退才接得上。
    const { navigator } = runPatches({ platformAuthenticator: false });
    await expect(navigator.credentials.get({ publicKey: {} })).rejects.toMatchObject({
      name: "NotAllowedError",
    });
  });

  it("有平台认证器时放行 —— 不能把 Touch ID 也一起挡掉", async () => {
    // 上一版是无条件拒绝,那样等于"永远没有 passkey"。签名 + entitlement 到位之后
    // Touch ID 是能用的(见 electron/webauthn.cjs),这里必须让它过去。
    const { navigator } = runPatches({ platformAuthenticator: true });
    await expect(navigator.credentials.get({ publicKey: {} })).resolves.toMatchObject({
      kind: "real-get",
    });
  });

  it("只拦 publicKey —— 密码和联合登录凭据照常走", async () => {
    const { navigator } = runPatches({ platformAuthenticator: false });
    await expect(navigator.credentials.get({ password: true })).resolves.toMatchObject({
      kind: "real-get",
    });
  });

  it("条件式 UI 一律答不可用", async () => {
    // 自动填充里的 passkey 在这里同样没有承载它的界面。答 true 再挂住,比一开始答 false 糟。
    const { window } = runPatches({ platformAuthenticator: true });
    await expect(window.PublicKeyCredential.isConditionalMediationAvailable()).resolves.toBe(false);
  });

  it("反检测那几条还在 —— 只补 Chromium 与 Chrome 确有差别的那几处", () => {
    // 同一段脚本里的东西,别在改 WebAuthn 时把它们碰掉了。
    const script = stealthSource();
    expect(script).toContain("webdriver");
    //: plugins 补成 Chrome 真实报的 PDF Viewer 列表(此前是 Plugin 1/2/3 三个假名字 ——
    //: 反欺诈一比对就是「自称 Chrome、指纹却不是 Chrome」,X 登录一直报错就是栽在这里)。
    expect(script).toContain("PDF Viewer");
    //: WebGL vendor/renderer 与 permissions.query **不再伪造**。谎报 Intel(Apple Silicon 上
    //: 直接矛盾)、返回普通对象冒充 PermissionStatus,都是比不补更糟的破绽;原生值本就与 Chrome
    //: 接近(同为 ANGLE 渲染)。这两处出现 = 有人把旧补丁抄回来了。
    expect(script).not.toContain("WebGLRenderingContext");
    expect(script).not.toContain("permissions.query");
  });
});
