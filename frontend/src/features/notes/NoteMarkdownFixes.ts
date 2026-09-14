import { Table } from "@tiptap/extension-table";
import type { JSONContent } from "@tiptap/react";

// 这两个类型上游没有单独导出,从配置上取更稳:换了版本它跟着变,不用手抄一份。
type RenderMarkdown = NonNullable<(typeof Table)["config"]["renderMarkdown"]>;
type Helpers = Parameters<RenderMarkdown>[1];
type Ctx = Parameters<RenderMarkdown>[2];

const renderTable = (Table as unknown as {
  config: { renderMarkdown?: RenderMarkdown };
}).config.renderMarkdown;

/**
 * 表格单元格里的竖线要转义,否则**那一格会被读成两格**,整张表当场变形 —— 而且两遍不收敛:
 * 一遍之后 `x \| y` 变成 `x | y`,再存一次它就真的成了两列。笔记里写技术文档时竖线是常客
 * (正则的或、shell 管道、讲 Markdown 表格本身)。
 *
 * 和围栏代码块那条(见 NoteCodeBlock)是同一类错:分隔符必须避开正文,不能是常量。
 *
 * 上游的排版逻辑(列宽、对齐、表头分隔行)没必要抄一遍 —— 它取每一格的文本只走
 * `h.renderChildren` 这一个口子,把那个口子包一层就够了。
 */
export const NoteTable = Table.extend({
  renderMarkdown(node: JSONContent, h: Helpers, ctx: Ctx) {
    if (!renderTable) return "";
    const escaped: Helpers = {
      ...h,
      renderChildren: (nodes: Parameters<Helpers["renderChildren"]>[0], separator?: string) =>
        h.renderChildren(nodes, separator).replace(/\\?\|/g, "\\|"),
    };
    return renderTable(node, escaped, ctx);
  },
});
