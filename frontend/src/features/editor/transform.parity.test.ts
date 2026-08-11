/**
 * 片段变换契约的前端一侧:跑 contracts/transform-cases.json。
 *
 * 后端 `backend/tests/test_transform_parity.py` 跑**同一份文件**。
 *
 * 为什么需要契约:后端 `_read_transform` 的原注释写着「Mirrors the frontend readTransform
 * defaults」—— 而它没做到。抓到时是**四份互不相同的答案**:写入钳到 scale≤4、导出钳到
 * scale≤10、关键帧那份 rotation 允许 ±3600,而这里**一处都不钳**、数字字符串还会静默退回默认。
 * 同一个 clip,预览放 20 倍、导出放 4 倍。
 *
 * 没发作只因为唯一的写入路径在写时先钳过一道 —— 那是上游挡住,不是两侧一致。
 */
import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/transform-cases.json";
import { TRANSFORM_BOUNDS, TRANSFORM_DEFAULTS, readTransform } from "@/features/editor/TransformOverlay";
import { sampleProp, type KfProp, type Keyframe } from "@/features/editor/keyframes";

describe("变换契约", () => {
  it("语料在,且带版本号 —— 找不到就静默跳过是最坏的结果", () => {
    expect(contract.contract).toBe("transform");
    expect(typeof contract.version).toBe("number");
    expect(contract.normalize.length).toBeGreaterThan(0);
    expect(contract.sample.length).toBeGreaterThan(0);
  });

  it("合法范围与默认值只有一份 —— 语料说了算", () => {
    expect(TRANSFORM_DEFAULTS).toEqual(contract.defaults);
    expect(TRANSFORM_BOUNDS).toEqual(contract.bounds);
  });

  it.each(contract.normalize.map((c) => [c.name, c] as const))("%s · 读出来是什么", (_name, testCase) => {
    const tf = readTransform(testCase.raw as Record<string, unknown>);

    const actual = { scale: tf.scale, x: tf.x, y: tf.y, rotation: tf.rotation, opacity: tf.opacity };

    expect(actual, `${testCase.name}\n  用例理由: ${testCase.why ?? ""}`).toEqual(testCase.transform);
  });

  it.each(contract.sample.map((c) => [c.name, c] as const))("%s · 关键帧采样", (_name, testCase) => {
    const actual = sampleProp(
      testCase.keyframes as Keyframe[],
      testCase.prop as KfProp,
      testCase.base,
      testCase.progress,
    );

    expect(actual, `${testCase.name}\n  用例理由: ${testCase.why ?? ""}`).toBeCloseTo(testCase.value, 9);
  });
});
