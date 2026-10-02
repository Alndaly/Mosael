/**
 * 断句契约的前端一侧:跑 contracts/transcript-sentence-cases.json —— 后端
 * tests/test_transcript_sentence_parity.py 跑的是**同一份文件**。剪辑台的逐字稿 / 生成字幕和工作流的
 * 生成字幕必须切得一样;改规则时先改语料,看着两侧一起红,再改两侧实现。
 */
import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/transcript-sentence-cases.json";
import { transcriptSegmentsForEditing } from "@/domain/timeline/transcriptProjection";

const round = (value: number) => Math.round(value * 1e6) / 1e6;

describe("断句契约", () => {
  it("语料在,且带版本号", () => {
    expect(contract.contract).toBe("transcript-sentences");
    expect(typeof contract.version).toBe("number");
    expect(contract.cases.length).toBeGreaterThan(0);
  });

  it.each(contract.cases.map((c) => [c.name, c] as const))("%s", (_name, testCase) => {
    const rows = transcriptSegmentsForEditing(testCase.segments).map((row) => ({
      id: row.id,
      start_time: round(row.start_time),
      end_time: round(row.end_time),
      text: row.text,
    }));
    expect(rows, testCase.why).toEqual(testCase.expected);
  });
});
