export type HighlightPart = { text: string; match: boolean };

/**
 * 把一段文字按查询词切成「命中 / 未命中」的片段,给搜索结果做高亮。
 *
 * 两条硬性要求:
 *
 * 1. **拼回去必须等于原文**。高亮只是把同一段字分开渲染,漏一个字、多一个字、顺序变了,
 *    用户看到的标题就不是库里那条了 —— 比不高亮糟得多。
 * 2. **不拿用户输入去拼正则**。搜一个 `(` 会让 `new RegExp` 当场抛,整个搜索框白屏。
 *    这里全程 indexOf 扫,元字符自然就是普通字符。
 *
 * 大小写不敏感地找,但切出来的是**原文的那几个字**(显示 `Mibu` 而不是用户敲的 `mibu`)。
 */
export function splitByQuery(text: string, query: string): HighlightPart[] {
  const needle = query.trim().toLowerCase();
  if (!needle || !text) return [{ text, match: false }];

  const haystack = text.toLowerCase();
  const parts: HighlightPart[] = [];
  let cursor = 0;
  for (;;) {
    const hit = haystack.indexOf(needle, cursor);
    if (hit < 0) break;
    if (hit > cursor) parts.push({ text: text.slice(cursor, hit), match: false });
    parts.push({ text: text.slice(hit, hit + needle.length), match: true });
    cursor = hit + needle.length;
  }
  if (parts.length === 0) return [{ text, match: false }];
  if (cursor < text.length) parts.push({ text: text.slice(cursor), match: false });
  return parts;
}
