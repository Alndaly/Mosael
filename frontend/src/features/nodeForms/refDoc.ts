/**
 * 「带内联引用的一段文本」在**存储**和**编辑**之间的翻译。
 *
 * 存下去的永远是 `{{node.output}}` 这种字符串 —— 后端的插值引擎认的就是它,格式不能因为
 * 换了个编辑器就变。编辑器里它显示成一个可整体删除的标签,那只是表现层。
 *
 * 抽成纯函数是为了能单测:光标、输入法、撤销那些交给 ProseMirror,而"字符串 ↔ 文档"这一步
 * 是我们自己的逻辑,错了会**悄悄改掉用户的配置** —— 少一个花括号、把两个引用粘成一个,
 * 都要等到运行时才发作。
 */

/** 文档里的一个片段:纯文本,或一个引用。 */
export type Piece = { type: "text"; text: string } | { type: "ref"; ref: string };

//: 引用的样子。**非贪婪**:`{{a}} 和 {{b}}` 要切成两个引用,贪婪匹配会把中间那段一起吞掉。
const REF = /\{\{([^{}]+)\}\}/g;

/** 字符串 → 片段。 */
export function parsePieces(value: string): Piece[] {
  const text = String(value ?? "");
  const out: Piece[] = [];
  let last = 0;
  for (const match of text.matchAll(REF)) {
    const at = match.index ?? 0;
    if (at > last) out.push({ type: "text", text: text.slice(last, at) });
    out.push({ type: "ref", ref: match[1].trim() });
    last = at + match[0].length;
  }
  if (last < text.length) out.push({ type: "text", text: text.slice(last) });
  return out;
}

/** `{{llm-1.text}}` → `llm-1.text`。存的是模板,里面那截才是路径。 */
export function bareRef(ref: string): string {
  return ref.replace(/^\{\{|\}\}$/g, "");
}

/** 整格正好是一个引用(两头的空白不算,规范化同样认它是整格引用)时,给出里面那截路径;否则 null。 */
export function wholeRef(value: string): string | null {
  const pieces = parsePieces(value.trim());
  return pieces.length === 1 && pieces[0].type === "ref" ? pieces[0].ref : null;
}

/** 值里有没有一段 `{{…}}` 引用。 */
export function hasReference(value: string): boolean {
  return parsePieces(value).some((piece) => piece.type === "ref");
}

/** 字和引用混写:里面有引用,但不是整格一个引用(「> {{report.json.verdict}}」「{{a.text}}{{b.text}}」)。 */
export function isMixedTemplate(value: string): boolean {
  return hasReference(value) && wholeRef(value) === null;
}

/** 片段 → 字符串。和 parsePieces 严格互逆。 */
export function piecesToString(pieces: Piece[]): string {
  return pieces.map((piece) => (piece.type === "ref" ? `{{${piece.ref}}}` : piece.text)).join("");
}

/** 片段 → TipTap 文档(单段落;这些字段本来就是一段文本,不需要多段落)。 */
export function piecesToDoc(pieces: Piece[]): Record<string, unknown> {
  const content = pieces
    .filter((piece) => (piece.type === "ref" ? piece.ref : piece.text) !== "")
    .map((piece) =>
      piece.type === "ref"
        ? { type: "ref", attrs: { ref: piece.ref } }
        : { type: "text", text: piece.text },
    );
  return { type: "doc", content: [{ type: "paragraph", ...(content.length ? { content } : {}) }] };
}

/**
 * TipTap 文档 → 字符串。
 *
 * 多个段落用换行接起来 —— 用户在里面按了回车就该留下换行,而不是被悄悄拼成一行。
 */
export function docToString(doc: unknown): string {
  const root = doc as { content?: Array<{ type?: string; content?: unknown[] }> } | null;
  if (!root?.content) return "";
  return root.content
    .map((block) =>
      ((block.content ?? []) as Array<{ type?: string; text?: string; attrs?: { ref?: string } }>)
        .map((node) => (node.type === "ref" ? `{{${node.attrs?.ref ?? ""}}}` : (node.text ?? "")))
        .join(""),
    )
    .join("\n");
}


//: 唤起变量菜单的字符。
//:
//: **是 `@` 不是 `/`。** 斜杠在这些框里是会被正常打出来的内容 —— 路径 `a/b`、日期
//: `2026/08/28`、比例 `16/9` 都带它,打着打着就弹出菜单挡住视线。`@` 在"点名某个东西"上是
//: 通行手势,而这里点的正是上游那个节点。
export const TRIGGER = "@";

/**
 * 按输入筛上游引用。
 *
 * 匹配的是**去掉花括号之后**的名字(`llm-1.text`),因为用户敲的是 `@llm` 而不是 `@{{llm`;给了 `labelOf`
 * 的话,屏幕上那个名字(「写标题 · 文本」)也算 —— 菜单里摆的是它,照着敲就该找得到。
 * 大小写不敏感;查询为空时全给 —— 刚敲下 `@` 就该看见所有候选,而不是一片空白。
 */
export function filterRefs(variables: readonly string[], query: string, labelOf?: (ref: string) => string): string[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...variables];
  return variables.filter(
    (ref) => ref.replace(/[{}]/g, "").toLowerCase().includes(needle) || Boolean(labelOf?.(ref).toLowerCase().includes(needle)),
  );
}
