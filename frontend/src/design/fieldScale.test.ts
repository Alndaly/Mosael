/**
 * 输入框和下拉触发器的高度只能来自 `size` 档位,不能在调用点用 className 改。
 *
 * `<Input className="h-8">` 是在说「我要 32px」—— 也是在说「Input 没有 32px 这一档」。此前确实
 * 没有:输入框只有一个 40px,于是十几个调用点各自写 `h-8`/`h-7`/`h-[26px]`,刻度住在 className
 * 里而不在 control-size.ts 里。后果是**漏一处就露馅**:插件页的工具筛选那一行,搜索框写了 `h-8`、
 * 同卡的输入框走默认档,并排矮一截;编辑器检查器里的 26px 则干脆不在任何一档上。
 *
 * 现在的刻度是 `FIELD_SIZE`(control-size.ts):`xs` 28、`sm` 32、`md` 40,和 `<Button size>`
 * 同名同高。这条拦下两种形状:
 *
 * - 字段的 className 里有**数字高度**(`h-8`、`h-[26px]`、`min-h-9`)或**竖向内距**(`py-*`/
 *   `pt-*`/`pb-*`)—— 固定高度的框里,竖向内距只会把字挤偏,不会改高度,写它就是在捏刻度;
 * - 传了 `size` 又写高度类 —— 两处说了两个高度,以后改一处另一处就成了谎话。
 *
 * 和 `buttonScale.test.ts` 同一套边界:只认前面紧挨空白或引号的类,变体前缀(`md:h-7`)与子选择器
 * (`[&>svg]:h-4`)不算;非数字的 `h-full`/`h-auto` 也不算,那是「跟着容器走」,不是刻度。
 *
 * **不管的:** `Textarea` —— 多行框的高度是「要放几行字」,不是一行控件的档位;`DraftInput`
 * 等不带样式的原生框、`CommandInput`(浮层列表的搜索行)、自定义 `trigger` 里自己画的按钮 ——
 * 它们不是 FIELD_SIZE 的字段。
 *
 * 存量冻结在 GRANDFATHERED(现在是空的),只减不增。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

/**
 * 走 FIELD_SIZE 档位的字段。`Pick` 是 scenes/boards 里转交给 OptionPicker 的薄壳,className
 * 原样透下去,所以一样要管。
 */
const FIELDS = ["Input", "SelectTrigger", "OptionPicker", "SearchableSelect", "Combobox", "TimePicker", "Pick"];

/** 存量:`文件: 类名`(不带行号,同 buttonScale / gridAxes)。只减不增。 */
const GRANDFATHERED = new Set<string>([]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : sourceFiles(full);
    return /\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name) ? [full] : [];
  });
}

/** 去掉注释 —— 免得棘轮被「注释里解释旧写法是 h-8」喂饱。 */
function strip(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/** 切出 `<Tag ...>` 开标签:按花括号深度配对,跳过 `=>` 里的 `>`。 */
function openTags(text: string, tag: string): string[] {
  const out: string[] = [];
  const re = new RegExp(`<${tag}(?=[\\s/>])`, "g");
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    let depth = 0;
    for (let i = re.lastIndex; i < text.length; i += 1) {
      const ch = text[i];
      if (ch === "{") depth += 1;
      else if (ch === "}") depth -= 1;
      else if (ch === ">" && depth === 0 && text[i - 1] !== "=") {
        out.push(text.slice(match.index, i + 1));
        break;
      }
    }
  }
  return out;
}

/**
 * 标签**自己**的某个属性(花括号深度为 0 处)。别的属性里嵌着的 JSX —— `trigger={<button
 * className="h-8">}`、`icon={<Camera size={14}/>}` —— 说的是别的元素,不归这里。
 */
function attribute(tag: string, name: string): string | null {
  let depth = 0;
  for (let i = 0; i < tag.length; i += 1) {
    const ch = tag[i];
    if (ch === "{") depth += 1;
    else if (ch === "}") depth -= 1;
    if (depth !== 0 || !tag.startsWith(`${name}=`, i) || !/\s/.test(tag[i - 1] ?? "")) continue;
    const start = i + name.length + 1;
    const open = tag[start];
    if (open === '"' || open === "'") return tag.slice(start + 1, tag.indexOf(open, start + 1));
    if (open !== "{") return null;
    let inner = 0;
    for (let j = start; j < tag.length; j += 1) {
      if (tag[j] === "{") inner += 1;
      else if (tag[j] === "}" && --inner === 0) return tag.slice(start + 1, j);
    }
  }
  return null;
}

/** 数字高度、下限高度、竖向内距。`!` 前缀(important)也算。 */
const HEIGHTISH = /(?<=[\s"'`])!?((?:min-h|h|py|pt|pb)-(?:\d|\[)[^\s"'`]*)/g;

interface Hit {
  file: string;
  classes: string[];
  sized: boolean;
}

function findHits(): Hit[] {
  const hits: Hit[] = [];
  for (const path of sourceFiles(SRC)) {
    const text = strip(readFileSync(path, "utf8"));
    const file = relative(SRC, path).replaceAll("\\", "/");
    for (const tag of FIELDS) {
      for (const open of openTags(text, tag)) {
        const className = attribute(open, "className");
        if (!className) continue;
        const classes = [...new Set([...` ${className} `.matchAll(HEIGHTISH)].map((m) => m[1]))].sort();
        if (classes.length) hits.push({ file, classes, sized: attribute(open, "size") != null });
      }
    }
  }
  return hits;
}

const key = (hit: Hit) => `${hit.file}: ${hit.classes.join(" ")}`;

describe("字段高度刻度", () => {
  const hits = findHits();

  it("字段不在 className 里改高度或竖向内距", () => {
    const offenders = hits.filter((hit) => !GRANDFATHERED.has(key(hit))).map(key);
    expect(
      offenders,
      "改用 size 档位(xs=28、sm=32、md=40,和同名的 Button 同高);挑档看这一行其它控件多高。" +
        "确实缺一档就往 control-size.ts 的 FIELD_SIZE 里加,别写在 className 里",
    ).toEqual([]);
  });

  it("传了 size 就不许再写高度类 —— 两处说两个高度", () => {
    const doubled = hits.filter((hit) => hit.sized).map(key);
    expect(doubled, "高度只由 size 说,删掉 className 里的那个").toEqual([]);
  });

  it("存量清单只减不增", () => {
    const live = new Set(hits.map(key));
    const stale = [...GRANDFATHERED].filter((entry) => !live.has(entry));
    expect(stale, "已经改用 size 了,从 GRANDFATHERED 删掉这几行").toEqual([]);
  });

  it("扫得到东西 —— 空棘轮不算数", () => {
    //: 这个仓库出过「解析器坏了、什么都没扫到、于是永远全绿」的棘轮。拿一处已知用 size 的
    //: 调用点当探针:它得被切成开标签、读出 size。
    const probe = strip(readFileSync(join(SRC, "components/app/CanvasNodeSearch.tsx"), "utf8"));
    const inputs = openTags(probe, "Input");
    expect(inputs.length).toBeGreaterThan(0);
    expect(inputs.map((tag) => attribute(tag, "size"))).toContain("sm");
    //: 解析器本身:抓得到 h-8 / h-[26px] / py-1,放过变体前缀与嵌套 JSX 里的类。
    const sample = '<Input size="xs" icon={<X className="h-4" />} className={cn("h-8 md:h-7 [&>svg]:h-4", on && "h-[26px] py-1")} />';
    const [open] = openTags(sample, "Input");
    expect([...` ${attribute(open, "className")} `.matchAll(HEIGHTISH)].map((m) => m[1])).toEqual(["h-8", "h-[26px]", "py-1"]);
  });
});
