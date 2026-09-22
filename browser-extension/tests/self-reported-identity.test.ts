import { afterEach, describe, expect, it, vi } from "vitest";

import { MosaelClient } from "../src/mosael/client";

/**
 * 扩展在请求头里自报的两件事,此前**两件都不是真的**。
 *
 * · `X-Mosael-Client` 发的是字面量 `"browser-extension"`,而桌面端发的是版本号 —— 同一栏
 *   两个意思。后端原样存进 `auth_sessions.client_version`,管理页照着渲染 `v{...}`,
 *   于是扩展用户那一行写着「vbrowser-extension」。两边各自都"对",错在没人定义过这一栏是什么。
 * · `Accept-Language` 写死 `zh-CN`。后端的任务消息、节点名、错误文案都按它翻(core/i18n),
 *   于是英文用户在扩展里收到的每一句后端文案都是中文 —— 而扩展自己的界面跟着浏览器语言走,
 *   两半对不上,并且没有任何地方会报错。
 */

async function callOnce(): Promise<Headers> {
  const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
    new Response("{}", { headers: { "Content-Type": "application/json" } }),
  );
  const client = new MosaelClient({ baseUrl: "http://127.0.0.1:8800", token: "session", fetcher });
  await client.logout();
  return new Headers(fetcher.mock.calls[0]?.[1]?.headers);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("扩展自报的身份", () => {
  it("版本取自 manifest,语法是 <界面>/<版本>", async () => {
    vi.stubGlobal("chrome", { runtime: { getManifest: () => ({ version: "0.1.0" }) } });

    expect((await callOnce()).get("X-Mosael-Client")).toBe("browser-extension/0.1.0");
  });

  it("报不出版本时干脆不报,而不是编一个", async () => {
    // 构建脚本和单元测试不在扩展上下文里,chrome 不存在。"不知道"是后端认的合法状态。
    vi.stubGlobal("chrome", undefined);

    expect((await callOnce()).has("X-Mosael-Client")).toBe(false);
  });

  it("语言跟着浏览器,而不是写死中文", async () => {
    vi.stubGlobal("chrome", { i18n: { getUILanguage: () => "en-US" } });

    expect((await callOnce()).get("Accept-Language")).toBe("en-US");
  });

  it("没有 chrome.i18n 时退到 navigator.language", async () => {
    vi.stubGlobal("chrome", undefined);
    vi.stubGlobal("navigator", { language: "ja-JP" });

    expect((await callOnce()).get("Accept-Language")).toBe("ja-JP");
  });
});
