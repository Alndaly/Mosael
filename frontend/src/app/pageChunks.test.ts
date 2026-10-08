/**
 * 页面**按需加载**,不许被直接 import 回主包。
 *
 * 此前十四个页面全是静态 import,于是打包出来是一个 4.20 MB 的主包:打开一次素材库,也要先解析
 * 工作流的图编辑器(@xyflow)、笔记的富文本内核(tiptap/prosemirror)、代码高亮(shiki)和图表。
 * 改成 React.lazy 之后主包 0.28 MB,每个页面自己一块。
 *
 * 这条测试拦的是**回头路**:`import { XxxView } from "@/features/…"` 在 pages.tsx 里写一次,
 * 那一页就又回到主包里,而打包仍然成功、测试仍然全绿 —— 只有下次量包体积时才看得出来。
 *
 * 首屏那一页(home)是例外:它一定会被渲染,懒加载只会多一次闪烁。
 *
 * **只看 pages.tsx 不够。** 外壳(App.tsx)里静态 import 的东西同样在首屏关键路径上:`main.tsx` 是 import 完
 * App 才开始画的。ComfyUI 工作台就这么回来过 —— 它只在桌面版、打开工作台时才出现,却经由助手面板把 tiptap /
 * prosemirror、Markdown 全家一起拖进首屏(首屏 JS 78 个文件 / 2.8 MB,而这一条测试一直是绿的)。所以再看结果:
 * 从入口出发**静态**走得到的模块里,不许出现只有某些页面才用的重型依赖。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { firstPackageUse, staticClosure } from "@/design/importGraph";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const PAGES = readFileSync(join(import.meta.dirname, "pages.tsx"), "utf8");

/** 允许静态 import 的:首屏那一页,以及渲染壳自己用的东西。 */
const EAGER = new Set(["@/features/home/HomeView"]);

describe("页面分块", () => {
  it("功能页只能通过 React.lazy 进来", () => {
    const eagerFeatureImports = [...PAGES.matchAll(/^import\s+\{[^}]*\}\s+from\s+"(@\/features\/[^"]+)";/gm)]
      .map((one) => one[1])
      .filter((path) => !EAGER.has(path));
    expect(eagerFeatureImports, "这些页面被静态 import,会回到主包里 —— 改成 React.lazy").toEqual([]);
  });

  it("每个懒加载的页面都拿到了自己的那一块", () => {
    const lazyPages = [...PAGES.matchAll(/React\.lazy\(\(\) => import\("(@\/features\/[^"]+)"\)/g)].map((one) => one[1]);
    expect(lazyPages.length).toBeGreaterThanOrEqual(13);
    expect(new Set(lazyPages).size, "同一个页面被 lazy 了两次").toBe(lazyPages.length);
  });

  it("兜底的 Suspense 在渲染出口上", () => {
    // 每页各写一次的话,漏写的那一页首次打开会直接抛,而不是转一下菊花。
    const app = readFileSync(join(import.meta.dirname, "App.tsx"), "utf8");
    expect(app).toMatch(/<React\.Suspense[\s\S]{0,200}?\{PAGE_RENDERERS\[view\]\(/);
  });

  /**
   * 首屏要先取到、解析完才能画出第一帧的,是 main.tsx 和 App.tsx 的静态依赖闭包(main 是 `await import(App)` 之后才
   * render)。这些包只该在用到它们的那一页 / 那一块里按需加载。
   */
  const STARTUP_ENTRIES = ["app/main.tsx", "app/App.tsx"];
  const PAGE_ONLY_PACKAGES = [
    "@tiptap/", // 富文本:笔记、助手输入框
    "prosemirror-",
    "streamdown", // Markdown 渲染:助手回答、笔记预览
    "react-markdown",
    "marked",
    "micromark",
    "shiki", // 代码高亮
    "@xyflow/", // 画布:画板、工作流
    "three", // 3D 场景
    "@codemirror/", // 代码编辑器
    "codemirror",
    "recharts", // 统计图
    "mp4box", // 剪辑页的播放内核
    "@dnd-kit/", // 拖拽排序
  ];

  it("首屏的静态依赖闭包里没有只属于某些页面的重型依赖", () => {
    const closure = staticClosure(STARTUP_ENTRIES);
    const offenders = PAGE_ONLY_PACKAGES.flatMap((prefix) => {
      const chain = firstPackageUse(closure, prefix);
      return chain ? [`${prefix}:${chain.join(" → ")}`] : [];
    });
    expect(offenders, "这些包被外壳静态拖进了首屏 —— 把链上那个组件改成 React.lazy").toEqual([]);
  });

  /**
   * 文案正文按语言分块(app/messageTables):首屏只取存着的那一种,和外壳并行。此前 preferences 在运行时引着
   * `app/messages`,两种语言五百多 KB 源码进了 index.html 里 modulepreload 的那一块,每次启动都要先解析完。
   */
  it("首屏的静态依赖闭包里没有文案正文 —— 两种语言都按需取", () => {
    const closure = staticClosure(STARTUP_ENTRIES);
    const tables = [...closure].filter(([module]) => /^app\/messages(\/|\.ts$)/.test(module)).map(([, chain]) => chain.join(" → "));
    expect(tables, "运行时的代码改用 app/messageTables 的 messagesFor / loadMessages;app/messages 只给类型和测试").toEqual([]);
    expect(closure.has("app/messageTables.ts"), "判据认得出那条路").toBe(true);
  });

  it("这道检查扫得到东西 —— 别变成空转", () => {
    const closure = staticClosure(STARTUP_ENTRIES);
    expect(closure.size, "从入口一个模块都没走到,八成是路径解析坏了").toBeGreaterThan(100);
    expect(closure.has("app/pages.tsx")).toBe(true);
    // 反过来:笔记页本身确实引着富文本内核 —— 判据认得出它,它只是不在首屏闭包里。
    expect(firstPackageUse(staticClosure(["features/notes/NotesView.tsx"]), "@tiptap/")).not.toBeNull();
    // 工作台确实把助手面板和富文本带了进来:它要是改回静态 import,上面那条会红。
    expect(firstPackageUse(staticClosure(["features/plugins/workbench/ComfyWorkbench.tsx"]), "@tiptap/")).not.toBeNull();
  });
});
