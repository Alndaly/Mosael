/**
 * 数据里那一行字的 markdown —— 应用里**唯一**一处认它的地方。
 *
 * 插件清单的工具说明和配置帮助、工作流节点的说明和字段帮助、智能体工具说明、确认卡摘要,
 * 这些字是写给人(或模型)看的,会带 `**强调**`、`` `代码` ``、`[链接](…)`。直接塞进 JSX
 * 记号就原样露出来。只留两条出口:
 *
 * - `<InlineMarkdown>`(./InlineMarkdown.tsx):要显示格式的地方。
 * - `toPlainText`:必须是纯文本的地方(搜索匹配、`title` / `aria-label`、只截一行的副标题)。
 *
 * 为什么不用 `AgentMarkdown`(Streamdown):它是**块级**渲染器,根上永远包一层 `<div>`,
 * 每段还各包一层 —— 放进 `<small>`、`<button>`、下拉选项里就是非法嵌套。这些字段都是一句话
 * 或一小段,只需要行内记号:粗体、斜体、删除线、行内代码、链接、换行。
 *
 * 官网(website/src/lib/inline-markdown.ts)是同一套规则的另一份 —— 两个包不共享源码。
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

function textOf(nodes: InlineNode[]): string {
  return nodes
    .map((node) => (node.type === "text" || node.type === "code" ? node.value : node.type === "break" ? " " : textOf(node.children)))
    .join("");
}

/** 去掉记号、只留字面,空白收成一个空格 —— 搜索、`title`、`aria-label`、单行副标题用这个。 */
export function toPlainText(source: string): string {
  return textOf(parseInline(source)).replace(/\s+/g, " ").trim();
}
