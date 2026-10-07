/**
 * `createContext` 所在的模块不许引 UI 组件。
 *
 * context 的**身份**就是那一次 `createContext` 返回的对象。它所在的模块只要被重新执行一次,就会
 * 造出一个新的 context:还挂在外层的 Provider 是旧的,之后才加载的页面拿到的是新的,`useXxx`
 * 读到 null,整页报「must be used within …Provider」。
 *
 * 开发时这是真的会发生的:改一个按钮、一个下拉,热更新沿着 import 往上找能就地替换的地方;同时导出
 * 组件和 hook 的模块替换不了,只能整个重跑。剪辑页就这样整页挂过一次(录音的 context 经 Recorder
 * 引着 select.tsx,改了下拉宽度之后)。所以 context 放进一个 UI 改动碰不到的模块:只依赖 React、
 * 类型和纯逻辑。
 *
 * 下面 KNOWN 里是还没拆的,只许减少。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { expect, it } from "vitest";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");
const UI_IMPORT = /^import\s+(?!type\b)[^;]*?from\s+"(@\/components\/[^"]+|@\/features\/[^"]+|\.\/[A-Z][^"]*)";?$/gm;

/** 已知的、还没拆的:context 和 UI 组件住在一起。只许减少。 */
const KNOWN = new Set([
  "components/app/image-preview.tsx",
  "components/markdown/CitationLink.tsx",
  "components/ui/form.tsx",
  "features/collaboration/commentDocument.tsx",
]);

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

it("创建 context 的模块只依赖 React、类型和纯逻辑", () => {
  const offenders = sources(SRC)
    .filter((path) => /\bcreateContext\s*[<(]/.test(readFileSync(path, "utf8")))
    .filter((path) => [...readFileSync(path, "utf8").matchAll(UI_IMPORT)].length > 0)
    .map((path) => relative(SRC, path));
  expect(offenders.filter((path) => !KNOWN.has(path)), "把 context 和取它的 hook 拆进一个不引 UI 的模块").toEqual([]);
  expect([...KNOWN].filter((path) => !offenders.includes(path)), "已经拆好了 —— 从 KNOWN 里删掉").toEqual([]);
});

/**
 * 文案表几乎每次改动都会变(加一条、改一句)。context 模块要是在运行时引它 —— 直接引 `@/app/messages`,或者引
 * 从它取文案的 `@/app/preferences` —— 改一句文案就会把 context 模块整个重跑、换出一个新的 context。偏好的 context
 * 就这样整窗挂过(「usePreferences must be used inside PreferencesProvider」)。只引类型不算:类型在运行时不存在。
 */
const TEXT_IMPORT = /^import\s+(?!type\b)[^;]*?from\s+"@\/app\/(messages|preferences)(\/[^"]*)?";?$/gm;

/** 已知的、还没拆的:context 模块在运行时取文案。只许减少。 */
const KNOWN_TEXT = new Set(["components/app/image-preview.tsx"]);

it("创建 context 的模块不在运行时引文案表", () => {
  const offenders = sources(SRC)
    .filter((path) => /\bcreateContext\s*[<(]/.test(readFileSync(path, "utf8")))
    .filter((path) => [...readFileSync(path, "utf8").matchAll(TEXT_IMPORT)].length > 0)
    .map((path) => relative(SRC, path));
  expect(offenders.filter((path) => !KNOWN_TEXT.has(path)), "context 和取它的 hook 拆进一个只依赖 React 和类型的模块").toEqual([]);
  expect([...KNOWN_TEXT].filter((path) => !offenders.includes(path)), "已经拆好了 —— 从 KNOWN_TEXT 里删掉").toEqual([]);
});
