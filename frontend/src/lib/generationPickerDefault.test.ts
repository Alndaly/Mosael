/**
 * 结构性约束:**生成模型选择器不拿清单第一项当默认** —— 落在存着的那个、用户设的默认,或者什么都不选。
 *
 * 清单按连接名排序,排在第一的那个不是谁的选择。画板的出图格曾经写着 `current = … ?? options[0]`,
 * 于是默认挑中了 147ai 上的 `claude-opus-4-6`,而用户在设置里设过的默认生图模型被晾在一边 ——
 * 后端「没点名模型就用他的默认」那条路也从来轮不到,因为前端总是点了名。
 *
 * 规则只有一处:`chooseGenerationOption` / `pickGenerationOption`(默认由后端标在选项上,`is_default`)。这里扫所有读生成选项的
 * 源文件,不许再出现 `?? options[0]` / `|| models[0]` 这种兜底;要兜底就调那个函数。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import type { GenerationOption } from "@/api/client";
import { chooseGenerationOption, pickGenerationOption } from "@/lib/generationCapabilities";

const SRC = path.resolve(__dirname, "..");

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "generated" || entry.name === "node_modules") continue;
      out.push(...sourceFiles(full));
    } else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

/** 读生成选项的文件:用了这个类型、直接打了那个接口,或者经 lib/generationOptions 取(工作流检查器、画板就是
 *  这样拿到的,类型和接口都不在它们自己的文件里)。 */
const CONSUMERS = sourceFiles(SRC).filter((file) => {
  const text = fs.readFileSync(file, "utf8");
  return /\bGenerationOption\b/.test(text) || text.includes("/generation/options") || /\buseGenerationOptions\b/.test(text);
});

const FIRST_ITEM_FALLBACK = /(\?\?|\|\|)\s*[\w.]*(?:[oO]ptions|[mM]odels)\[0\]/;

describe("生成模型选择器的默认", () => {
  it("扫描面站得住", () => {
    const names = CONSUMERS.map((file) => path.relative(SRC, file));
    for (const expected of ["features/boards/NodeComposer.tsx", "features/ai-studio/GenerateWorkspace.tsx", "features/workflows/NodeInspector.tsx", "features/workflows/nodeInspectorGenerate.tsx"]) {
      expect(names).toContain(expected);
    }
  });

  it("读生成选项的地方不拿第一项兜底", () => {
    const offenders: string[] = [];
    for (const file of CONSUMERS) {
      fs.readFileSync(file, "utf8").split("\n").forEach((line, index) => {
        if (FIRST_ITEM_FALLBACK.test(line)) offenders.push(`${path.relative(SRC, file)}:${index + 1}: ${line.trim()}`);
      });
    }
    expect(offenders, "改用 pickGenerationOption:存着的 → 默认 → 不选").toEqual([]);
  });

  it("chooseGenerationOption:记着的 → (没记着时)默认 → 没有;记着的不在清单里不拿别的顶上", () => {
    const option = (model: string, kind: string, isDefault = false) =>
      ({ id: model, provider_profile_id: "p", profile_name: "P", provider: "x", kind, model,
         adapter_available: true, capabilities_known: true, is_default: isDefault }) as GenerationOption;
    const first = option("aaa", "image");
    const chosen = option("flux", "image", true);
    const video = option("veo", "video", true);
    const saved = (model: string) => ({ provider_profile_id: "p", model, kind: "image" });

    expect(pickGenerationOption([first])).toBeNull();
    expect(pickGenerationOption([first, chosen])).toBe(chosen);
    expect(chooseGenerationOption([first, chosen], saved("aaa"))).toEqual({ option: first, missing: null, remapped: false });
    expect(chooseGenerationOption([first, chosen], null)).toEqual({ option: chosen, missing: null, remapped: false });
    // 记着的已经不在清单里:是它不在了,不是默认 —— 默认那个是按次付费的别家模型也说不定
    expect(chooseGenerationOption([first, chosen], saved("gone"))).toEqual({ option: null, missing: saved("gone"), remapped: false });
    // 清单还没到:不说「不在了」
    expect(chooseGenerationOption([], saved("gone"), { loaded: false })).toEqual({ option: null, missing: null, remapped: false });
    // 只认这种生成的默认
    expect(pickGenerationOption([first, video], { kind: "image" })).toBeNull();
    expect(pickGenerationOption([first, video], { kind: "video" })).toBe(video);
  });
});

describe("连接重建之后,同一份模型自动接回去", () => {
  const option = (profile: string, model: string) => ({
    value: `${profile}:${model}`,
    model,
    provider_profile_id: profile,
    kind: "image",
    is_default: false,
  } as never);
  const saved = (profile: string, model: string) => ({ provider_profile_id: profile, model, kind: "image" });

  it("连接 id 变了、同一份模型只剩一个:接回去,并标记 remapped", () => {
    //: 维护者遇到的样子:插件实例重建后 provider_profile_id 换了 -> 原来那条永远对不上 ->
    //: 模型说"用不了"、"在工作台里打开"那颗按钮也一起没了。
    const chosen = chooseGenerationOption([option("new", "zimage.json")], saved("old", "zimage.json"));
    expect(chosen.option?.provider_profile_id).toBe("new");
    expect(chosen.missing).toBeNull();
    expect(chosen.remapped).toBe(true);
  });

  it("同一份模型有好几条:不猜,照实说那条不在了", () => {
    //: 分不清就让人自己选 —— 猜错等于把用户的工作流换成别人的。
    const chosen = chooseGenerationOption(
      [option("a", "zimage.json"), option("b", "zimage.json")],
      saved("old", "zimage.json"),
    );
    expect(chosen.option).toBeNull();
    expect(chosen.missing).toEqual(saved("old", "zimage.json"));
    expect(chosen.remapped).toBe(false);
  });

  it("模型名字也不在:不接", () => {
    const chosen = chooseGenerationOption([option("new", "other.json")], saved("old", "zimage.json"));
    expect(chosen.option).toBeNull();
    expect(chosen.missing).toEqual(saved("old", "zimage.json"));
  });

  it("原连接还在:就是它,不算重接", () => {
    const chosen = chooseGenerationOption([option("old", "zimage.json")], saved("old", "zimage.json"));
    expect(chosen.option?.provider_profile_id).toBe("old");
    expect(chosen.remapped).toBe(false);
  });
});
