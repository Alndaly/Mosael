/**
 * 结构性约束:**接口回的逐字稿只有一处被转成可投影的段落。**
 *
 * 这条测试是补写的,因为它真的破过 —— 而且破的方式是这个项目的契约体系钉不住的那种。
 *
 * 项目有 7 组 parity 契约,守的是**跨语言的两份实现**:预览与导出、sidecar 与后端。那类漂移
 * 至少看得见,两边代码长得不一样。而这次是:同一个接口、同一个投影函数、两个调用方各写了一份
 * 映射,其中一份把 `tokens` 写死成 `[]`。逐字稿页显示 156 句,生成出来的字幕却是几条一分钟的
 * 巨块 —— 因为没有词级时间戳时投影会退到按标点猜句子的兜底路径。
 *
 * **两份长得几乎一样的映射,连 diff 都看不出问题。** 所以这里钉的不是"两边结果相等"
 * (那需要先有两边),而是"只有一边":凡是调 `projectTranscript` 的地方,段落必须来自
 * `transcriptSegmentsFromApi`。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { transcriptSegmentsFromApi } from "./transcriptProjection";

const SRC = join(__dirname, "..", "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return entry === "node_modules" || entry === "generated" ? [] : sourceFiles(path);
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [path] : [];
  });
}

describe("逐字稿映射只有一处", () => {
  it("每个调用 projectTranscript 的文件都从 transcriptSegmentsFromApi 拿段落", () => {
    const offenders = sourceFiles(SRC)
      .filter((path) => !path.endsWith(join("timeline", "transcriptProjection.ts")))
      .filter((path) => {
        const source = readFileSync(path, "utf8");
        return source.includes("projectTranscript(") && !source.includes("transcriptSegmentsFromApi");
      })
      .map((path) => path.slice(SRC.length + 1));

    expect(offenders, "这些文件自己拼了一份逐字稿映射 —— 用 transcriptSegmentsFromApi").toEqual([]);
  });

  it("没有别处再手写一遍 tokens 映射", () => {
    // `start_time:` 与 `end_time:` 同时出现在一个对象字面量里,基本只可能是在重建 token。
    const offenders = sourceFiles(SRC)
      .filter((path) => !path.endsWith(join("timeline", "transcriptProjection.ts")))
      .filter((path) => {
        const source = readFileSync(path, "utf8");
        return /tokens:\s*\([^)]*\)\s*\.map/.test(source) || /tokens:\s*\[\]/.test(source);
      })
      .map((path) => path.slice(SRC.length + 1));

    expect(offenders, "这些文件在手写 tokens 映射(写死 [] 正是那次的形状)").toEqual([]);
  });
});

describe("transcriptSegmentsFromApi", () => {
  const segment = {
    id: "s1", start_time: 0, end_time: 3.8, text: "这是我工作室的 mac mini。", speaker: "A",
    tokens: [{ start_time: 0, end_time: 1, text: "这是" }, { start_time: 1, end_time: 3.8, text: "mac mini。" }],
  };

  it("词级时间戳照抄,不丢", () => {
    expect(transcriptSegmentsFromApi([segment])[0].tokens).toEqual(segment.tokens);
  });

  it("老转写没有 tokens 时给空数组,不是 undefined", () => {
    const { tokens: _dropped, ...withoutTokens } = segment;
    expect(transcriptSegmentsFromApi([withoutTokens])[0].tokens).toEqual([]);
  });

  it("接口没回 segments 时是空数组,不炸", () => {
    expect(transcriptSegmentsFromApi(undefined)).toEqual([]);
    expect(transcriptSegmentsFromApi(null)).toEqual([]);
  });
});
