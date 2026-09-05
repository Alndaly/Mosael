/**
 * 按钮的尺寸刻度只能来自 token,不能在调用点重定义。
 *
 * `<Button size="icon" className="h-7 w-7">` 这种写法是在说「我要 28px」—— 但它同时也在说
 * 「Button 没有 28px 这一档」。作者不是想改这一个按钮,是想要一个刻度而 token 里没有,于是
 * 就地捏一个。捏的人多了,刻度就住在 60 多个 className 里,而不是住在 `buttonVariants` 里。
 *
 * 后果不是「有个按钮尺寸不对」,是**漏一处就露馅**:同一排控件里只要有一个忘了盖,它就按
 * `size="icon"` 渲染成 36px,杵在一排 28px 中间。圆形按钮尤其藏不住这 8px —— 智能体输入框
 * 的工具行就是这么坏的,当时是手工把那几个按钮补上 `h-7 w-7`,而不是补上缺的那一档。
 *
 * 现在四档都有 token:`xs`/`icon-xs` 是 28,`sm`/`icon-sm` 是 32,`default`/`icon` 是 36,
 * `lg` 是 40。想要新的一档就往 `buttonVariants` 里加一档,别在 className 里加。
 *
 * 拦的是「同时写了 `size` 和 `h-N`/`w-N`/`size-N`」这一种形状 —— 光写 className 不写 size 的
 * 那是别的东西(原生 `<button>`、纯布局盒子),不归这条管。
 *
 * 存量冻结在 GRANDFATHERED,全是 20/24px 的真·一次性尺寸(浮在缩略图角上的删除钮、
 * 挤在一行里的复制按钮)—— 它们比最小的那一档还小,给它们发 token 等于把 token 变成
 * 「所有出现过的尺寸」。要放行就写进来,清单只减不增。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..", "..");

/**
 * 存量:确实需要一次性尺寸的调用点,记成 `文件: 类名`(和 `design/gridAxes.test.ts` 同一套
 * 键 —— 不带行号,不然挪一行代码就要改清单,清单就没人愿意维护了)。
 *
 * **只减不增。** 新增一处会红,提示去 `buttonVariants` 里补那一档;改用 token 之后不删这里
 * 也会红。
 */
const GRANDFATHERED = new Set<string>([
  "components/agent/SubagentPanel.tsx: h-6 w-6",
  "features/ai-studio/AiStudio.tsx: h-6",
  "features/ai-studio/FrameSlotField.tsx: h-5 w-5",
  "features/ai-studio/FrameSlotField.tsx: h-6 w-6",
  "features/ai-studio/trace/TraceView.tsx: h-6 w-6",
  "features/editor/Inspector.tsx: h-6",
  "features/plugins/PluginsView.tsx: h-6",
  "features/settings/VoiceLibrarySection.tsx: h-6 w-6",
]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : sourceFiles(full);
    return /\.tsx$/.test(entry.name) ? [full] : [];
  });
}

/** 去掉注释 —— 免得棘轮被「注释里解释为什么这里是 h-7 w-7」喂饱(这个仓库出过空棘轮)。 */
function strip(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/** 粗略切出 `<Button ...>` 开标签:跳过 `=>` 里的 `>`,按花括号深度配对。 */
function openTags(text: string): string[] {
  const out: string[] = [];
  const re = /<Button\b/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    let i = re.lastIndex;
    let depth = 0;
    while (i < text.length) {
      const ch = text[i];
      if (ch === "{") depth += 1;
      else if (ch === "}") depth -= 1;
      else if (ch === ">" && depth === 0 && text[i - 1] !== "=") {
        out.push(text.slice(match.index, i + 1));
        break;
      }
      i += 1;
    }
  }
  return out;
}

/**
 * 尺寸类:数字打头的 `h-`/`w-`/`size-`,而且前面紧挨着空白或引号。
 *
 * 这个边界一次挡掉三种不该管的写法:变体前缀(`md:h-7` —— 那是响应式,不是重定义基准刻度)、
 * 子选择器(`[&_svg]:size-4` —— 说的是里面的图标)、以及 `min-h-7`/`max-w-8` 这类下限上限。
 * 非数字的 `w-fit`、`h-full` 也不算:它们表达的是「跟着内容/容器走」,不是一个刻度。
 */
const SCALE = /(?<=[\s"'`])((?:h|w|size)-\d[\w./[\]()%-]*)(?=[\s"'`])/g;

interface Hit {
  file: string;
  classes: string[];
}

function findHits(): Hit[] {
  const hits: Hit[] = [];
  for (const path of sourceFiles(SRC)) {
    const file = relative(SRC, path);
    for (const tag of openTags(strip(readFileSync(path, "utf8")))) {
      // 没传 size 的不归这条管:那是「完全自己画一个按钮」,不是「拿了一档再改它」。
      if (!/\bsize=/.test(tag)) continue;
      const classes = [...new Set([...tag.matchAll(SCALE)].map((m) => m[1]))].sort();
      if (classes.length > 0) hits.push({ file, classes });
    }
  }
  return hits;
}

const key = (hit: Hit) => `${hit.file}: ${hit.classes.join(" ")}`;

describe("按钮尺寸刻度", () => {
  it("传了 size 就不许再用 className 改高宽", () => {
    const offenders = findHits()
      .map(key)
      .filter((entry) => !GRANDFATHERED.has(entry));
    expect(
      offenders,
      "改用现成的那一档(xs/icon-xs=28、sm/icon-sm=32、default/icon=36、lg=40);" +
        "确实缺一档就往 buttonVariants 里加,别写在 className 里",
    ).toEqual([]);
  });

  it("存量清单只减不增", () => {
    const live = new Set(findHits().map(key));
    const stale = [...GRANDFATHERED].filter((entry) => !live.has(entry));
    expect(stale, "已经改用 token 了,从 GRANDFATHERED 删掉这几行").toEqual([]);
  });
});
