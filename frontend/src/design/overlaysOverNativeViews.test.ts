/**
 * 应用级的浮层都登记了「原生视图在前台时怎么让」,登记的那种处理也真的接上了(ADR 0051)。
 *
 * 内嵌浏览器、ComfyUI 工作台的画布是原生视图,盖在一切 DOM 上。体检里漏了五处:系统通知点进来的任务中心、提示条、命令面板、
 * 确认卡、免提浮标 —— 都画在网页底下,人以为什么都没发生。每一处都是「当初没想到要接」,所以这条盯三件事:
 * - 挂在应用根上(App、AppShell)的、会浮起来的组件,要么登记在 GLOBAL_OVERLAYS(components/app/overNativeView),要么在下面
 *   NOT_GLOBAL 里写明为什么不用管;
 * - 桌面壳从外面派的 window 事件(系统通知、深链、网页里按的 ⌘K —— electron/preload.cjs 里 dispatch 的那几个),听它的模块都登记了:
 *   它们正是在原生视图亮着时被叫起来的;
 * - 登记的处理真接上了:`aside` 挂在 `<OverNativeView>` 里,`chrome` 住进外壳顶栏的那个位,`float` 交给浮层视图,`leave` 先收起视图。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import { GLOBAL_OVERLAYS, type OverlayHandling } from "@/components/app/overNativeView";
import { readSource, SRC } from "@/design/jsxSource";

/** 挂全局浮层的地方:应用根和应用的外框。 */
const HOSTS = ["app/App.tsx", "components/layout/AppShell.tsx"];

/** 挂在根上、会浮起来,但不归这条规矩管的。理由写清楚:下一个人要判断新加的那个是不是同一种。 */
const NOT_GLOBAL: Record<string, string> = {
  AppShell: "应用的外框本身;顶栏、侧栏里点出来的浮层原生视图在前台时点不到(外壳顶栏盖着顶栏)",
  AppearanceProvider: "外观的背景层,不是浮层",
  LoginView: "登录之前,没有原生视图",
  ImagePreviewProvider: "看大图:开着时请原生视图让开(nativeViewAside),ADR 0051 之前就接好了",
  BrowserPageList: "原生视图的外壳本身(内嵌浏览器左边的页面列表)",
  BrowserPreview: "原生视图的外壳本身(网页的悬停预览)",
  LivePanels: "原生视图的外壳本身(悬浮的网页面板)",
  ComfyWorkbench: "原生视图的外壳本身(工作台的顶栏和右边那一列)",
  ChromeStatusSlot: "原生视图的外壳本身(外壳顶栏上给 chrome 那一类留的位)",
  MainStaleNotice: "只在开发时出现;原生视图在前台时外壳顶栏上有它的小标记(MainStaleBadge)",
  NotificationCenter: "只从顶栏的铃铛打开,原生视图在前台时顶栏被外壳盖着,开不出来",
  RenameDialog: "只从侧栏的工作区菜单打开,原生视图在前台时点不到",
  DeleteWorkspaceDialog: "只从侧栏的工作区菜单打开,原生视图在前台时点不到",
};

/** 一个模块看起来会浮起来:Radix 的弹层、portal、`fixed` 加一层 z。 */
const FLOATS = /<(?:Dialog|AlertDialog|Sheet|Popover|CommandDialog|Toaster|ModalShell|ConfirmDialog)\b|createPortal\(|["'`][^"'`\n]*\bfixed\b[^"'`\n]*\bz-/;

/** `<Name` 是一个 JSX 开标签(不是 `useState<Name>` 这种泛型参数)。 */
const jsxTag = (name: string) => new RegExp(`(?<![\\w$.)\\]])<${name}[\\s/>]`);

function resolveImport(spec: string): string | null {
  if (!spec.startsWith("@/")) return null;
  const base = spec.slice(2);
  for (const candidate of [`${base}.tsx`, `${base}.ts`, `${base}/index.tsx`, `${base}/index.ts`]) {
    if (existsSync(join(SRC, candidate))) return candidate;
  }
  return null;
}

/** 宿主文件里用到的、从别的模块引进来的组件:名字 → 模块。 */
function importedComponents(host: string): Map<string, string> {
  const source = readSource(host);
  const found = new Map<string, string>();
  for (const match of source.matchAll(/import\s*\{([^}]*)\}\s*from\s*"([^"]+)"/g)) {
    const file = resolveImport(match[2]);
    if (!file) continue;
    for (const raw of match[1].split(",")) {
      const name = raw.trim().replace(/^type\s+/, "").split(/\s+as\s+/).pop()!.trim();
      if (/^[A-Z]/.test(name) && jsxTag(name).test(source)) found.set(name, file);
    }
  }
  for (const match of source.matchAll(/const (\w+) = React\.lazy\(\(\) => import\("([^"]+)"\)/g)) {
    const file = resolveImport(match[2]);
    if (file && jsxTag(match[1]).test(source)) found.set(match[1], file);
  }
  return found;
}

/** `<name` 在宿主里是不是包在 `<OverNativeView>` 里。 */
function insideOverNativeView(source: string, name: string): boolean {
  const at = source.search(jsxTag(name));
  if (at < 0) return false;
  const before = source.slice(0, at);
  return before.lastIndexOf("<OverNativeView>") > before.lastIndexOf("</OverNativeView>");
}

function codeFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : codeFiles(full);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [relative(SRC, full)] : [];
  });
}

const registered = Object.entries(GLOBAL_OVERLAYS) as Array<[string, { file: string; handling: OverlayHandling }]>;

describe("应用级的浮层:原生视图在前台时怎么让", () => {
  it("挂在应用根上、会浮起来的组件,都登记了(或写明了为什么不用管)", () => {
    const missing: string[] = [];
    for (const host of HOSTS) {
      for (const [name, file] of importedComponents(host)) {
        if (file.startsWith("components/ui/")) continue; // 基础组件不是浮层本身
        if (name in GLOBAL_OVERLAYS || name in NOT_GLOBAL) continue;
        if (FLOATS.test(readSource(file))) missing.push(`${host} 里的 <${name}>(${file})`);
      }
    }
    expect(missing, "登记进 components/app/overNativeView 的 GLOBAL_OVERLAYS,或者在 NOT_GLOBAL 里写明理由").toEqual([]);
  });

  it("扫得到:任务中心、命令面板、确认卡、免提浮标都被当成根上的浮层", () => {
    const names = new Set(HOSTS.flatMap((host) => [...importedComponents(host).keys()]));
    for (const name of ["TaskCenter", "CommandPalette", "ConfirmationCenter", "VoiceDock", "RemoteVoiceConsentHost"]) {
      expect(names.has(name), name).toBe(true);
      expect(FLOATS.test(readSource(GLOBAL_OVERLAYS[name as keyof typeof GLOBAL_OVERLAYS].file)), name).toBe(true);
    }
  });

  it("桌面壳从外面派的事件,听它的模块都登记了", () => {
    const preload = readFileSync(join(SRC, "..", "..", "electron", "preload.cjs"), "utf8");
    const events = [...preload.matchAll(/new CustomEvent\("(mosael:[^"]+)"/g)].map((match) => match[1]);
    expect(events, "preload 派的事件").toEqual(expect.arrayContaining(["mosael:open-tasks", "mosael:open-cmdk", "mosael:deep-link"]));
    const files = new Set(registered.map(([, entry]) => entry.file));
    const missing = codeFiles(SRC).flatMap((file) => {
      const source = readSource(file);
      return events.filter((event) => source.includes(`addEventListener("${event}"`) && !files.has(file)).map((event) => `${file} 听 ${event}`);
    });
    expect(missing).toEqual([]);
  });

  it("登记的处理都接上了", () => {
    const broken: string[] = [];
    for (const [name, { file, handling }] of registered) {
      const source = readSource(file);
      if (handling === "aside") {
        const hosted = HOSTS.filter((host) => importedComponents(host).has(name));
        if (hosted.length === 0) broken.push(`${name}:没挂在应用根上`);
        for (const host of hosted) if (!insideOverNativeView(readSource(host), name)) broken.push(`${name}:${host} 里没包在 <OverNativeView> 里`);
      } else if (handling === "chrome") {
        for (const needed of ["useNativeViewInFront(", "useChromeStatusSlot(", "<InChromeStatusSlot"]) {
          if (!source.includes(needed)) broken.push(`${name}:${file} 里没有 ${needed}`);
        }
      } else if (handling === "float") {
        if (!source.includes("useToastMirror(")) broken.push(`${name}:${file} 里没有 useToastMirror(`);
      } else if (!source.includes("leaveNativeView(")) {
        broken.push(`${name}:${file} 里没有 leaveNativeView(`);
      }
    }
    expect(broken).toEqual([]);
  });

  it("提示条挂着 APP_CHROME:任何弹窗开着时上面的按钮都点得到、点了不关弹窗(D40)", () => {
    const app = readSource("app/App.tsx");
    expect(app).toMatch(/\{\.\.\.APP_CHROME\}[^>]*>\s*<Toaster\b/);
  });
});
