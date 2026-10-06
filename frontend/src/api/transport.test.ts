import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { DEV_PORT, UNCONFIGURED_API_BASE, resolveApiBase } from "./transport";

const base = { stored: null, env: undefined, dev: false, port: "" };

describe("这一页连哪台后端", () => {
  it("选过的服务器最先,其次是起 Vite / 构建时给的地址,都没有才是本机 8800", () => {
    expect(resolveApiBase({ ...base, stored: "http://team.example:9000/", env: "http://127.0.0.1:8833" }))
      .toBe("http://team.example:9000");
    expect(resolveApiBase({ ...base, env: "http://127.0.0.1:8833/" })).toBe("http://127.0.0.1:8833");
    expect(resolveApiBase(base)).toBe("http://127.0.0.1:8800");
  });

  it("开发服务器开在 5173 以外的端口、又什么都没配:不退回 8800,而是一个解析不出来的地址", () => {
    expect(resolveApiBase({ ...base, dev: true, port: "5291" })).toBe(UNCONFIGURED_API_BASE);
    expect(new URL(UNCONFIGURED_API_BASE).hostname.endsWith(".invalid")).toBe(true);
    // 配了就照配的连;`pnpm dev` 的 5173 照旧连本机 8800
    expect(resolveApiBase({ ...base, dev: true, port: "5291", env: "http://127.0.0.1:8833" })).toBe("http://127.0.0.1:8833");
    expect(resolveApiBase({ ...base, dev: true, port: "5291", stored: "http://127.0.0.1:8833" })).toBe("http://127.0.0.1:8833");
    expect(resolveApiBase({ ...base, dev: true, port: DEV_PORT })).toBe("http://127.0.0.1:8800");
  });

  it("打包出来的应用不受影响:没给地址就是 8800,不管页面是从哪个端口来的", () => {
    expect(resolveApiBase({ ...base, dev: false, port: "4173" })).toBe("http://127.0.0.1:8800");
    expect(resolveApiBase({ ...base, dev: false, port: "" })).toBe("http://127.0.0.1:8800");
  });

  it("DEV_PORT 和 `pnpm dev` 钉死的端口是同一个", () => {
    const pkg = JSON.parse(readFileSync(resolve(__dirname, "../../package.json"), "utf8")) as { scripts: Record<string, string> };
    expect(pkg.scripts.dev).toContain(`--port ${DEV_PORT}`);
    expect(pkg.scripts.dev).toContain("--strictPort");
  });
});
