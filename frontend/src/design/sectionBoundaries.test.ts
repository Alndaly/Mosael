/**
 * 渲染外来数据的那几块各自有错误边界(components/app/errorBoundary 的 SectionBoundary):出错只换掉自己。
 *
 * 此前只有整页、整窗两层。嵌在画板、剪辑、笔记、工作流、3D 场景、ComfyUI 工作台里的助手面板渲染的是模型的工具结果,
 * 它一出错整页被换掉,而画布好好的;常驻在窗口上的确认中心、免提浮标、内嵌浏览器的顶栏、工作台一出错,整个窗口换成
 * 「Mosael 出错了」。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { SRC, blankComments, tsxSources } from "@/design/jsxSource";

/** 每一处 `<Tag` 是不是包在一个还没闭合的 `<SectionBoundary` 里(按开闭标签计数;同一个文件里够用)。 */
function unguarded(code: string, tag: string): number[] {
  const lines: number[] = [];
  const pattern = new RegExp(`<${tag}[\\s>/]`, "g");
  for (const match of code.matchAll(pattern)) {
    const before = code.slice(0, match.index);
    const opened = (before.match(/<SectionBoundary[\s>]/g) ?? []).length;
    const closed = (before.match(/<\/SectionBoundary>/g) ?? []).length;
    if (opened <= closed) lines.push(before.split("\n").length);
  }
  return lines;
}

const read = (rel: string) => blankComments(readFileSync(join(SRC, rel), "utf8"));

describe("各自兜底的那几块", () => {
  it("每一处嵌进页面的助手面板都包在 SectionBoundary 里", () => {
    const sites = tsxSources().filter((rel) => rel !== "features/agent/CanvasAgentChat.tsx" && /<CanvasAgentChat[\s>/]/.test(read(rel)));
    expect(sites.length, "一处助手面板都没扫到,八成是标签名改了").toBeGreaterThanOrEqual(6);
    const offenders = sites.flatMap((rel) => unguarded(read(rel), "CanvasAgentChat").map((line) => `${rel}:${line}`));
    expect(offenders, "包一层 <SectionBoundary onClose={…}>:面板出错只换掉面板").toEqual([]);
  });

  it("常驻在窗口上的浮层都包在 SectionBoundary 里", () => {
    const app = read("app/App.tsx");
    const overlays = ["MainStaleNotice", "BrowserDownloads", "BrowserPreview", "LivePanels", "NativeViewStandIn", "CommandPalette", "ConfirmationCenter", "RemoteVoiceConsentHost", "VoiceDock", "ComfyWorkbench", "ChromeAboveDialogs"];
    const offenders = overlays.flatMap((tag) => unguarded(app, tag).map((line) => `${tag}(App.tsx:${line})`));
    expect(offenders, "包一层 <SectionBoundary mode=\"quiet\">:浮层出错只收起它自己").toEqual([]);
  });
});
