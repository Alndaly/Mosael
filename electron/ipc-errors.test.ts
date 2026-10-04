/**
 * 渲染层经 IPC 调主进程失败时给人看的那句话:不露「Error invoking remote method …」这类前缀和堆栈;主进程里
 * 没有这个处理器(主进程还是旧的,渲染层热更新成了新代码)时说要重启。
 *
 * 映射在调 IPC 的那一层统一做(preload 里所有 invoke 都过它),不是每个按钮各写一遍 —— 第二条测试守住这件事。
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

import { describe, expect, it } from "vitest";

const { humanIpcError } = createRequire(import.meta.url)("./ipc-errors.cjs") as {
  humanIpcError: (error: unknown, locale?: string) => Error;
};

describe("IPC 报错说人话", () => {
  it("主进程里没有这个处理器:说要重启 Mosael(应用的一部分还是旧版本),中英都有", () => {
    const error = new Error("Error invoking remote method 'pageTools:inset': Error: No handler registered for 'pageTools:inset'");
    expect(humanIpcError(error, "zh-CN").message).toBe("这个功能要重启 Mosael 才能用(应用的一部分还是旧版本)");
    expect(humanIpcError(error, "en-US").message).toBe(
      "Restart Mosael to use this (part of the app is still the old version)",
    );
  });

  it("去掉 Electron 加的前缀和错误类型名,留下主进程自己那句话(页面工具的原因码照样认得出)", () => {
    expect(
      humanIpcError(new Error("Error invoking remote method 'pageTools:capture': Error: page-tools: no_page"), "zh-CN").message,
    ).toBe("page-tools: no_page");
    expect(
      humanIpcError(new Error("Error invoking remote method 'publish:login': TypeError: publish:login: accountId must be a non-empty string"), "zh-CN")
        .message,
    ).toBe("publish:login: accountId must be a non-empty string");
    expect(humanIpcError(new Error("Error invoking remote method 'x': Error: 网页没有打开"), "zh-CN").message).toBe("网页没有打开");
  });

  it("不带堆栈;什么都没说的报错给一句通用的话", () => {
    const withStack = new Error("Error invoking remote method 'x': Error: boom\n    at foo (main.cjs:1:2)\n    at bar (main.cjs:3:4)");
    expect(humanIpcError(withStack, "zh-CN").message).toBe("boom");
    expect(humanIpcError(new Error("Error invoking remote method 'x': Error: "), "zh-CN").message).toBe(
      "桌面端没有完成这一步,再试一次",
    );
    expect(humanIpcError(undefined, "en").message).toBe("The desktop app couldn't finish this; try again");
  });

  it("preload 里所有 invoke 都经这一层(没有哪个按钮直接拿到 Electron 的原话)", () => {
    const source = fs.readFileSync(path.join(__dirname, "preload.cjs"), "utf8");
    // 只有那一个包装函数直接调 ipcRenderer.invoke,它的失败交给 humanIpcError。
    const direct = source.split("\n").filter((line) => line.includes("ipcRenderer.invoke("));
    expect(direct).toEqual(["  return ipcRenderer.invoke(channel, ...args).catch((error) => {"]);
    expect(source).toContain("throw humanIpcError(error, document.documentElement.lang);");
    expect(source.match(/\binvoke\(IPC\.invoke\./g)?.length ?? 0).toBeGreaterThan(30);
  });
});
