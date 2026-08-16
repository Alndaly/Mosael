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
 * 两次都是同一个形状:**后台任务改了数据,而前端不知道该刷什么**。所以这里断言的是
 * 「配音这条路要刷的缓存键集合」,而不是某一次调用。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const PANEL = readFileSync(join(import.meta.dirname, "SubtitlePanel.tsx"), "utf8");

/** 去掉注释 —— 免得这条棘轮被「注释里提到 assets」喂饱(这个仓库出过空棘轮)。 */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("配音完成后的缓存刷新", () => {
  it("时间线和素材库都要刷 —— 少刷素材,片段就显示成一串 id 且没有波形", () => {
    const body = code(PANEL);
    // 定位到跟着任务终态跑的那个 effect,而不是文件里任意一处 invalidate。
    const effect = body.slice(body.indexOf("jobStatus !== \"succeeded\""), body.indexOf("const run = useMutation"));
    expect(effect).toContain('queryKey: ["sequences"]');
    expect(effect).toContain('queryKey: ["assets"]');
  });

  it("失败也刷 —— 部分成功时已经落地的那几段同样得看得见", () => {
    const body = code(PANEL);
    const effect = body.slice(body.indexOf("jobStatus !== \"succeeded\""), body.indexOf("const run = useMutation"));
    // 提前 return 的条件里必须**同时**含 failed,否则失败分支根本走不到刷新那两行。
    expect(effect).toMatch(/jobStatus !== "succeeded" && jobStatus !== "failed"/);
  });
});
