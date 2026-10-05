import { describe, expect, it } from "vitest";

import type { GenerationOption } from "@/api/client";
import { generationParameterLabel } from "@/lib/generationParameterLabels";

const t = (key: string) => key;
const model = (capabilities: Record<string, unknown>) => ({ capabilities }) as unknown as GenerationOption;

/**
 * 「张数」这一格叫什么只问 generationParameterLabel:AI 工作台、画板、工作流节点的表单和画布上的接入点都读它。
 * ComfyUI 的工作流「张数」是跑几遍(描述符的 `num_images_unit: "runs"`)—— 照实叫,不然一处「张数」一处「跑几遍」。
 */
describe("张数这一格的名字", () => {
  it("ComfyUI 的工作流(数的是跑几遍):叫「跑几遍」", () => {
    expect(generationParameterLabel("num_images", model({ num_images_unit: "runs" }), t)).toBe("genRuns");
  });

  it("别的模型照旧叫「张数」", () => {
    expect(generationParameterLabel("num_images", model({}), t)).toBe("wfGenNumImages");
    expect(generationParameterLabel("num_images", null, t)).toBe("wfGenNumImages");
  });
});
