/**
 * 棘轮:**图上失败要有兜底**。
 *
 * 界面上几乎所有图都可能读不出来 —— 素材文件被清理、缩略图没生成、远端预览地址过期、头像被换掉。
 * 裸 `<img>` 在那种时候画的是浏览器的破图图标:既没说是什么,也没说为什么。2026-10-23 的素材卡片、
 * 2026-10-24 的设置页头像都是这么被指出来的,而每次都是"这一处补一下",下一处照旧。
 *
 * 所以这里收成一条:**每一处 `<img>` 要么走 `FallbackImage`,要么自己有 `onError`。**
 * 剩下三处是画布/叠加层里把图当**纹理或取景框**用的(见 ALLOWED),它们不进入普通布局,
 * 失败时表现为整块画面空着,由外层自己说明 —— 每一条都要写清为什么。
 */
export const RATCHET = true;

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

/** 仍然用裸 `<img>` 且没有 `onError` 的地方:**只减不增**,每条写清为什么。 */
const ALLOWED: Record<string, string> = {
  // 浏览器池里那张"此刻网页画面"的快照:失败时整块预览空着,外层已经有"没有画面"的说明。
  "features/browser-pool/BrowserPageList.tsx": "网页快照(外层有「没有画面」的说明)",
  // 区域选择的底层画面:它被当成取景坐标用,失败时由工具自己提示「先截一帧」。
  "features/browser-pool/session-tools/RegionOverlay.tsx": "区域选择的取景图(坐标基准)",
  // 合成器把图当纹理画进 canvas,换成一个 span 会直接破坏渲染。
  "features/editor/playback/CanvasCompositor.tsx": "canvas 纹理源",
};

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

/** JSX 里真正会被渲染的 `<img>`(注释里提到的不算)。 */
function imageSites(source: string): { imgs: number; guarded: number } {
  const code = source
    .split("\n")
    .filter((line) => {
      const trimmed = line.trimStart();
      //: 注释里说「`<img>` 会污染画布」不算一处图 —— 单行块注释(`/** … */`)也要跳过。
      return !trimmed.startsWith("//") && !trimmed.startsWith("*") && !trimmed.startsWith("/*");
    })
    .join("\n");
  const imgs = (code.match(/<img[\s>]/g) ?? []).length;
  const guarded =
    (code.match(/onError/g) ?? []).length + (code.match(/<FallbackImage/g) ?? []).length;
  return { imgs, guarded };
}

describe("图片兜底", () => {
  it("每一处 <img> 要么走 FallbackImage、要么自己有 onError(存量只减不增)", () => {
    const offenders: string[] = [];
    for (const path of sources(SRC)) {
      const rel = path.slice(SRC.length + 1).replaceAll("\\", "/");
      const { imgs, guarded } = imageSites(readFileSync(path, "utf8"));
      if (imgs <= guarded) continue;
      if (ALLOWED[rel]) continue;
      offenders.push(`${rel}: ${imgs} 处图,其中 ${imgs - guarded} 处没有兜底`);
    }
    expect(
      offenders,
      "用 FallbackImage(components/ui/fallback-image),或者在 <img> 上加 onError 换成占位:\n  " +
        offenders.join("\n  "),
    ).toEqual([]);
  });

  it("豁免名单只减不增:已经补上的地方要从 ALLOWED 里删掉", () => {
    const stale = Object.keys(ALLOWED).filter((rel) => {
      const path = join(SRC, rel);
      try {
        const { imgs, guarded } = imageSites(readFileSync(path, "utf8"));
        return imgs <= guarded;
      } catch {
        return true; // 文件没了 —— 这条豁免也该删
      }
    });
    expect(stale, `这些地方的图已经有兜底了,从 ALLOWED 里删掉:${stale.join(", ")}`).toEqual([]);
  });
});
