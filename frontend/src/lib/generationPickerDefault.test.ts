/**
 * 结构性约束:**生成模型选择器不拿清单第一项当默认** —— 落在存着的那个、用户设的默认,或者什么都不选。
 *
 * 清单按连接名排序,排在第一的那个不是谁的选择。画板的出图格曾经写着 `current = … ?? options[0]`,
 * 于是默认挑中了 147ai 上的 `claude-opus-4-6`,而用户在设置里设过的默认生图模型被晾在一边 ——
 * 后端「没点名模型就用他的默认」那条路也从来轮不到,因为前端总是点了名。
 *
 * 规则只有一处:`pickGenerationOption`(默认由后端标在选项上,`is_default`)。这里扫所有读生成选项的
 * 源文件,不许再出现 `?? options[0]` / `|| models[0]` 这种兜底;要兜底就调那个函数。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import type { GenerationOption } from "@/api/client";
import { pickGenerationOption } from "@/lib/generationCapabilities";

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

/** 读生成选项的文件:用了这个类型,或者直接打了那个接口。 */
const CONSUMERS = sourceFiles(SRC).filter((file) => {
  const text = fs.readFileSync(file, "utf8");
  return /\bGenerationOption\b/.test(text) || text.includes("/generation/options");
});

const FIRST_ITEM_FALLBACK = /(\?\?|\|\|)\s*[\w.]*(?:[oO]ptions|[mM]odels)\[0\]/;

describe("生成模型选择器的默认", () => {
  it("扫描面站得住", () => {
    const names = CONSUMERS.map((file) => path.relative(SRC, file));
    for (const expected of ["features/boards/NodeComposer.tsx", "features/ai-studio/AiStudio.tsx", "features/workflows/WorkflowsView.tsx"]) {
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

  it("pickGenerationOption:存着的 → 默认 → 没有", () => {
    const option = (model: string, kind: string, isDefault = false) =>
      ({ id: model, provider_profile_id: "p", profile_name: "P", provider: "x", kind, model, label: model,
         adapter_available: true, capabilities_known: true, is_default: isDefault }) as GenerationOption;
    const first = option("aaa", "image");
    const chosen = option("flux", "image", true);
    const video = option("veo", "video", true);

    expect(pickGenerationOption([first])).toBeNull();
    expect(pickGenerationOption([first, chosen])).toBe(chosen);
    expect(pickGenerationOption([first, chosen], { saved: (one) => one.model === "aaa" })).toBe(first);
    // 存着的已经不在清单里:落到默认
    expect(pickGenerationOption([first, chosen], { saved: (one) => one.model === "gone" })).toBe(chosen);
    // 只认这种生成的默认
    expect(pickGenerationOption([first, video], { kind: "image" })).toBeNull();
    expect(pickGenerationOption([first, video], { kind: "video" })).toBe(video);
  });
});
