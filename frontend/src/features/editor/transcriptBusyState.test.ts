/**
 * 转写正跑着的时候,逐字稿面板不能说「还没有转写结果」。
 *
 * 线上现象:任务在跑,面板却显示空状态 —— 那句话字面上成立,却把用户引向"是不是没点上"。
 * 根因是面板只认**自己发起的**那一次(本地 state 里的 asrJobId):从素材页发起、或者切走再回来,
 * 它就一无所知。任务的真相在后端,所以改成按 kind=transcribe 拉任务表,按素材 id 对上。
 *
 * 这条棘轮守的是「别再退回本地 state」,以及「跑完要自己取结果」——后者缺了就变成另一种
 * "跑完了界面不知道",用户仍然只能刷新。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const source = readFileSync(join(import.meta.dirname, "TranscriptPanel.tsx"), "utf8");

describe("逐字稿面板的进行中状态", () => {
  it("按后端任务表判断有没有在转,而不是只认自己发起的那一次", () => {
    expect(source).toContain('kind=transcribe');
    // 光有 asrRunning(本地)不够,必须把后端那份也算进去。
    expect(source).toMatch(/const busy = asrRunning \|\| Boolean\(runningJob\)/);
  });

  it("**进行中不渲染空状态文案**", () => {
    expect(source).toMatch(/busy \? t\("transcribing"\) : t\("transcriptEmpty"\)/);
  });

  it("跑完自己重取逐字稿 —— 否则仍要用户刷新", () => {
    expect(source).toMatch(/wasRunning\.current && !now/);
    expect(source).toContain('queryKey: ["transcript", assetId]');
  });
});
