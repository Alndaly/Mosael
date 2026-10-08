/**
 * 「画布操控方式」(触控板 / 鼠标)只有一种样子:components/app/CanvasInputModeMenu。
 *
 * 此前同一件事两种做法:ComfyUI 工作台顶栏是一段「触控板 | 鼠标」分段控件,在「保存」「运行」旁边占了一大块;画板、工作流、
 * 3D 场景是一颗点一下就切换的图标按钮,看不出现在是哪种、点了会变成哪种(维护者:换成带图标的按钮加下拉,别忘了说明)。
 *
 * 存储各走各的(工作台只对那个连接,其余是全局的 canvasInputMode),所以有两个包装 —— CanvasInputModeSwitch、
 * ComfyNavigationSwitch —— 都只是把存储接到 CanvasInputModeMenu 上。这条盯三件事:
 * - 能**改**画布操控方式的只有这两个包装(别处只读它);
 * - 两个包装都渲染 CanvasInputModeMenu;
 * - 触控板 / 鼠标那两个图标只在 CanvasInputModeMenu 里出现(没有人在别处另画一套)。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { blankComments } from "@/design/jsxSource";

const SRC = join(import.meta.dirname, "..");
const MENU = "components/app/CanvasInputModeMenu.tsx";
const WRAPPERS = ["components/app/CanvasInputModeSwitch.tsx", "features/plugins/ComfyNavigationSwitch.tsx"];
/** 挂开关的那几处:三块画布的工具条、工作台顶栏、内嵌浏览器顶栏(ComfyUI 的视图不在工作台里时)。 */
const SITES: Record<string, string> = {
  "features/boards/BoardsView.tsx": "CanvasInputModeSwitch",
  "features/workflows/WorkflowEditorToolbar.tsx": "CanvasInputModeSwitch",
  "features/scenes/SceneStudio.tsx": "CanvasInputModeSwitch",
  "features/plugins/workbench/ComfyWorkbench.tsx": "ComfyNavigationSwitch",
  "app/App.tsx": "ComfyNavigationSwitch",
};

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry) && !entry.includes(".test.") ? [relative(SRC, path)] : [];
  });
}
const read = (rel: string) => blankComments(readFileSync(join(SRC, rel), "utf8"));

describe("画布操控方式只有一种样子", () => {
  const all = sources(SRC);

  it("能改它的只有那两个包装", () => {
    const writers = all.filter((rel) => {
      const code = read(rel);
      return /\bsetCanvasInputMode\b/.test(code) && !rel.endsWith("components/app/canvasInputMode.ts")
        || /\[\s*\w+\s*,\s*\w+\s*\]\s*=\s*useCanvasInputMode\(/.test(code)
        || /\bchoose\b[^;]*=\s*useComfyNavigation\(/.test(code);
    });
    expect(writers.sort(), "新的入口用 CanvasInputModeSwitch / ComfyNavigationSwitch,别再写第三种开关").toEqual([...WRAPPERS].sort());
  });

  it("两个包装都渲染 CanvasInputModeMenu", () => {
    for (const rel of WRAPPERS) expect(read(rel), rel).toMatch(/<CanvasInputModeMenu\b/);
  });

  it("触控板 / 鼠标那两个图标只在 CanvasInputModeMenu 里", () => {
    const drawn = all.filter((rel) => /import\s*\{[^}]*\b(Touchpad|Mouse)\b[^}]*\}\s*from\s*"lucide-react"/.test(read(rel)));
    expect(drawn).toEqual([MENU]);
  });

  it("挂开关的几处都用了包装", () => {
    for (const [rel, wrapper] of Object.entries(SITES)) expect(read(rel), rel).toMatch(new RegExp(`<${wrapper}\\b`));
  });
});
