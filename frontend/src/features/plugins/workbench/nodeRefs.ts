/**
 * 「助手」回复里指节点的写法(ADR 0042 §5):根图上的 `#12`,子图里的从根图往里走 `#12:5`。渲染之前换成页面引用的链接
 * (见 components/markdown/markdownRefs),点了在画布上定位那个节点。
 *
 * 只换正文里的:围栏代码块、行内代码、已经是链接的、网址里的(`…/#12`)、HTML 实体(`&#12;`)、单词连着的(`issue#12`)不动。
 */
import { MARKDOWN_REF } from "@/components/markdown/markdownRefs";

/** 和后端 `comfy_locate` 认的写法一致:根图编号可以是负的,子图里的每一段不带负号,最多 16 层。 */
const NODE_REF = /(^|[^\w&#/[\]`])#(-?\d{1,10}(?::\d{1,10}){0,16})(?!\w|:\d)/g;
const FENCE = /^\s{0,3}(`{3,}|~{3,})/;
const INLINE_CODE = /(`+)[^`]*?\1/g;

export function linkNodeRefs(markdown: string): string {
  let fence = "";
  return markdown
    .split("\n")
    .map((line) => {
      const opened = FENCE.exec(line)?.[1];
      if (fence) {
        if (opened && opened[0] === fence[0] && opened.length >= fence.length) fence = "";
        return line;
      }
      if (opened) {
        fence = opened;
        return line;
      }
      return outsideCode(line, (text) => text.replace(NODE_REF, (_, before: string, ref: string) => `${before}[#${ref}](${MARKDOWN_REF}${ref})`));
    })
    .join("\n");
}

/** 一行里行内代码以外的那几段交给 `change`。 */
function outsideCode(line: string, change: (text: string) => string): string {
  let out = "";
  let last = 0;
  for (const match of line.matchAll(INLINE_CODE)) {
    out += change(line.slice(last, match.index)) + match[0];
    last = match.index + match[0].length;
  }
  return out + change(line.slice(last));
}
