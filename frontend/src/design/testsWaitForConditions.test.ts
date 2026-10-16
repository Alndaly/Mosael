/**
 * 棘轮:测试里拿真计时器「等 N 毫秒」只减不增 —— 测试等条件(`waitFor` / `findBy*`),要推时间就用假计时器。
 *
 * 数的是一个靠计时器兑现的 Promise:`await` 一个由 `setTimeout` 去 resolve 的 Promise —— 「等 0.8 秒,它应该已经……了 /
 * 还没……」。在开发机上永远是绿的;机器一忙,该发生的还没发生,「没发生」那类断言照样成立(修复撤掉也是绿的),「发生了」
 * 那类就随机红。写法规矩见 docs/CONVENTIONS.md「测试里怎么等」,后端那一半是 backend/tests/test_tests_wait_for_events_not_time.py。
 *
 * 存量按文件冻在下面。**新加一处会红**;改掉一处也会红 —— 把表里的数字改小(或删掉那一行),表才不会慢慢变成一张谁都能
 * 往里加的白名单。真有一处非得这么写,加进表里,并在那一行写清为什么。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

export const RATCHET = true;

const REPO = join(import.meta.dirname, "..", "..", "..");
const ROOTS = [join(REPO, "frontend", "src"), join(REPO, "electron")];
const SELF = join(import.meta.dirname, "testsWaitForConditions.test.ts");

//: 一个由 setTimeout 去 resolve 的 Promise(`window.` / `globalThis.` 前缀、带类型参数、函数体包在花括号里都算)
const TIMER_PROMISE = /new Promise(?:<[^>]*>)?\(\s*\(?\s*(\w+)[^)=]*\)?\s*=>\s*\{?\s*(?:window\.|globalThis\.)?setTimeout\(\s*\1\b/g;

//: 存量,按文件(相对仓库根)。**只减不增。**
const TIMER_WAITS: Record<string, number> = {
  "electron/backend-lifecycle.test.ts": 1,
  "electron/preload-locale.test.ts": 1,
  "electron/publish/accountViewsPanels.test.ts": 1,
  "electron/publish/comfyWorkbench.test.ts": 1,
  "frontend/src/components/app/imagePreviewClose.dom.test.tsx": 1,
  "frontend/src/components/app/imagePreviewLayers.dom.test.tsx": 1,
  "frontend/src/components/app/suggestionMenu.dom.test.tsx": 1,
  "frontend/src/components/app/useExternalContent.dom.test.tsx": 1,
  "frontend/src/components/jobs/TaskCenter.dom.test.tsx": 1,
  "frontend/src/components/ui/appChrome.dom.test.tsx": 3,
  "frontend/src/components/ui/hint.dom.test.tsx": 2,
  "frontend/src/components/ui/nativeViewAside.dom.test.tsx": 6,
  "frontend/src/components/ui/optionPicker.dom.test.tsx": 3,
  "frontend/src/components/ui/truncate.dom.test.tsx": 2,
  "frontend/src/features/admin/InstallSourceSection.dom.test.tsx": 1,
  "frontend/src/features/agent/CanvasAgentChat.places.dom.test.tsx": 1,
  "frontend/src/features/agent/CanvasAgentChat.transcriptPolling.dom.test.tsx": 1,
  "frontend/src/features/agent/composerMentionRenders.dom.test.tsx": 1,
  "frontend/src/features/agent/saveAsSkill.dom.test.tsx": 1,
  "frontend/src/features/agent/skillPicker.dom.test.tsx": 1,
  "frontend/src/features/ai-studio/GenerateWorkspace.dom.test.tsx": 1,
  "frontend/src/features/ai-studio/durationFollows.dom.test.tsx": 1,
  "frontend/src/features/browser-pool/BrowserPageList.dom.test.tsx": 1,
  "frontend/src/features/browser-pool/embeddedFocus.dom.test.tsx": 1,
  "frontend/src/features/editor/EditorView.editing.dom.test.tsx": 3,
  "frontend/src/features/editor/playback/audioProxySource.test.ts": 1,
  "frontend/src/features/entities/entities.dom.test.tsx": 1,
  "frontend/src/features/media/cameraCapture.dom.test.ts": 1,
  "frontend/src/features/media/inputPreview.test.ts": 1,
  "frontend/src/features/media/useImportMediaFiles.dom.test.tsx": 1,
  "frontend/src/features/notes/NoteSelectionToolbar.dom.test.tsx": 2,
  "frontend/src/features/notes/noteAgentEdits.dom.test.tsx": 1,
  "frontend/src/features/notes/notesAgent.dom.test.tsx": 1,
  "frontend/src/features/plugins/ConnectionCollapse.dom.test.tsx": 1,
  "frontend/src/features/plugins/WorkflowAppEditor.dom.test.tsx": 2,
  "frontend/src/features/plugins/workbench/ComfyWorkbench.dom.test.tsx": 2,
  "frontend/src/features/plugins/workbench/ModelsPanelDetail.dom.test.tsx": 3,
  "frontend/src/features/settings/AutopilotRulesSection.dom.test.tsx": 1,
  "frontend/src/features/workflows/NodeInspector.generatePrompt.dom.test.tsx": 3,
  "frontend/src/features/workflows/TemplateUpgradeNotice.dom.test.tsx": 3,
  "frontend/src/features/workflows/WorkflowEditor.dom.test.tsx": 4,
  "frontend/src/features/workflows/WorkflowEditor.referenceHints.dom.test.tsx": 1,
  "frontend/src/features/workflows/WorkflowSaveConflict.dom.test.tsx": 3,
  "frontend/src/lib/clickThrough.dom.test.ts": 1,
};

function testFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === "dist") continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) out.push(...testFiles(path));
    else if (/\.test\.tsx?$/.test(entry) && path !== SELF) out.push(path);
  }
  return out;
}

function count(source: string): number {
  return (source.match(TIMER_PROMISE) ?? []).length;
}

describe("测试里怎么等", () => {
  it("拿真计时器等 N 毫秒的写法只减不增", () => {
    const found: Record<string, number> = {};
    for (const path of ROOTS.flatMap(testFiles)) {
      const hits = count(readFileSync(path, "utf8"));
      if (hits) found[relative(REPO, path)] = hits;
    }
    const drift: string[] = [];
    for (const name of [...new Set([...Object.keys(TIMER_WAITS), ...Object.keys(found)])].sort()) {
      const allowed = TIMER_WAITS[name] ?? 0;
      const now = found[name] ?? 0;
      if (now > allowed) drift.push(`${name}:${now} 处(表里是 ${allowed})—— 新加的改成 waitFor / findBy*,要推时间用 vi.useFakeTimers`);
      else if (now < allowed) drift.push(`${name}:剩 ${now} 处,表里还写着 ${allowed} —— 改好了就把表里的数字改小(只减不增)`);
    }
    expect(drift, "测试里「等时间」的写法和存量表对不上(docs/CONVENTIONS.md「测试里怎么等」)").toEqual([]);
  });

  it("数法认得出该数的、放过不该数的", () => {
    expect(count("await new Promise((resolve) => setTimeout(resolve, 800));")).toBe(1);
    expect(count("await new Promise((r) => window.setTimeout(r, 50));")).toBe(1);
    expect(count("await new Promise<void>((done) => { setTimeout(done, 10); });")).toBe(1);
    expect(count("const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));")).toBe(1);
    expect(count("setTimeout(() => controller.abort(), 20);")).toBe(0);
    expect(count("vi.useFakeTimers({ toFake: [\"setTimeout\"] });")).toBe(0);
    expect(count("await waitFor(() => expect(log).toEqual([\"a\"]));")).toBe(0);
  });
});
