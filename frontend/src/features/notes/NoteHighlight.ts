import { Mark, markInputRule, markPasteRule, mergeAttributes } from "@tiptap/react";
import { Markdown } from "@tiptap/markdown";

/** 高亮这个标记的名字。切换用 `toggleMark(HIGHLIGHT)`:没高亮的加上,已高亮的取消。 */
export const HIGHLIGHT = "highlight";

/**
 * 笔记里的高亮。**存成 `==文字==`**(Obsidian / Typora 的写法),编辑、阅读、Markdown 三种模式之间来回不丢不变;
 * 智能体读到的、edit_note 改的、导出的都是这同一份字。
 *
 * 一种颜色:`==` 没有地方放颜色,要多色就得换存储格式(那是另一回事),一种颜色够用就不加这层复杂度。
 *
 * **字面的 `==` 要转义**:见下面的 NoteMarkdown。
 */
const INPUT = /(?:^|\s)(==(?!\s)((?:[^=]+))(?<!\s)==)$/;
const PASTE = /(?:^|\s)(==(?!\s)((?:[^=]+))(?<!\s)==)/g;
const TOKEN = /^==(?=\S)([^\n]*?\S)==(?!=)/;

export const NoteHighlight = Mark.create({
  name: HIGHLIGHT,

  parseHTML() {
    return [{ tag: "mark" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["mark", mergeAttributes({ class: "note-highlight" }, HTMLAttributes), 0];
  },

  //: 比粗体、斜体这些基本标记优先(默认 100):套在它们外面,`==…**粗**…==` 存回去还是一整段,不被切成好几截。
  priority: 101,

  markdownTokenizer: {
    name: "highlight",
    level: "inline",
    start: (src) => src.indexOf("=="),
    tokenize: (src, _tokens, lexer) => {
      const match = TOKEN.exec(src);
      if (!match) return undefined;
      return { type: "highlight", raw: match[0], text: match[1], tokens: lexer.inlineTokens(match[1]) };
    },
  },

  parseMarkdown: (token, helpers) => helpers.applyMark(HIGHLIGHT, helpers.parseInline(token.tokens || [])),

  renderMarkdown: (node, helpers) => `==${helpers.renderChildren(node)}==`,

  addKeyboardShortcuts() {
    return { "Mod-Shift-h": () => this.editor.commands.toggleMark(this.name) };
  },

  addInputRules() {
    return [markInputRule({ find: INPUT, type: this.type })];
  },

  addPasteRules() {
    return [markPasteRule({ find: PASTE, type: this.type })];
  },
});

/**
 * 笔记用的 Markdown 扩展:就是 @tiptap/markdown,只多一条 —— **正文里字面的 `==` 存的时候转义**。
 *
 * 序列化器只转义它认识的那几个记号(`*` `_` `~` …,库里的 escapeMarkdownSyntax),不认识 `=`。正文里本来就写着
 * `a==b==c` 的话,存回去再读会凭空变成高亮。所以连着两个以上的 `=` 逐个写成 `\=`(Markdown 的反斜杠转义,读回来
 * 就是字面的 `=`)。那个方法是库内部的,升级改了名这一条就不生效 —— noteHighlight.test 钉着,改名了会红。
 */
export const NoteMarkdown = Markdown.extend({
  onBeforeCreate(event) {
    this.parent?.(event);
    const manager = this.editor.markdown as unknown as { escapeMarkdownSyntax?: (text: string) => string } | undefined;
    const escape = manager?.escapeMarkdownSyntax?.bind(manager);
    if (!manager || !escape) return;
    manager.escapeMarkdownSyntax = (text: string) => escape(text).replace(/={2,}/g, (run) => run.replace(/=/g, "\\="));
  },
});
