/**
 * 两段文字的差异,给确认卡上「原文 → 新文」用:没变的照常,删去的划掉,新加的高亮。
 *
 * **按字 / 词对齐**:中日文一个字一个单位,西文一个词一个单位(把 quick → slow 画成换了五个字母没人读得懂),
 * 空白、标点各自成单位。先去掉首尾相同的部分,中间那段做最长公共子序列;中间那段太大(两段都很长、
 * 又几乎全改了)就不逐字对齐,整段删 + 整段加 —— 那种改动逐字画出来也只是一片红绿。
 */

export type DiffSegment = { kind: "same" | "del" | "ins"; text: string };

const TOKEN = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]|[\p{L}\p{N}_]+|\s+|./gsu;
/** 中间那段两边单位数之积超过它就不逐字对齐。 */
const ALIGN_LIMIT = 250_000;

export function diffText(before: string, after: string): DiffSegment[] {
  const a = before.match(TOKEN) ?? [];
  const b = after.match(TOKEN) ?? [];
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
  let tail = 0;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail += 1;
  const out: DiffSegment[] = [];
  const push = (kind: DiffSegment["kind"], text: string) => {
    if (!text) return;
    const last = out[out.length - 1];
    if (last?.kind === kind) last.text += text;
    else out.push({ kind, text });
  };
  push("same", a.slice(0, head).join(""));
  const midA = a.slice(head, a.length - tail);
  const midB = b.slice(head, b.length - tail);
  if (midA.length * midB.length > ALIGN_LIMIT) {
    push("del", midA.join(""));
    push("ins", midB.join(""));
  } else {
    //: lcs[i][j] = midA[i..] 与 midB[j..] 的最长公共子序列长度。
    const lcs = Array.from({ length: midA.length + 1 }, () => new Array<number>(midB.length + 1).fill(0));
    for (let i = midA.length - 1; i >= 0; i -= 1) {
      for (let j = midB.length - 1; j >= 0; j -= 1) {
        lcs[i][j] = midA[i] === midB[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < midA.length || j < midB.length) {
      if (i < midA.length && j < midB.length && midA[i] === midB[j]) {
        push("same", midA[i]);
        i += 1;
        j += 1;
      } else if (i < midA.length && (j === midB.length || lcs[i + 1][j] >= lcs[i][j + 1])) {
        //: 同一处先画删去的、再画新加的 —— 读起来是「把这几个字换成那几个字」。
        push("del", midA[i]);
        i += 1;
      } else {
        push("ins", midB[j]);
        j += 1;
      }
    }
  }
  push("same", a.slice(a.length - tail).join(""));
  return out;
}
