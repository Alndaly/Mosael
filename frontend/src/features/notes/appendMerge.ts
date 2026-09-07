import type { Note } from "@/api/domains/notes";

/** 追加的内容与原文之间的分隔符。**必须与后端 `domain/notes.APPEND_SEPARATOR` 逐字相同** ——
 *  见 contracts/shared-constants.json:不等时不会报错,前端只是再也认不出追加。 */
export const APPEND_SEPARATOR = "\n\n";

/**
 * 三方合并:本地草稿 + 服务端的一次**纯追加**。
 *
 * 现场是这样的:一边从逐字稿/字幕往笔记里追加,一边有人开着这篇文档在写。两件事都合法,
 * 而且落在文档的不同位置——追加只动末尾。所以这里不需要通用的文本合并,只需要认出
 * "这次差异是不是一次追加",是就把同样的尾巴接到本地草稿后面。
 *
 * 认的判据**不是"服务端正文以我们那份开头"** —— 那条太松:别人把最后一个词改长了也满足它,
 * 于是合并出来的是一句谁都没写过的话。判据是**后端拼接契约本身**:追加落库的形状一定是
 * `原文 + 分隔符 + 新内容`(`APPEND_SEPARATOR`),少了那个分隔符就不是追加。
 *
 * 认不出来就返回 `null`,交回给 409 + 冲突条 —— 那种情况没有安全的自动答案,而假装有一个
 * 才是真正会丢字的做法。
 *
 * @param known  我们上次与服务端对齐时的那一版(自动保存成功、或刚载入时的样子)
 * @param server 服务端现在的样子
 * @param local  本地草稿(可能带着还没保存的编辑)
 * @returns 合并后的草稿;不是一次纯追加时返回 `null`
 */
export function mergeAppendedNote(known: Note, server: Note, local: Note): Note | null {
  if (server.revision <= known.revision) return null;
  const appended = appendedTail(known.markdown, server.markdown);
  if (appended === null) return null;
  return {
    ...local,
    // 修订号跟着服务端走 —— 下一次自动保存的 base_revision 因此是对的,不会再撞 409。
    revision: server.revision,
    updated_at: server.updated_at,
    markdown: join(local.markdown, appended),
    sources: mergeSources(known, server, local),
  };
}

/** 服务端正文相对我们那一版多出来的那一段;不是一次追加则 `null`。 */
function appendedTail(known: string, server: string): string | null {
  // 空文档没有可拼的原文,后端的 join 会把分隔符省掉 —— 整份正文都是追加进来的。
  if (!known) return server;
  const prefix = known + APPEND_SEPARATOR;
  return server.startsWith(prefix) ? server.slice(prefix.length) : null;
}

/** 与后端 join 同构:哪一边为空就不留下一个空分隔符。 */
function join(head: string, tail: string): string {
  return [head, tail].filter(Boolean).join(APPEND_SEPARATOR);
}

/**
 * 本地新加的来源留着,服务端追加的来源也留着。
 *
 * 本地**删掉**的来源会被带回来:追加与删除撞在一起没有正确答案,而"出处多一条"比"出处
 * 凭空少一条"容易发现得多 —— 后者是静默丢失可追溯性,前者用户一眼就看见并能再删一次。
 */
function mergeSources(known: Note, server: Note, local: Note): Note["sources"] {
  const identity = (source: Note["sources"][number]) => JSON.stringify(source);
  const knownIds = new Set(known.sources.map(identity));
  return [...server.sources, ...local.sources.filter(source => !knownIds.has(identity(source)))];
}
