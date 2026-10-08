import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { jobSettled, runStatusLabelKey, runStatusText } from "./runStatus";

describe("任务状态的叫法", () => {
  it("认识的状态给对应的键", () => {
    expect(runStatusLabelKey("queued")).toBe("runStatus_queued");
    expect(runStatusLabelKey("cancelled")).toBe("runStatus_cancelled");
  });

  it("不认识的状态返回 null,显示时原样给状态值,不拼出一串不存在的键", () => {
    expect(runStatusLabelKey("paused")).toBeNull();
    // 原型链上的名字不算认识
    expect(runStatusLabelKey("toString")).toBeNull();
    const t = (key: string) => `«${key}»`;
    expect(runStatusText(t, "succeeded")).toBe("«runStatus_succeeded»");
    expect(runStatusText(t, "paused")).toBe("paused");
  });
});

describe("任务结束了没有", () => {
  it("被停下的也是结束了(ADR 0049),还在跑的、没取到的不是", () => {
    for (const status of ["succeeded", "failed", "cancelled"]) expect(jobSettled(status)).toBe(true);
    for (const status of ["queued", "running", undefined]) expect(jobSettled(status)).toBe(false);
  });

  it("棘轮:不再写死「成功或失败」当结束 —— 被停下的任务会被当成还在跑,一直轮询下去", () => {
    const root = join(import.meta.dirname, "..", "..");
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) && !path.includes("generated")) files.push(path);
      }
    };
    walk(root);
    const pattern = /status === "succeeded" \|\| [\w.?]*status === "failed"|status === "failed" \|\| [\w.?]*status === "succeeded"/;
    const offenders = files.filter((path) => pattern.test(readFileSync(path, "utf8"))).map((path) => relative(root, path));
    expect(offenders).toEqual([]);
  });
});
