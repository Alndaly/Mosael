/**
 * 选项来自服务端的下拉,要么走 OptionPicker(过阈值自动换成可搜索的那版),要么给出理由。
 *
 * 判据是「这份清单的长度我们说了不算」:`useQuery` 的结果有多少条由用户的账号、装了多少
 * 插件、上传了多少字体决定。今天三条,明天三十条 —— 而写代码的那天它是三条,于是留下一个
 * 裸 `Select`,长起来之后没有任何东西会提醒谁。用户报过两次:模型清单里滚着找一个只差一个
 * 数字的名字(seedance-2.5-image-to-video / seedance-2.5-reference-to-video),以及具名输出
 * 那一列几十条 `{{…}}` 引用。
 *
 * 写死的常量清单(三个宽高比、两个响应格式)不在这条里 —— 它们的长度是我们说了算的,
 * 加个搜索框只是噪音。
 *
 * 存量冻结在 GRANDFATHERED,每一条都写清楚为什么它留着 Select;清单只减不增。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

/** 存量:选项来自查询、却**故意**留着裸 Select 的地方。键是「文件: 那个查询变量名」。 */
const GRANDFATHERED = new Map<string, string>([
  [
    "features/editor/VoicePanel.tsx: localEngines",
    "每一项带三态运行环境徽标(已装/未装/还没测过),不是一行纯文字;引擎数量由我们打包决定,不会长",
  ],
  ["features/editor/VoicePanel.tsx: engines", "同上,TTS 引擎是我们打包进去的固定几个"],
  ["features/settings/AgentVoiceSection.tsx: engines", "同上"],
  ["features/editor/SubtitlePanel.tsx: f5Models", "只在装了多于一个权重时才出现,而权重是手动装的"],
]);

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules") continue;
      out.push(...sources(full));
    } else if (entry.name.endsWith(".tsx") && !entry.name.includes(".test.")) {
      // components/ui 是 Select 本体和它的包装,不是调用点。
      if (!full.includes(`${join("components", "ui")}${"/"}`)) out.push(full);
    }
  }
  return out;
}

/** 一个 `<SelectItem` 之前不远处出现的 `xxx.data` —— 那份清单的长度我们说了不算。 */
function queryBackedSelects(text: string): string[] {
  const found = new Set<string>();
  for (const item of text.matchAll(/<SelectItem/g)) {
    const before = text.slice(Math.max(0, item.index - 400), item.index);
    for (const hit of before.matchAll(/\b([A-Za-z_$][\w$]*)\.data\b/g)) found.add(hit[1]);
  }
  return [...found];
}

describe("长清单要能搜", () => {
  it("选项来自服务端的下拉不留裸 Select", () => {
    const offenders: string[] = [];
    for (const file of sources(SRC)) {
      const key = relative(SRC, file);
      for (const query of queryBackedSelects(readFileSync(file, "utf8"))) {
        const entry = `${key}: ${query}`;
        if (!GRANDFATHERED.has(entry)) offenders.push(entry);
      }
    }
    expect(
      offenders,
      "改用 @/components/ui/option-picker 的 OptionPicker(短清单它仍然渲染 Select,不改观感);\n" +
        "确有理由留着的,连同理由记进这条测试的 GRANDFATHERED",
    ).toEqual([]);
  });

  it("存量清单里的每一条都还在(挪走了就该从清单里删)", () => {
    const live = new Set(
      sources(SRC).flatMap((file) =>
        queryBackedSelects(readFileSync(file, "utf8")).map((query) => `${relative(SRC, file)}: ${query}`),
      ),
    );
    expect([...GRANDFATHERED.keys()].filter((key) => !live.has(key))).toEqual([]);
  });
});
