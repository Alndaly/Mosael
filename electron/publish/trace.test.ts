/**
 * 结构化事件日志(P7):一行一个 JSON,URL 只留 origin+path,凭据键一律打码,文件有上限。
 */
import { describe, expect, it } from "vitest";

// CommonJS is intentional: publishWorker 加载的是同一份。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createTrace, safeUrl, scrub } = require("./trace.cjs") as {
  createTrace: (options?: {
    dir?: string;
    maxBytes?: number;
    now?: () => number;
    fs?: Record<string, unknown>;
  }) => { event: (scene: string, fields?: object) => void; span: <T>(scene: string, fields: object, run: () => Promise<T>) => Promise<T>; file: string };
  safeUrl: (url: string) => string;
  scrub: (value: unknown) => unknown;
};

function memoryFs() {
  const files = new Map<string, string>();
  const sizes = new Map<string, number>();
  return {
    files,
    mkdirSync: () => undefined,
    statSync: (file: string) => ({ size: sizes.get(file) ?? 0 }),
    renameSync: (from: string, to: string) => {
      files.set(to, files.get(from) ?? "");
      files.delete(from);
    },
    appendFileSync: (file: string, line: string) => {
      files.set(file, (files.get(file) ?? "") + line);
      sizes.set(file, (sizes.get(file) ?? 0) + line.length);
    },
  };
}

describe("排查用的结构化日志", () => {
  it("URL 只留 origin + path:视频号那串地址里的 code / state 不进日志", () => {
    expect(
      safeUrl("https://channels.weixin.qq.com/platform/oauth-callback.html?dark=1&code=081Q5p&state=undefined"),
    ).toBe("https://channels.weixin.qq.com/platform/oauth-callback.html");
    expect(safeUrl("not a url?with=query")).toBe("not a url");
  });

  it("凭据键打码,嵌套的也打", () => {
    const out = scrub({ cookie: "a=1", nested: { token: "secret", keep: "ok" }, url: "https://x.test/p?code=1" }) as Record<string, unknown>;
    expect(out.cookie).toBe("***");
    expect((out.nested as Record<string, unknown>).token).toBe("***");
    expect((out.nested as Record<string, unknown>).keep).toBe("ok");
    expect(out.url).toBe("https://x.test/p");
  });

  it("一行一条 JSON,span 自动带耗时与结论(成功和失败各一条)", async () => {
    const fs = memoryFs();
    const trace = createTrace({ dir: "/tmp/t", now: () => 1000, fs: fs as never });
    trace.event("login", { phase: "opening", account: "a1" });
    await trace.span("checkLogin", { phase: "verifying" }, async () => "ok");
    await expect(trace.span("checkLogin", {}, async () => { throw new Error("boom"); })).rejects.toThrow("boom");

    const lines = (fs.files.get(trace.file) ?? "").trim().split("\n").map((l) => JSON.parse(l));
    expect(lines).toHaveLength(3);
    expect(lines[0]).toMatchObject({ scene: "login", phase: "opening", account: "a1" });
    expect(lines[1]).toMatchObject({ scene: "checkLogin", ok: true, at: 0 });
    expect(lines[2]).toMatchObject({ scene: "checkLogin", ok: false, error: "boom" });
  });

  it("文件超过上限就轮转一份,不会无限长", () => {
    const fs = memoryFs();
    const trace = createTrace({ dir: "/tmp/t", maxBytes: 40, now: () => 1, fs: fs as never });
    trace.event("a", { pad: "x".repeat(30) });
    trace.event("b", { pad: "y".repeat(30) });
    expect(fs.files.has(`${trace.file}.1`)).toBe(true);
  });

  it("没给目录就什么都不写(独立运行 / 测试不落盘)", () => {
    const trace = createTrace({});
    expect(() => trace.event("x", {})).not.toThrow();
    expect(trace.file).toBe("");
  });
});
