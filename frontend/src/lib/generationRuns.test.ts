/**
 * ComfyUI 的工作流「张数」是跑几遍(描述符的 `num_images_unit: "runs"`):每遍按工作流原样出它那一批。说明照维护者给的
 * 那句:跑几遍、每遍几张(批量 × 几个结果节点)、这次一共几张;一遍几张判不出来时不报数,宁可不说,不说错。
 */
import { describe, expect, it } from "vitest";

import type { GenerationOption } from "@/api/client";
import { aiStudio as enAiStudio } from "@/app/messages/en-US/aiStudio";
import { aiStudio as zhAiStudio } from "@/app/messages/zh-CN/aiStudio";
import type { MessageKey } from "@/app/messages";
import { countsRuns, outputsPerRun, runsHint } from "./generationCapabilities";

const zh = (key: MessageKey) => (zhAiStudio as Record<string, string>)[key] ?? key;
const en = (key: MessageKey) => (enAiStudio as Record<string, string>)[key] ?? key;
const comfy = (caps: Record<string, unknown>) =>
  ({ capabilities: { parameter_keys: ["num_images", "output_node"], num_images_unit: "runs", ...caps } }) as unknown as GenerationOption;
//: 「古风女孩1」那样:缺省最终结果一个节点、「全部」三个节点,画布存着一次 4 张。
const choice = { output_node: { type: "string", enum: ["final", "all", "17"], "x-outputs-per-run": { final: 4, all: 12, "17": 4 } } };

describe("跑几遍的说明", () => {
  it("批量 4、最终结果一个节点:每遍 4 张,跑 2 遍一共 8 张", () => {
    const model = comfy({ outputs_per_run: 4, batch_per_run: 4, parameter_schema: choice });
    expect(countsRuns(model)).toBe(true);
    expect(runsHint(zh, model, {}, 2)).toBe("跑几遍。每遍按工作流原样出 4 张(批量 4),这次一共 8 张");
    expect(runsHint(en, model, {}, 2)).toBe(
      "How many times to run it. Each run makes 4 as the workflow is saved (batch 4); 8 in total this time",
    );
  });

  it("选「全部」:批量 4 × 3 个结果节点,「N×」和说明里的总数是同一个数", () => {
    const model = comfy({ outputs_per_run: 4, batch_per_run: 4, parameter_schema: choice });
    expect(runsHint(zh, model, { output_node: "all" }, 1)).toBe(
      "跑几遍。每遍按工作流原样出 12 张(批量 4 × 3 个结果节点),这次一共 12 张",
    );
    expect(outputsPerRun(model, { output_node: "all" }) * 1).toBe(12);
  });

  it("一遍一张:几个结果节点说几个,一个就不说", () => {
    expect(runsHint(zh, comfy({ outputs_per_run: 2, batch_per_run: 1 }), {}, 3)).toBe(
      "跑几遍。每遍按工作流原样出 2 张(2 个结果节点),这次一共 6 张",
    );
    expect(runsHint(zh, comfy({ batch_per_run: 1 }), {}, 2)).toBe("跑几遍。每遍按工作流原样出 1 张,这次一共 2 张");
  });

  it("一遍几张判不出来(没给批量):不报数", () => {
    expect(runsHint(zh, comfy({}), {}, 3)).toBe("跑几遍。每遍按工作流原样出图,一遍出几张由工作流定;这次跑 3 遍");
  });

  it("别的模型的张数就是张数", () => {
    expect(countsRuns({ capabilities: { parameter_keys: ["num_images"] } } as unknown as GenerationOption)).toBe(false);
  });
});
