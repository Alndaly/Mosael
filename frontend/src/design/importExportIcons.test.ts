/**
 * 「导入」「导出」的图标方向和字对得上:导入是箭头**进来**,导出是箭头**出去**。
 *
 * 维护者:「技能这里的导入 icon 明显是导出语义」—— 「导入 .zip」用的是 `Upload`(箭头从盒子里往上出去)、
 * 「导入文件夹」用的是 `FolderUp`;反过来一串「导出」用的是 `Download`(箭头往下进盒子),看着像导入。
 *
 * 规矩(方向以 Mosael 为准):
 * - 导入:`Import`、`FileInput`、`FolderInput`(箭头指进去);
 * - 导出:`FileOutput`、`FolderOutput`(箭头指出来);
 * - 「上传」照旧 `Upload` 一类,「下载 / 保存到本地 / 安装」照旧 `Download` 一类 —— 那几个字的意思和图标本来就对得上,不归这里管。
 *
 * 认法:一处有方向的图标(JSX `<Upload` 或 `icon={…}` / `icon: …`),取它上下三行里离得最近的 `t("…")`,看那条中文
 * 说的是「导入」还是「导出」(两样都说、或都不说的不管)。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { readSource, SRC, tsxSources } from "./jsxSource";

/** 有方向的图标(lucide 名)。 */
const DIRECTIONAL = new Set([
  "Upload", "Download", "Import", "FileUp", "FileDown", "FileInput", "FileOutput", "FolderUp", "FolderDown", "FolderInput",
  "FolderOutput", "ImageUp", "ImageDown", "CloudUpload", "CloudDownload", "HardDriveUpload", "HardDriveDownload",
  "ArrowUpFromLine", "ArrowDownToLine", "Share", "Share2",
]);
const INWARD = new Set(["Import", "FileInput", "FolderInput"]);
const OUTWARD = new Set(["FileOutput", "FolderOutput"]);

/** 存量:只减不增。`文件:行` → 说明。 */
const STOCK: Record<string, string> = {};

function zhMessages(): Map<string, string> {
  const dir = join(SRC, "app", "messages", "zh-CN");
  const out = new Map<string, string>();
  for (const name of readdirSync(dir)) {
    if (!name.endsWith(".ts")) continue;
    for (const match of readFileSync(join(dir, name), "utf8").matchAll(/^\s*(\w+):\s*"((?:[^"\\]|\\.)*)"/gm)) {
      out.set(match[1], match[2]);
    }
  }
  return out;
}

function lucideImports(code: string): Set<string> {
  const names = new Set<string>();
  for (const match of code.matchAll(/import\s*\{([^}]*)\}\s*from\s*["']lucide-react["']/g)) {
    for (const part of match[1].split(",")) {
      const name = part.trim().replace(/^type\s+/, "").split(/\s+as\s+/).pop()?.trim();
      if (name) names.add(name);
    }
  }
  return names;
}

type Finding = { at: string; icon: string; key: string; says: "导入" | "导出" };

/** 一个文件里图标方向和最近那条字说的方向对不上的地方。 */
export function mismatches(rel: string, code: string, zh: ReadonlyMap<string, string>): Finding[] {
  const icons = [...lucideImports(code)].filter((name) => DIRECTIONAL.has(name));
  if (!icons.length) return [];
  const usage = new RegExp(`(?:<|icon[=:]\\s*\\{?\\s*<?)(${icons.join("|")})\\b`);
  const lines = code.split("\n");
  const found: Finding[] = [];
  lines.forEach((line, index) => {
    if (/^\s*import\b/.test(line)) return;
    const icon = usage.exec(line)?.[1];
    if (!icon) return;
    let nearest: { key: string; distance: number } | null = null;
    for (let offset = -3; offset <= 3; offset += 1) {
      const other = lines[index + offset];
      if (other === undefined) continue;
      for (const match of other.matchAll(/\bt\("(\w+)"\)/g)) {
        // 同样远时取下面的:按钮的字一般写在图标后面
        const distance = Math.abs(offset) * 2 - (offset > 0 ? 1 : 0);
        if (!nearest || distance < nearest.distance) nearest = { key: match[1], distance };
      }
    }
    const text = nearest ? zh.get(nearest.key) ?? "" : "";
    const imports = text.includes("导入");
    const exports = text.includes("导出");
    if (imports === exports) return;
    const says = imports ? "导入" : "导出";
    if ((says === "导入" && !INWARD.has(icon)) || (says === "导出" && !OUTWARD.has(icon))) {
      found.push({ at: `${rel}:${index + 1}`, icon, key: nearest!.key, says });
    }
  });
  return found;
}

describe("导入 / 导出的图标方向", () => {
  it("说「导入」的用箭头进来的图标,说「导出」的用箭头出去的", () => {
    const zh = zhMessages();
    const found = tsxSources().flatMap((rel) => mismatches(rel, readSource(rel), zh)).filter((one) => !(one.at in STOCK));
    expect(found.map((one) => `${one.at}  ${one.icon} ← ${one.key}「${one.says}」`)).toEqual([]);
  });

  it("认得出对不上的写法(自检)", () => {
    const zh = new Map([["importZip", "导入 .zip"], ["exportZip", "导出 .zip"], ["upload", "上传图片"]]);
    const code = [
      'import { Download, Import, Upload } from "lucide-react";',
      '<Button><Upload />{t("importZip")}</Button>',
      '<Button><Import />{t("importZip")}</Button>',
      '<MenuItem icon={<Download />} label={t("exportZip")} />',
      '<Button><Upload />{t("upload")}</Button>',
    ].join("\n\n\n\n");
    expect(mismatches("x.tsx", code, zh).map((one) => one.icon)).toEqual(["Upload", "Download"]);
  });
});
