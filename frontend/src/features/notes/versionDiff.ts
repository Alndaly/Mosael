import { diffText, type DiffSegment } from "@/lib/textDiff";

/**
 * 两版笔记正文的差异,给版本记录里的对比用。
 *
 * 先按**行**对齐:没改的行原样成段(长的那几段由界面折起来),改了的相邻几行合成一块,块里再按字对齐(lib/textDiff,
 * 和改笔记确认卡同一套)。直接整篇逐字对齐不行:改动散在开头和结尾时,掐头去尾之后中间还是几乎整篇,超过逐字对齐的
 * 上限就退成「整篇删 + 整篇加」。
 *
 * 一块改动里两边几乎没有共同的字(整行换成了不相干的话)时,不逐字对齐:那样画出来是红绿交错的一串,哪句是哪句都
 * 认不出。这种块拆成「删掉的一段」和「加上的一段」两块,各占一段。
 */

export type DocumentDiffBlock =
  | { kind: "same"; lines: string[] }
  | { kind: "change"; segments: DiffSegment[] };

/** 中间那段两边行数之积超过它就不逐行对齐,整段当成一块改动(块里仍按字对齐,有自己的上限)。 */
const LINE_ALIGN_LIMIT = 1_000_000;
/** 一块改动里,共同的字占较短那一边的比例低于它,就当成整段换掉(删一段、加一段)。不算空白。 */
const MIN_SHARED = 0.5;

const visible = (text: string) => text.replace(/\s/g, "").length;

const linesOf = (text: string) => (text === "" ? [] : text.split("\n"));

export function diffDocument(before: string, after: string): DocumentDiffBlock[] {
  const a = linesOf(before);
  const b = linesOf(after);
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
  let tail = 0;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail += 1;

  const out: DocumentDiffBlock[] = [];
  const same = (lines: string[]) => {
    if (!lines.length) return;
    const last = out[out.length - 1];
    if (last?.kind === "same") last.lines.push(...lines);
    else out.push({ kind: "same", lines: [...lines] });
  };
  const change = (removed: string[], added: string[]) => {
    const before = removed.join("\n");
    const after = added.join("\n");
    if (!removed.length && !added.length) return;
    const segments = diffText(before, after);
    const shared = segments.reduce((sum, one) => sum + (one.kind === "same" ? visible(one.text) : 0), 0);
    const shorter = Math.min(visible(before), visible(after));
    if (shorter > 0 && shared / shorter < MIN_SHARED) {
      out.push({ kind: "change", segments: [{ kind: "del", text: before }] }, { kind: "change", segments: [{ kind: "ins", text: after }] });
    } else {
      out.push({ kind: "change", segments });
    }
  };

  same(a.slice(0, head));
  const midA = a.slice(head, a.length - tail);
  const midB = b.slice(head, b.length - tail);
  if (midA.length * midB.length > LINE_ALIGN_LIMIT) {
    change(midA, midB);
  } else {
    //: lcs[i * width + j] = midA[i..] 与 midB[j..] 的最长公共子序列(按行)。
    const width = midB.length + 1;
    const lcs = new Int32Array((midA.length + 1) * width);
    for (let i = midA.length - 1; i >= 0; i -= 1) {
      for (let j = midB.length - 1; j >= 0; j -= 1) {
        lcs[i * width + j] = midA[i] === midB[j] ? lcs[(i + 1) * width + j + 1] + 1 : Math.max(lcs[(i + 1) * width + j], lcs[i * width + j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    let removed: string[] = [];
    let added: string[] = [];
    while (i < midA.length || j < midB.length) {
      if (i < midA.length && j < midB.length && midA[i] === midB[j]) {
        change(removed, added);
        removed = [];
        added = [];
        same([midA[i]]);
        i += 1;
        j += 1;
      } else if (i < midA.length && (j === midB.length || lcs[(i + 1) * width + j] >= lcs[i * width + j + 1])) {
        removed.push(midA[i]);
        i += 1;
      } else {
        added.push(midB[j]);
        j += 1;
      }
    }
    change(removed, added);
  }
  same(a.slice(a.length - tail));
  return out;
}
