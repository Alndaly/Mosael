import { describe, expect, it } from "vitest";

// CommonJS is intentional: Electron main loads this exact module.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createRestartPolicy, dataDirId, reusable } = require("./backend-lifecycle.cjs") as {
  createRestartPolicy: (options?: { maxRestarts?: number; windowMs?: number; baseDelayMs?: number }) => {
    next(now?: number): number | null;
  };
  dataDirId: (dir: string) => string;
  reusable: (
    health: Record<string, unknown> | null,
    expected: { version: string; dataDir: string; strict: boolean },
  ) => { ok: boolean; reason?: string };
};

const DIR = "/tmp/mosael-data";
const mine = { status: "ok", app: "mosael", version: "1.8.0", data_dir_id: "40a9c9be4789eb9d" };

describe("端口上的后端能不能复用", () => {
  it("数据目录指纹和后端(core/lifeline)同一个算法", () => {
    expect(dataDirId(DIR)).toBe("40a9c9be4789eb9d");
  });

  it("打包版:版本和数据目录都对得上才复用", () => {
    const expected = { version: "1.8.0", dataDir: DIR, strict: true };
    expect(reusable(mine, expected).ok).toBe(true);
    expect(reusable({ ...mine, version: "1.7.0" }, expected).ok, "上次强杀留下的旧版孤儿").toBe(false);
    expect(reusable({ ...mine, data_dir_id: "0000" }, expected).ok, "指着另一份数据").toBe(false);
    expect(reusable({ status: "ok" }, expected).ok, "端口上是别的东西").toBe(false);
    expect(reusable(null, expected).ok).toBe(false);
  });

  it("开发时照旧宽松:手动起的 uvicorn 只要活着就用", () => {
    expect(reusable({ status: "ok" }, { version: "1.8.0", dataDir: DIR, strict: false }).ok).toBe(true);
  });
});

describe("崩溃重启的退避", () => {
  it("1s、2s、4s,五分钟里第四次就认输", () => {
    const policy = createRestartPolicy();
    expect([policy.next(0), policy.next(10), policy.next(20)]).toEqual([1000, 2000, 4000]);
    expect(policy.next(30)).toBeNull();
  });

  it("崩溃隔得够久就重新计数", () => {
    const policy = createRestartPolicy({ windowMs: 1000 });
    policy.next(0);
    policy.next(10);
    policy.next(20);
    expect(policy.next(5000)).toBe(1000);
  });
});
