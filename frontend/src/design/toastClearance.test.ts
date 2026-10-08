/**
 * 贴底的输入区挂 `data-toast-avoid`,右下角的提示条才知道要让开它(components/app/toastClearance)。
 *
 * 维护者截图:AI Studio 里「语音合成 · 已完成」盖在输入框右下角的发送键和「⌘Enter 生成」上。规则是全局的 —— 提示条量挂了
 * 标记的元素、伸进右下角那一列就抬上去 —— 但标记得有人挂:新写一个贴底的输入框忘了挂,它的发送键就又被盖住,而且只在
 * 「刚好有一条提示」的那几秒里看得见。这条盯两类:
 * - 渲染智能体输入框(`<DraftComposer`)的文件 —— AI Studio 的对话、各页的智能体面板(画板、工作流、笔记、3D 场景、剪辑、工作台);
 * - AI Studio 创作那一栏的输入卡(图像、视频、音乐、语音、播客共用的那一张)。
 * 以及提示条那一头确实在用这条规则(Toaster 的 offset 跟着 useToastClearance 走)。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { readSource, tsxSources } from "@/design/jsxSource";

/** 贴底、但不渲染 DraftComposer 的输入区。 */
const BOTTOM_COMPOSERS = ["features/ai-studio/GenerateWorkspace.tsx"];
/** 输入框组件自己(被别处包在贴底的卡片里,标记挂在那张卡片上)。 */
const COMPOSER_ITSELF = new Set(["features/agent/ChatComposer.tsx", "features/agent/composerDraft.tsx"]);

describe("提示条让开贴底的输入区", () => {
  const hosts = tsxSources().filter((rel) => !COMPOSER_ITSELF.has(rel) && /<DraftComposer\b/.test(readSource(rel)));

  it("扫得到:智能体输入框至少挂在 AI Studio 对话和智能体面板两处", () => {
    expect(hosts).toEqual(expect.arrayContaining(["features/ai-studio/ChatWorkspace.tsx", "features/agent/CanvasAgentChat.tsx"]));
  });

  it("渲染智能体输入框的、AI Studio 创作的输入卡,都挂了 data-toast-avoid", () => {
    const missing = [...hosts, ...BOTTOM_COMPOSERS].filter((rel) => !/\bdata-toast-avoid\b/.test(readSource(rel)));
    expect(missing).toEqual([]);
  });

  it("提示条的底边距跟着 useToastClearance 走", () => {
    const app = readSource("app/App.tsx");
    expect(app).toMatch(/useToastClearance\(\)/);
    expect(app).toMatch(/<Toaster[\s\S]*?offset=\{\{\s*bottom\s*\}\}/);
  });
});
