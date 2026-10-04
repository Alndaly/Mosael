import type { Editor } from "@tiptap/react";

/**
 * 笔记编辑器 ⇄ 笔记页助手之间的两件事。
 *
 * **选区要按正文 Markdown 说。** 助手改正文用 edit_note,锚点是存下来的那份 Markdown 里逐字的原文
 * (见 backend/app/domain/notes/passages)。编辑器里看到的是去掉标记的纯文字:选中「周一和剪辑组对了节奏」,
 * 存的却是 `周一和**剪辑组**对了节奏` —— 拿纯文字去找,一带格式就找不到。
 *
 * **服务端改了一段,编辑器按最小差异接。** 整份 setContent 会把光标扔回开头(正在看的那一处跟着跳走);
 * 只替换改了的那一段,光标照常映射,撤销一步就回到改之前。
 */

export interface NoteSelection {
  /** 选中的那段在正文 Markdown 里的原文;只是一个光标时为空串。 */
  text: string;
  /** 在正文 Markdown 里的起止下标。 */
  start: number;
  end: number;
  /** 紧挨着的前后文(各至多 SELECTION_CONTEXT_CHARS 字)。光标处插入时拿它当锚点。 */
  before: string;
  after: string;
}

/** 前后文各取多少字:够让锚点在一篇笔记里唯一,又不把整篇搬进上下文。 */
export const SELECTION_CONTEXT_CHARS = 40;

//: 私用区的两个字:Markdown 序列化不会转义它们,正文里也不会有。
const START = "";
const END = "";

/**
 * 当前选区 / 光标在正文 Markdown 里是哪一段。
 *
 * 做法:在文档的一份**不提交**的副本里,选区两端各插一个记号字,整篇序列化,数记号的位置 —— 这样标记
 * (`**`、链接、列表符号)怎么排都是序列化器自己排的,不用在这里再推一遍。去掉记号之后得和原文逐字一样才算数;
 * 不一样(选中的是一张图、记号挤乱了标记)就退回纯文字,在原文里找得到唯一一处才给位置。
 */
export function readNoteSelection(editor: Editor): NoteSelection | null {
  if (editor.isDestroyed || !editor.markdown) return null;
  const { from, to, empty } = editor.state.selection;
  const markdown = editor.getMarkdown();
  try {
    const tr = editor.state.tr;
    if (!empty) tr.insertText(END, to);
    tr.insertText(START, from);
    const marked = editor.markdown.serialize(tr.doc.toJSON());
    const start = marked.indexOf(START);
    const endMark = empty ? start + 1 : marked.indexOf(END);
    if (start >= 0 && endMark > start && marked.replace(START, "").replace(END, "") === markdown) {
      return around(markdown, start, endMark - 1);
    }
  } catch {
    // 记号插不进去(选区落在不收文字的地方):走下面的纯文字。
  }
  const text = editor.state.doc.textBetween(from, to, "\n");
  const at = text ? markdown.indexOf(text) : -1;
  if (at >= 0 && markdown.indexOf(text, at + 1) < 0) return around(markdown, at, at + text.length);
  return text ? { text, start: -1, end: -1, before: "", after: "" } : null;
}

function around(markdown: string, start: number, end: number): NoteSelection {
  return {
    text: markdown.slice(start, end),
    start,
    end,
    before: markdown.slice(Math.max(0, start - SELECTION_CONTEXT_CHARS), start),
    after: markdown.slice(end, end + SELECTION_CONTEXT_CHARS),
  };
}

/**
 * 把编辑器里的文档换成 `markdown` 那一版,只动不一样的那一段。返回是否真的改了。
 *
 * 这一步**进撤销历史**(智能体改的一段,用户 Ctrl+Z 就能退回),但**不回灌 onUpdate**:接过来的就是服务端那一版,
 * 不是用户的新编辑,回灌的话草稿会被标成「待保存」、再原样存一遍。撤销那一步是用户的编辑,照常回灌、照常保存。
 */
export function followMarkdown(editor: Editor, markdown: string): boolean {
  if (editor.isDestroyed || !editor.markdown) return false;
  const next = editor.schema.nodeFromJSON(editor.markdown.parse(markdown));
  const doc = editor.state.doc;
  if (doc.content.findDiffStart(next.content) == null) return false;
  const tr = editor.state.tr;
  //: 从后往前落:前面那些块在原文档里的位置不受后面改动的影响。一个事务 = 撤销一步。
  for (const hunk of blockHunks(doc, next).reverse()) replaceHunk(tr, doc, next, hunk);
  tr.setMeta("preventUpdate", true);
  editor.view.dispatch(tr);
  return true;
}

type PMNode = Editor["state"]["doc"];
type Hunk = { fromA: number; toA: number; fromB: number; toB: number };
/** 中间那段块数的乘积超过它就不逐块对齐了,整段当一处改动(只是光标映射粗一点)。 */
const BLOCK_ALIGN_LIMIT = 250_000;

/**
 * 两版文档在**顶层块**上的差异:哪几段连续的块被换掉了。
 *
 * 只比首尾的话,智能体在开头和结尾各改一处,中间所有没动的段落都会被算进那一次替换 —— 停在中间的光标
 * 被挤到替换的边上,选区被撑成大半篇。按块对齐(最长公共子序列)之后,没动的块原样留着。
 */
function blockHunks(a: PMNode, b: PMNode): Hunk[] {
  const A = Array.from({ length: a.childCount }, (_, i) => a.child(i));
  const B = Array.from({ length: b.childCount }, (_, i) => b.child(i));
  const offsets = (nodes: PMNode[]) => {
    const at = [0];
    for (const node of nodes) at.push(at[at.length - 1] + node.nodeSize);
    return at;
  };
  const posA = offsets(A);
  const posB = offsets(B);
  let head = 0;
  while (head < A.length && head < B.length && A[head].eq(B[head])) head += 1;
  let tail = 0;
  while (tail < A.length - head && tail < B.length - head && A[A.length - 1 - tail].eq(B[B.length - 1 - tail])) tail += 1;
  const [a0, a1, b0, b1] = [head, A.length - tail, head, B.length - tail];
  const hunk = (i0: number, i1: number, j0: number, j1: number): Hunk => ({ fromA: posA[i0], toA: posA[i1], fromB: posB[j0], toB: posB[j1] });
  if ((a1 - a0) * (b1 - b0) > BLOCK_ALIGN_LIMIT) return [hunk(a0, a1, b0, b1)];
  //: lcs[i][j] = A[i..a1) 与 B[j..b1) 的最长公共子序列长度。
  const lcs = Array.from({ length: a1 - a0 + 1 }, () => new Array<number>(b1 - b0 + 1).fill(0));
  for (let i = a1 - 1; i >= a0; i -= 1) {
    for (let j = b1 - 1; j >= b0; j -= 1) {
      lcs[i - a0][j - b0] = A[i].eq(B[j]) ? lcs[i - a0 + 1][j - b0 + 1] + 1 : Math.max(lcs[i - a0 + 1][j - b0], lcs[i - a0][j - b0 + 1]);
    }
  }
  const hunks: Hunk[] = [];
  let [i, j, si, sj] = [a0, b0, a0, b0];
  while (i < a1 || j < b1) {
    if (i < a1 && j < b1 && A[i].eq(B[j])) {
      if (si < i || sj < j) hunks.push(hunk(si, i, sj, j));
      i += 1; j += 1; si = i; sj = j;
    } else if (j < b1 && (i === a1 || lcs[i - a0][j - b0 + 1] >= lcs[i - a0 + 1][j - b0])) j += 1;
    else i += 1;
  }
  if (si < a1 || sj < b1) hunks.push(hunk(si, a1, sj, b1));
  return hunks;
}

/** 落一处块级差异;两边都有内容时再往里收到真正不同的那几个字(一段里只改了半句,就只换那半句)。 */
function replaceHunk(tr: Editor["state"]["tr"], a: PMNode, b: PMNode, { fromA, toA, fromB, toB }: Hunk): void {
  if (fromA === toA || fromB === toB) {
    tr.replace(fromA, toA, b.slice(fromB, toB));
    return;
  }
  const oldPart = a.slice(fromA, toA).content;
  const newPart = b.slice(fromB, toB).content;
  const start = oldPart.findDiffStart(newPart) ?? 0;
  let { a: endA, b: endB } = oldPart.findDiffEnd(newPart) ?? { a: oldPart.size, b: newPart.size };
  //: 两头比出来的公共部分重叠了(一段重复的文字被删掉一份):把尾部往后推,区间才不会倒过来。
  const overlap = start - Math.min(endA, endB);
  if (overlap > 0) {
    endA += overlap;
    endB += overlap;
  }
  tr.replace(fromA + start, fromA + endA, b.slice(fromB + start, fromB + endB));
}

/**
 * 按一段**正文原文**(带 Markdown 记号,见 NoteSelection.text)找回它在编辑器文档里的位置。
 *
 * 对话气泡里那行选区摘录点进来时用。原文先按同一个序列化器解析成纯文字,再在文档的文字里找;同一段字出现
 * 多次时挑相对位置离 `start`(原文在 Markdown 里的下标)最近的那处。找不到(那段已经改掉了)返回 null。
 */
export function findPassage(editor: Editor, markdown: string, start: number): { from: number; to: number } | null {
  if (editor.isDestroyed || !editor.markdown) return null;
  let needle = markdown;
  try {
    const parsed = editor.schema.nodeFromJSON(editor.markdown.parse(markdown));
    needle = parsed.textBetween(0, parsed.content.size, "\n");
  } catch {
    // 解析不了就按原样找。
  }
  needle = needle.trim();
  if (!needle) return null;
  //: 文档的文字,块与块之间一个换行(和上面 textBetween 的分隔一致),逐字记下它在文档里的位置。
  const chars: string[] = [];
  const at: number[] = [];
  editor.state.doc.descendants((node, pos) => {
    if (node.isTextblock && chars.length) {
      chars.push("\n");
      at.push(pos);
    }
    if (node.isText) {
      for (let i = 0; i < node.text!.length; i += 1) {
        chars.push(node.text![i]);
        at.push(pos + i);
      }
    }
  });
  const text = chars.join("");
  const expected = start >= 0 ? start / Math.max(1, editor.getMarkdown().length) : 0;
  let best = -1;
  for (let index = text.indexOf(needle); index >= 0; index = text.indexOf(needle, index + 1)) {
    if (best < 0 || Math.abs(index / text.length - expected) < Math.abs(best / text.length - expected)) best = index;
  }
  if (best < 0) return null;
  return { from: at[best], to: at[best + needle.length - 1] + 1 };
}
