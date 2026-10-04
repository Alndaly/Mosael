import type { MessageKey } from "@/app/messages";
import type { Note } from "@/api/domains/notes";
import type { NoteSelection } from "./noteSelection";

/**
 * 笔记页助手每条消息附带的隐藏上下文:这是哪一篇、正文、选中的那段或光标在哪。
 *
 * **正文按长短给。** 短的整篇附上 —— 「总结一下」「列个提纲」不必再多一次工具调用;长的只给开头,说清用
 * read_note 分段读(它一页 12000 字,`truncated` 为真就接着读)。整篇塞进来的话,一条消息的上下文上限
 * (composerAttachments.MAX_CONTEXT_CHARS,和附件、引用的笔记共用)一篇长文就占满了,而且每条消息都重发一遍。
 *
 * **选区给的是正文原文**(见 noteSelection):助手改它用 edit_note,锚点要逐字一致。
 */

type Translate = (key: MessageKey) => string;
type NoteFacts = Pick<Note, "id" | "title" | "revision" | "markdown">;

/** 短于它的笔记整篇附上。 */
export const NOTE_BODY_INLINE_CHARS = 1200;
/** 长笔记附上的开头。 */
const NOTE_BODY_HEAD_CHARS = 400;
/** 短于它的选区原样附上;再长只给头尾。 */
const SELECTION_INLINE_CHARS = 900;
const SELECTION_HEAD_CHARS = 300;
const SELECTION_TAIL_CHARS = 200;
/** 这段上下文最长多少字 —— 给附件和引用的笔记留出那条 4000 字上限的余量。 */
export const NOTE_AGENT_CONTEXT_BUDGET = 3000;

export function noteAgentContext(t: Translate, note: NoteFacts | null, selection: NoteSelection | null): string {
  if (!note) return t("noteAgentNoNote");
  const markdown = note.markdown;
  const parts = [
    fill(t("noteAgentContext"), { title: note.title || "—", id: note.id, revision: note.revision, chars: markdown.length }),
  ];
  if (markdown.length <= NOTE_BODY_INLINE_CHARS) {
    if (markdown.trim()) parts.push(fill(t("noteAgentBody"), { body: markdown }));
  } else {
    parts.push(fill(t("noteAgentBodyHead"), { body: `${markdown.slice(0, NOTE_BODY_HEAD_CHARS)}…` }));
  }
  if (selection?.text) parts.push(selectionPart(t, selection));
  else if (selection && selection.start >= 0) {
    parts.push(fill(t("noteAgentCursor"), { before: selection.before, after: selection.after }));
  }
  return parts.join("\n\n").slice(0, NOTE_AGENT_CONTEXT_BUDGET);
}

function selectionPart(t: Translate, selection: NoteSelection): string {
  const { text, start, end } = selection;
  if (start < 0) return fill(t("noteAgentSelectionLoose"), { text: clip(text, SELECTION_INLINE_CHARS) });
  if (text.length <= SELECTION_INLINE_CHARS) return fill(t("noteAgentSelection"), { text, start, end });
  return fill(t("noteAgentSelectionLong"), {
    head: text.slice(0, SELECTION_HEAD_CHARS),
    tail: text.slice(-SELECTION_TAIL_CHARS),
    start,
    end,
    length: end - start,
  });
}

function clip(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max)}…`;
}

/** 只扫模板本身:填进去的正文里就算有 `{x}` 也不会被再换一次。 */
function fill(template: string, params: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => (name in params ? String(params[name]) : whole));
}
