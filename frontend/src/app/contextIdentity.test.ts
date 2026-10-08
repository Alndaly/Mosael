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
 *
 * **看的是运行时的整条依赖链,不只是直接 import。** 热更新沿着 import 往上找能就地替换的地方,中间隔着一个纯逻辑模块
 * 照样会传到 context 模块;而此前的正则只认 `@/components`、`@/features` 和**大写开头**的 `./X` —— `tooltip.tsx`
 * (三个 context,引着 `./kbd`)和 `overChromeModal.tsx`(引着 `./nativeViewAside`)就这样违规却不在清单里。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { expect, it } from "vitest";

import { staticClosure } from "@/design/importGraph";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");

/** 界面组件:components/ 和 features/ 下的 .tsx。 */
const isUi = (rel: string) => /^(components|features)\//.test(rel) && rel.endsWith(".tsx");
/** 文案表,以及从它取文案的 preferences。 */
const isText = (rel: string) => /^app\/(messages|preferences)(\/|\.)/.test(rel);

/** 已知的、还没拆的:context 和 UI 组件住在一起。只许减少。 */
const KNOWN = new Set([
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

const contextModules = sources(SRC)
  .filter((path) => /\bcreateContext\s*[<(]/.test(readFileSync(path, "utf8")))
  .map((path) => relative(SRC, path));

/** 这个模块在运行时(直接或隔着几层)引到的第一个满足条件的模块,连同那条链。 */
function reaches(module: string, predicate: (rel: string) => boolean): string[] | null {
  for (const [target, chain] of staticClosure([module])) {
    if (target !== module && predicate(target)) return chain;
  }
  return null;
}

it("创建 context 的模块只依赖 React、类型和纯逻辑(整条运行时依赖链)", () => {
  const offenders = contextModules
    .map((module) => ({ module, chain: reaches(module, isUi) }))
    .filter(({ chain }) => chain !== null);
  expect(
    offenders.filter(({ module }) => !KNOWN.has(module)).map(({ chain }) => chain!.join(" → ")),
    "把 context 和取它的 hook 拆进一个不引 UI 的模块",
  ).toEqual([]);
  expect([...KNOWN].filter((path) => !offenders.some(({ module }) => module === path)), "已经拆好了 —— 从 KNOWN 里删掉").toEqual([]);
});

/**
 * 文案表几乎每次改动都会变(加一条、改一句)。context 模块要是在运行时引它 —— 直接引 `@/app/messages`,或者引
 * 从它取文案的 `@/app/preferences`,或者隔着几层引到它们 —— 改一句文案就会把 context 模块整个重跑、换出一个新的 context。
 * 偏好的 context 就这样整窗挂过(「usePreferences must be used inside PreferencesProvider」)。只引类型不算:类型在运行时不存在。
 *
 * 此前这里还有一份「还没拆的」清单,只剩 `image-preview.tsx` 一处;它的 context 已经拆进 imagePreviewContext.ts,
 * 这一条从此没有例外。
 */
it("创建 context 的模块不在运行时引文案表(整条运行时依赖链)", () => {
  const offenders = contextModules
    .filter((module) => !KNOWN.has(module))
    .map((module) => reaches(module, isText))
    .filter((chain): chain is string[] => chain !== null)
    .map((chain) => chain.join(" → "));
  expect(offenders, "context 和取它的 hook 拆进一个只依赖 React 和类型的模块").toEqual([]);
});

it("这道检查扫得到东西 —— 别变成空转", () => {
  expect(contextModules.length).toBeGreaterThan(15);
  expect(contextModules).toEqual(expect.arrayContaining(["components/app/imagePreviewContext.ts", "components/ui/tooltipContext.ts"]));
  // 判据认得出隔着一层的情形:场景之类的界面组件当然引着 UI(用一个确定引 UI 的模块反证)。
  expect(reaches("components/app/image-preview.tsx", isUi)).not.toBeNull();
  expect(reaches("components/app/image-preview.tsx", isText)).not.toBeNull();
});
