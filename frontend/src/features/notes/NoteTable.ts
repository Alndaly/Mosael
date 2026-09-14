import { Table } from "@tiptap/extension-table";

/**
 * 表格单元格里的竖线要转义,否则**那一格会被读成两格**,整张表当场变形 —— 而且两遍不收敛:
 * 一遍之后 `x \| y` 成了 `x | y`,再存一次它就真的裂成两列。笔记里写技术文档时竖线是常客
 * (正则的或、shell 管道、讲 Markdown 表格本身)。
 *
 * 和围栏代码块那条(见 NoteCodeBlock)是同一类错:分隔符必须避开正文,不能是常量。
 *
 * 上游那段排版(列宽、对齐、表头分隔行)没必要抄一遍 —— 它取每一格的文本只走
 * `renderChildren` 这一个口子,把那个口子包一层就够了。
 */
export const NoteTable = Table.extend({
  renderMarkdown(node, helpers, context) {
    return Table.config.renderMarkdown?.(node, {
      ...helpers,
      renderChildren: (nodes, separator) =>
        helpers.renderChildren(nodes, separator).replace(/\\?\|/g, "\\|"),
    }, context) ?? "";
  },
});
