/**
 * 配音完成后要刷**哪些**缓存。
 *
 * 这条看着像琐事,实际连着两个用户报上来的症状:
 *
 *   ・「配音没生成」—— 其实生成了,只是时间线没刷,新轨进不到界面里;
 *   ・「音轨没有波浪线」—— 后端明明有波形文件,但片段引用的素材前端还不知道,
 *     于是 `assetById.get(clip.asset_id)` 是 undefined,`has_waveform` 无从读起,
 *     片段标题也回退成一串 asset id(截图里那个 `d925885e`)。
 *
 * 两次都是同一个形状:**后台任务改了数据,而前端不知道该刷什么**。刷新现在归任务中心,
 * 刷什么由后端任务目录声明(ADR-0018)—— 所以这里断言的是目录里配音那一行,和任务中心
 * 不把刷新包在「成功了才」里(部分成功时已经落地的那几段同样得看得见)。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(import.meta.dirname, "../../../..");
const CATALOG = readFileSync(join(ROOT, "backend/app/domain/job_catalog.py"), "utf8");
const TASK_CENTER = readFileSync(join(import.meta.dirname, "../../components/layout/TaskCenter.tsx"), "utf8");

/** 去掉注释 —— 免得这条棘轮被「注释里提到 assets」喂饱(这个仓库出过空棘轮)。 */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*(\/\/|#).*$/gm, "");
}

describe("配音完成后的缓存刷新", () => {
  it("时间线和素材库都要刷 —— 少刷素材,片段就显示成一串 id 且没有波形", () => {
    const line = code(CATALOG).split("\n").find((row) => row.includes('JobKind("subtitle_dub"'));
    expect(line).toBeDefined();
    expect(line).toContain('"assets"');
    expect(line).toContain('"sequences"');
  });

  it("失败也刷 —— 部分成功时已经落地的那几段同样得看得见", () => {
    const body = code(TASK_CENTER);
    const refresh = body.indexOf("queryKeysAffectedBy(meta)");
    expect(refresh).toBeGreaterThan(0);
    // 刷新在「要不要说」之前,也不看 succeeded。
    expect(refresh).toBeLessThan(body.indexOf("shouldAnnounce(meta"));
    expect(body.slice(body.indexOf("const meta = kindOf(job.kind)"), refresh)).not.toContain('"succeeded"');
  });
});
