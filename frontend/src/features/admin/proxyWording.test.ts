import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";

/**
 * 出站代理「留空」是什么意思(体检 D57,维护者 2026-10-09 拍板):**跟随系统代理,本机地址始终直连。**
 *
 * 此前写的是「留空 = 直连」,可后端在代理留空时只是把进程里的代理环境变量清掉 —— httpx 接着就去读系统代理设置
 * (macOS、Windows),开着 Clash 之类系统代理的机器上请求照样走代理;只有本机地址(回连、本机的 Ollama / ComfyUI)
 * 一律直连(见 backend core/http_retry.loopback_direct、domain/network)。说「直连」的人会以为关掉了代理。
 * 真正的「直连」选项以后另做;这里先把话说对。
 */
describe("出站代理留空的说法", () => {
  it("中文:跟随系统代理,本机地址始终直连", () => {
    const zh = messages["zh-CN"];
    for (const text of [zh.proxyDesc, zh.proxyUrlDesc]) {
      expect(text).toContain("留空 = 跟随系统代理(本机地址始终直连)");
      expect(text).not.toMatch(/留空\s*(=|为)\s*直连/);
    }
  });

  it("英文同一个意思", () => {
    const en = messages["en-US"];
    for (const text of [en.proxyDesc, en.proxyUrlDesc]) {
      expect(text).toContain("Empty = follow the system proxy (local addresses always go direct)");
      expect(text).not.toMatch(/Empty (means|=) direct/);
    }
  });
});
