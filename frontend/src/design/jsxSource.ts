/**
 * 给源码棘轮用的一把小 JSX 扫描器:找开标签、读它的属性、取它的子内容。
 *
 * 不是解析器 —— 它不认识 TypeScript,只认得出「看起来像 JSX 开标签」的那一段:`<` 前面不能是
 * 标识符或右括号(排除 `a < b` 和泛型 `Array<string>`),属性里的 `{…}` 按花括号配对、跳过字符串。
 * 棘轮拿它判断的都是「某个标签上有没有某个属性」这一类局部的事,够用;判错了会在棘轮里
 * 以一条具体的 `文件:行` 出现,当场就能看出是扫描器的问题还是代码的问题。
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

export const SRC = join(import.meta.dirname, "..");

/** src 下所有非测试的 .tsx(相对路径)。 */
export function tsxSources(): string[] {
  const walk = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) return entry.name === "node_modules" ? [] : walk(full);
      return entry.name.endsWith(".tsx") && !/\.test\.tsx$/.test(entry.name) ? [relative(SRC, full)] : [];
    });
  return walk(SRC).sort();
}

export function readSource(rel: string): string {
  return blankComments(readFileSync(join(SRC, rel), "utf8"));
}

/** 把注释换成等长的空白(保留换行):位置和行号不变,注释里提到的标签不会被当成代码。 */
export function blankComments(code: string): string {
  let out = "";
  let i = 0;
  while (i < code.length) {
    const c = code[i];
    const next = code[i + 1];
    if (c === "/" && next === "*") {
      const end = code.indexOf("*/", i + 2);
      const stop = end < 0 ? code.length : end + 2;
      out += code.slice(i, stop).replace(/[^\n]/g, " ");
      i = stop;
    } else if (c === "/" && next === "/" && code[i - 1] !== ":" && !insideJsxText(code, i)) {
      const end = code.indexOf("\n", i);
      const stop = end < 0 ? code.length : end;
      out += " ".repeat(stop - i);
      i = stop;
    } else if (c === '"' || c === "'" || c === "`") {
      const stop = skipString(code, i);
      out += code.slice(i, stop);
      i = stop;
    } else {
      out += c;
      i += 1;
    }
  }
  return out;
}

/** `https://…` 这种出现在 JSX 文本里的 `//` 不是注释。粗判:这一行 `//` 前面最近的是 `>` 而不是代码。 */
function insideJsxText(code: string, at: number): boolean {
  const lineStart = code.lastIndexOf("\n", at) + 1;
  const before = code.slice(lineStart, at);
  return /[^\s=(,]$/.test(before) && /<[^>]*>[^<{}]*$/.test(before);
}

function skipString(code: string, start: number): number {
  const quote = code[start];
  let i = start + 1;
  while (i < code.length) {
    const c = code[i];
    if (c === "\\") i += 2;
    else if (c === quote) return i + 1;
    else if (quote !== "`" && c === "\n") return i;
    else i += 1;
  }
  return i;
}

export type OpenTag = {
  tag: string;
  /** `<` 的位置。 */
  start: number;
  /** 开标签结束(`>` 之后)的位置。 */
  end: number;
  selfClosing: boolean;
  line: number;
  /** 属性名 → 原样的值(`"…"`、`{…}`;没有值的布尔属性是 `""`)。展开的 `{...props}` 不算。 */
  attrs: Map<string, string>;
};

const TAG_START = /<([A-Za-z][\w.]*)(?=[\s/>])/g;

/** 文件里所有 JSX 开标签,按出现顺序。 */
export function openTags(code: string): OpenTag[] {
  const out: OpenTag[] = [];
  TAG_START.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = TAG_START.exec(code))) {
    const start = match.index;
    if (!startsJsx(code, start)) continue;
    const parsed = parseAttrs(code, start + 1 + match[1].length);
    if (!parsed) continue;
    out.push({
      tag: match[1],
      start,
      end: parsed.end,
      selfClosing: parsed.selfClosing,
      line: code.slice(0, start).split("\n").length,
      attrs: parsed.attrs,
    });
  }
  return out;
}

/** `<` 前面是标识符、数字、`)`、`]` 的,是比较或泛型,不是 JSX(`return <div>` 例外)。 */
function startsJsx(code: string, at: number): boolean {
  let i = at - 1;
  while (i >= 0 && /\s/.test(code[i])) i -= 1;
  if (i < 0) return true;
  if (/[\w$)\]]/.test(code[i])) return /\b(return|yield|await|default)$/.test(code.slice(Math.max(0, i - 8), i + 1));
  return true;
}

function parseAttrs(code: string, from: number): { end: number; selfClosing: boolean; attrs: Map<string, string> } | null {
  const attrs = new Map<string, string>();
  let i = from;
  while (i < code.length) {
    const c = code[i];
    if (/\s/.test(c)) {
      i += 1;
    } else if (c === "/" && code[i + 1] === ">") {
      return { end: i + 2, selfClosing: true, attrs };
    } else if (c === ">") {
      return { end: i + 1, selfClosing: false, attrs };
    } else if (c === "{") {
      i = skipBraces(code, i);
    } else if (/[A-Za-z_]/.test(c)) {
      const name = /^[\w:.-]+/.exec(code.slice(i))![0];
      i += name.length;
      if (code[i] === "=") {
        i += 1;
        const valueStart = i;
        if (code[i] === '"' || code[i] === "'") i = skipString(code, i);
        else if (code[i] === "{") i = skipBraces(code, i);
        else return null;
        attrs.set(name, code.slice(valueStart, i));
      } else {
        attrs.set(name, "");
      }
    } else {
      return null;
    }
  }
  return null;
}

export function skipBraces(code: string, start: number): number {
  let depth = 0;
  let i = start;
  while (i < code.length) {
    const c = code[i];
    if (c === '"' || c === "'" || c === "`") {
      i = skipString(code, i);
      continue;
    }
    if (c === "{") depth += 1;
    else if (c === "}") {
      depth -= 1;
      if (depth === 0) return i + 1;
    }
    i += 1;
  }
  return i;
}

/** 一个非自闭合开标签的子内容(到配对的闭标签为止)。配不上就是 null。 */
export function childrenOf(code: string, tag: OpenTag): string | null {
  if (tag.selfClosing) return "";
  const opening = new RegExp(`<${tag.tag.replace(".", "\\.")}(?=[\\s/>])`, "g");
  const closing = `</${tag.tag}>`;
  let depth = 1;
  let i = tag.end;
  while (i < code.length) {
    const close = code.indexOf(closing, i);
    if (close < 0) return null;
    opening.lastIndex = i;
    const open = opening.exec(code);
    if (open && open.index < close) {
      const parsed = parseAttrs(code, open.index + 1 + tag.tag.length);
      if (parsed && !parsed.selfClosing) depth += 1;
      i = parsed ? parsed.end : open.index + 1;
      continue;
    }
    depth -= 1;
    if (depth === 0) return code.slice(tag.end, close);
    i = close + closing.length;
  }
  return null;
}

/** 属性值里的类名字符串(`"…"`、`{"…"}`、`{cn("…", …)}` 里出现的所有字符串字面量拼起来)。 */
export function classText(value: string | undefined): string {
  if (value === undefined) return "";
  return [...value.matchAll(/"([^"]*)"|'([^']*)'|`([^`]*)`/g)].map((m) => m[1] ?? m[2] ?? m[3]).join(" ");
}
