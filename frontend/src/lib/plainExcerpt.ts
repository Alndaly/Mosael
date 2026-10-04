/**
 * 一段笔记 Markdown 开头的几个字,**给人看的那一版**:去掉 `**`、`#`、链接语法这些记号,空白压成一个空格。
 *
 * 选区小条(笔记页输入卡里)和气泡里那行摘录(对话里)共用 —— 两处说的是同一段字,长得应该一样。
 * 发给智能体、存进消息的仍是原文(带着记号,edit_note 才找得到)。
 */
export function plainExcerpt(markdown: string, length = 24): string {
  return markdown
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_~`>#]+|==/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, length);
}
