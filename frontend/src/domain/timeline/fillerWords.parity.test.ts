/**
 * 口癖词表的前端一侧:跑 contracts/filler-word-cases.json。
 *
 * 口播整理模板交给模型的口头禅候选(backend/app/domain/voices/fillers.py)跑同一份语料,见
 * backend/tests/test_filler_word_parity.py。两边各写一份而不对账的话:面板上「一键去口癖」认得的「就是说」,
 * 模型那边却没有时间,删不掉;或者反过来。
 */
import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/filler-word-cases.json";

import { FILLER_CATEGORIES, fillerCategory } from "./transcriptProjection";

describe("口癖词表(契约)", () => {
  it("类别、歧义标记、词逐字一致", () => {
    expect(FILLER_CATEGORIES.map((one) => ({ id: one.id, ambiguous: one.ambiguous, words: [...one.words] }))).toEqual(
      contract.categories,
    );
  });

  it.each(contract.cases)("判 $text", ({ text, category }) => {
    expect(fillerCategory(text)).toBe(category);
  });
});
