/**
 * 仓库链接只能指向 **main**,而且只能指向真实存在的路径。
 *
 * 3D 场景页的「查看安装步骤」曾经指向 `tree/codex/scene-studio/plugins/examples/blender` ——
 * 那是一条**开发分支**。远端只有 main,所以每一个点它的人拿到的都是 404,而这个链接出现在
 * 「还没接上 Blender」的空状态里:正是最需要它管用的时刻。
 *
 * 这类错误不会报任何错,只有点过的人知道。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const REPO = join(SRC, "..", "..");

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : sources(full);
    return /\.tsx?$/.test(entry.name) && !entry.name.includes(".test.") ? [full] : [];
  });
}

/** `https://github.com/<owner>/<repo>/(tree|blob)/<ref>/<path>` */
const REPO_LINK = /https:\/\/github\.com\/Alndaly\/Mosael\/(?:tree|blob)\/([^/"'`\s]+)\/([^"'`\s)]*)/g;

describe("仓库链接", () => {
  const found = sources(SRC).flatMap((file) =>
    [...readFileSync(file, "utf8").matchAll(REPO_LINK)].map((hit) => ({
      file: relative(SRC, file).replaceAll("\\", "/"),
      ref: hit[1],
      path: hit[2],
    })),
  );

  it("不指向开发分支 —— 远端只有 main,别的 ref 一律 404", () => {
    expect(found.filter((one) => one.ref !== "main").map((one) => `${one.file}: ${one.ref}`)).toEqual([]);
  });

  it("指到的路径在仓库里真的存在", () => {
    // 拼错的路径和过期的路径一样是 404,而两者都得点开才知道。
    const missing = found.filter((one) => one.path && !existsSync(join(REPO, one.path)));
    expect(missing.map((one) => `${one.file}: ${one.path}`)).toEqual([]);
  });
});
