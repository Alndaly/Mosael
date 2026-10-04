/**
 * 「存成笔记」里不碰 Electron 的那一半:读页面的那段脚本和它的上限。
 */

// 注进页面的脚本是**只读**的:不改 DOM、不触发事件、不发请求,交回可结构化克隆的普通对象。
// 以字符串形式交给 executeJavaScript,所以脚本里不能引用外部变量。

/** 正文 HTML 最多交多大:整页 DOM 能有十几 MB(内联的 SVG、JSON 数据),正文提取不需要那些。 */
export const MAX_PAGE_HTML = 4_000_000;
/** 选中文字最多交多少字。 */
export const MAX_SELECTION_CHARS = 200_000;

/**
 * 读页面:渲染后的 DOM(含登录后才看得到的内容),或者当前选中的文字。
 *
 * 给的是**渲染后的** HTML 而不是去后端重新抓一遍:很多页面不登录看不到正文,而登录态只在这个
 * 浏览器档案里。正文怎么挑、怎么转 Markdown 由后端做(和文档解析同一套转换,见 backend documents/web_page)。
 * 脚本和样式先剥掉 —— 它们往往占了 DOM 的大半,却一个字都不是正文。
 */
export const READ_PAGE_SCRIPT = `((mode, maxHtml, maxText) => {
  if (mode === "selection") {
    const text = String(window.getSelection ? window.getSelection() : "").trim();
    return { selection: text.slice(0, maxText), html: "" };
  }
  const clone = document.documentElement.cloneNode(true);
  for (const node of clone.querySelectorAll("script, style, noscript, template, iframe, svg, canvas, link[rel=stylesheet]")) node.remove();
  return { selection: "", html: clone.outerHTML.slice(0, maxHtml) };
})`;
