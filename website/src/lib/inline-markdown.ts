import { createElement, Fragment, type ReactNode } from "react";

/**
 * 数据里那一行字的 markdown —— 全站**唯一**一处认它的地方。
 *
 * 插件清单、工作流目录、发布说明、文档 frontmatter 里的句子是写给人(或模型)看的,会带
 * `**强调**`、`` `代码` ``、`[链接](…)`。页面把它们当纯文本塞进 JSX,记号就原样露出来;
 * 每个页面各写一条正则去剥,剥掉的又各不相同(有的只剥 `**`,有的连 `_` 一起剥 ——
 * `run_host_code` 就成了 `runhostcode`)。所以只留两条出口:
 *
 * - `InlineMarkdown`:要显示格式的地方(详情页的简介、工具说明、更新要点)。
 * - `toPlainText`:必须是纯文本的地方(`<title>`、meta description、搜索索引、只截一两行的
 *   卡片简介、目录和锚点)。
 *
 * 只认**行内**记号:粗体、斜体、删除线、行内代码、链接、换行。这些字段都是一句话或一小段,
 * 标题、列表、表格进不来;真要整篇 markdown 的地方(文档正文、插件 README)走 MDX。
 *
 * 这个文件不引用别的站内模块、组件也不用 JSX —— `node --test` 直接拿它跑(见
 * test/inline-markdown.test.mjs),测的就是页面用的这一份。
 */
export type InlineNode =
  | { type: "text"; value: string }
  | { type: "code"; value: string }
  | { type: "break" }
  | { type: "strong" | "emphasis" | "delete"; children: InlineNode[] }
  | { type: "link"; href: string; children: InlineNode[] };

const PUNCTUATION = /[!-/:-@[-`{-~]/;
const WORD = /[\p{L}\p{N}]/u;
const SPACE = /\s/;

/** 反引号串:从 `start` 起数一样的字符有几个。 */
function runLength(source: string, start: number): number {
  let end = start;
  while (source[end] === source[start]) end += 1;
  return end - start;
}

/** 行内代码:找长度**正好相同**的收尾反引号;找不到就不是代码。返回收尾之后的位置。 */
function codeSpan(source: string, start: number): { value: string; end: number } | null {
  const size = runLength(source, start);
  let at = start + size;
  while (at < source.length) {
    const next = source.indexOf("`", at);
    if (next < 0) return null;
    const run = runLength(source, next);
    if (run === size) {
      let value = source.slice(start + size, next).replace(/\n/g, " ");
      if (/^ .*[^ ].* $/.test(value)) value = value.slice(1, -1);
      return { value, end: next + run };
    }
    at = next + run;
  }
  return null;
}

/** 跳过一个结构(转义、代码)时下一步该从哪儿接着扫 —— 找收尾记号时不能扫进代码里去。 */
function skipAtom(source: string, at: number): number {
  if (source[at] === "\\" && PUNCTUATION.test(source[at + 1] ?? "")) return at + 2;
  if (source[at] === "`") {
    const code = codeSpan(source, at);
    return code ? code.end : at + runLength(source, at);
  }
  return at + 1;
}

/** `[文字](地址)`:返回文字、地址和结束位置。方括号可以嵌套;地址里不能有空白,括号可以成对出现一层。 */
function linkAt(source: string, start: number): { label: string; href: string; end: number } | null {
  let depth = 0;
  let at = start;
  while (at < source.length) {
    const char = source[at];
    if (char === "[") depth += 1;
    else if (char === "]") {
      depth -= 1;
      if (depth === 0) break;
    }
    at = char === "\\" || char === "`" ? skipAtom(source, at) : at + 1;
  }
  if (depth !== 0 || source[at + 1] !== "(") return null;
  const target = /^\(\s*(<[^<>\n]*>|(?:[^\s()]|\([^\s()]*\))*)(?:\s+"[^"]*")?\s*\)/.exec(source.slice(at + 1));
  if (!target) return null;
  const href = target[1].replace(/^<|>$/g, "");
  return { label: source.slice(start + 1, at), href, end: at + 1 + target[0].length };
}

function flanks(before: string, after: string, marker: string): { open: boolean; close: boolean } {
  // 简化过的 CommonMark 规则:开头记号后面不能是空白,收尾记号前面不能是空白;`_` 另外
  // 不能夹在词中间 —— 否则 snake_case 的名字会被拆成斜体。
  const open = after !== "" && !SPACE.test(after) && !(marker === "_" && WORD.test(before));
  const close = before !== "" && !SPACE.test(before) && !(marker === "_" && WORD.test(after));
  return { open, close };
}

/** 从 `from` 起找一个长度正好是 `size` 的收尾记号;别的长度的同种记号整串跳过(那是嵌套的)。 */
function closerOf(source: string, from: number, marker: string, size: number): number {
  let at = from;
  while (at < source.length) {
    const char = source[at];
    if (char === "\\" || char === "`") {
      at = skipAtom(source, at);
      continue;
    }
    if (char !== marker) {
      at += 1;
      continue;
    }
    const run = runLength(source, at);
    if (run === size && flanks(source[at - 1] ?? "", source[at + run] ?? "", marker).close) return at;
    at += run;
  }
  return -1;
}

function push(nodes: InlineNode[], value: string) {
  const last = nodes.at(-1);
  if (last?.type === "text") last.value += value;
  else if (value) nodes.push({ type: "text", value });
}

export function parseInline(source: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  let at = 0;
  while (at < source.length) {
    const char = source[at];

    if (char === "\\" && source[at + 1] === "\n") {
      nodes.push({ type: "break" });
      at += 2;
      continue;
    }
    if (char === "\\" && PUNCTUATION.test(source[at + 1] ?? "")) {
      push(nodes, source[at + 1]);
      at += 2;
      continue;
    }

    if (char === "\n" || (char === " " && /^ *\n/.test(source.slice(at)))) {
      // 行尾两个空格或空一行 = 真换行;单个换行在 markdown 里只是一个空格。
      const gap = /^ *\n[ \t\n]*/.exec(source.slice(at))![0];
      const hard = /^ {2,}\n/.test(gap) || /\n[ \t]*\n/.test(gap);
      if (hard) nodes.push({ type: "break" });
      else push(nodes, " ");
      at += gap.length;
      continue;
    }

    if (char === "`") {
      const code = codeSpan(source, at);
      if (code) {
        nodes.push({ type: "code", value: code.value });
        at = code.end;
      } else {
        const size = runLength(source, at);
        push(nodes, source.slice(at, at + size));
        at += size;
      }
      continue;
    }

    if (char === "[" || (char === "!" && source[at + 1] === "[")) {
      const image = char === "!";
      const link = linkAt(source, image ? at + 1 : at);
      if (link) {
        const children = parseInline(link.label);
        // 图片在一行字里放不下,留它的替代文字。
        if (image) nodes.push(...children);
        else nodes.push({ type: "link", href: link.href, children });
        at = link.end;
        continue;
      }
    }

    if (char === "<") {
      const autolink = /^<(https?:\/\/[^\s<>]+)>/.exec(source.slice(at));
      if (autolink) {
        nodes.push({ type: "link", href: autolink[1], children: [{ type: "text", value: autolink[1] }] });
        at += autolink[0].length;
        continue;
      }
    }

    if (char === "*" || char === "_" || char === "~") {
      const run = runLength(source, at);
      const sizes = char === "~" ? (run === 2 ? [2] : []) : run >= 3 ? [3] : [run];
      let matched = false;
      for (const size of sizes) {
        if (!flanks(source[at - 1] ?? "", source[at + run] ?? "", char).open) break;
        const close = closerOf(source, at + size, char, size);
        if (close < 0 || close === at + size) continue;
        const children = parseInline(source.slice(at + size, close));
        if (char === "~") nodes.push({ type: "delete", children });
        else if (size === 1) nodes.push({ type: "emphasis", children });
        else if (size === 2) nodes.push({ type: "strong", children });
        else nodes.push({ type: "strong", children: [{ type: "emphasis", children }] });
        at = close + size;
        matched = true;
        break;
      }
      if (!matched) {
        push(nodes, source.slice(at, at + run));
        at += run;
      }
      continue;
    }

    push(nodes, char);
    at += 1;
  }
  return nodes;
}

/** 按**看得见的字数**截断:截在记号里面也不会留下半个 `**`,截掉的地方补一个省略号。 */
function truncate(nodes: InlineNode[], budget: { left: number }): InlineNode[] {
  const kept: InlineNode[] = [];
  for (const node of nodes) {
    if (budget.left <= 0) break;
    if (node.type === "text" || node.type === "code") {
      const chars = Array.from(node.value);
      if (chars.length > budget.left) {
        kept.push({ ...node, value: `${chars.slice(0, budget.left).join("").trimEnd()}…` });
        budget.left = 0;
        break;
      }
      budget.left -= chars.length;
      kept.push(node);
    } else if (node.type === "break") {
      budget.left -= 1;
      kept.push(node);
    } else {
      kept.push({ ...node, children: truncate(node.children, budget) });
    }
  }
  return kept;
}

function textOf(nodes: InlineNode[]): string {
  return nodes
    .map((node) => (node.type === "text" || node.type === "code" ? node.value : node.type === "break" ? " " : textOf(node.children)))
    .join("");
}

/** 去掉记号、只留字面,空白收成一个空格 —— `<title>`、meta、搜索索引、卡片摘要用这个。 */
export function toPlainText(source: string, maxLength?: number): string {
  const plain = textOf(parseInline(source)).replace(/\s+/g, " ").trim();
  if (maxLength === undefined || Array.from(plain).length <= maxLength) return plain;
  return `${Array.from(plain).slice(0, maxLength - 1).join("").trimEnd()}…`;
}

/** 链接只认 http(s) 和站内路径:数据里的 `javascript:` 渲染出去就是可点的。 */
export function safeHref(href: string): string | null {
  if (/^https?:\/\//i.test(href)) return href;
  if (/^\/(?!\/)/.test(href) || href.startsWith("#")) return href;
  return null;
}

const CLASSES = {
  strong: "font-semibold text-foreground",
  code: "rounded-sm bg-secondary px-1 py-px font-mono text-[0.9em] text-foreground [overflow-wrap:anywhere]",
  link: "text-primary underline underline-offset-2 hover:no-underline",
} as const;

function render(nodes: InlineNode[], links: boolean): ReactNode[] {
  return nodes.map((node, key) => {
    switch (node.type) {
      case "text":
        return node.value;
      case "code":
        return createElement("code", { key, className: CLASSES.code }, node.value);
      case "break":
        return createElement("br", { key });
      case "strong":
        return createElement("strong", { key, className: CLASSES.strong }, render(node.children, links));
      case "emphasis":
        return createElement("em", { key }, render(node.children, links));
      case "delete":
        return createElement("del", { key }, render(node.children, links));
      case "link": {
        const href = links ? safeHref(node.href) : null;
        const children = render(node.children, links);
        if (!href) return createElement(Fragment, { key }, children);
        const external = /^https?:/i.test(href);
        return createElement(
          "a",
          { key, href, className: CLASSES.link, ...(external ? { target: "_blank", rel: "noreferrer" } : {}) },
          children,
        );
      }
    }
  });
}

/**
 * 把一行数据里的行内 markdown 渲染出来。只出行内元素(`strong`/`em`/`code`/`a`/`br`),
 * 放进 `<p>`、`<li>`、`<span>` 都合法。
 *
 * `links={false}`:放在整块可点的卡片或按钮里时用 —— 链接里套链接是无效的 HTML。
 * `maxLength`:按看得见的字数截断(见 `truncate`)。
 */
export function InlineMarkdown({ text, links = true, maxLength }: { text: string; links?: boolean; maxLength?: number }): ReactNode {
  const nodes = parseInline(text);
  return createElement(Fragment, null, render(maxLength === undefined ? nodes : truncate(nodes, { left: maxLength }), links));
}
