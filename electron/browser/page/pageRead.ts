/**
 * 存成笔记 —— 主进程这一半:读出渲染后的页面或选中的文字(正文怎么挑由后端做,见 backend documents/web_page)。
 */
import { foreground, pageOf } from "./pageTarget";
import { MAX_PAGE_HTML, MAX_SELECTION_CHARS, READ_PAGE_SCRIPT } from "./pageReadCore";
import type { PageInfo } from "./pageToolsCore";

/** 读页面:渲染后的 HTML(整页正文由后端挑)或选中的文字。 */
export async function readPage(mode: "article" | "selection"): Promise<{ page: PageInfo; html: string; selection: string }> {
  const { webContents: wc } = foreground();
  const page = pageOf(wc);
  const result = (await wc.mainFrame
    .executeJavaScript(`${READ_PAGE_SCRIPT}(${JSON.stringify(mode)}, ${MAX_PAGE_HTML}, ${MAX_SELECTION_CHARS})`)
    .catch(() => null)) as { html?: unknown; selection?: unknown } | null;
  return {
    page,
    html: typeof result?.html === "string" ? result.html : "",
    selection: typeof result?.selection === "string" ? result.selection : "",
  };
}
