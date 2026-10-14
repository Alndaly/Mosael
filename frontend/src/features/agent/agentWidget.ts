/**
 * 智能体给的小界面(`show_widget`)装进 iframe 之前的那份文档,以及 iframe 和这一页之间唯一的一条消息。
 *
 * ## 安全边界
 *
 * 这段 HTML 是**模型写的**,而模型读过的网页、文档、工具结果都可能往里塞东西(提示词注入)。所以它被当成
 * 不可信的第三方页面,关在四道墙里 —— 每一道防一件具体的事:
 *
 * 1. **不同源**:iframe 的 `sandbox` 只给 `allow-scripts`,**不给 `allow-same-origin`**,它的来源是不透明的
 *    (opaque origin)。碰不到这一页的 DOM、localStorage、cookie,也碰不到 preload 挂在主框架上的桥
 *    (preload 只在主框架跑)。脚本能跑,但跑在一个什么都不认识它的地方。
 * 2. **不能离开**:sandbox 里没有 `allow-top-navigation*`、`allow-popups`、`allow-forms`、`allow-modals` ——
 *    不能把整个应用导航走、不能开新窗口、不能提交表单、不能弹 alert 挡住界面。它**导航自己**这一条沙箱管不到,
 *    由桌面壳拦(electron/app-origin.cjs guardNavigation 的 will-frame-navigate:子框架只许停在 srcdoc);
 *    界面里的链接点击在 BOOTSTRAP 里就被吞掉了。
 * 3. **断网**:文档开头注入一条 CSP(WIDGET_CSP)。`connect-src 'none'` 断掉 fetch / XHR / WebSocket /
 *    sendBeacon;脚本、样式、字体、图片只许从下面几个 CDN 和地图瓦片源来。CSP 只能**收紧**不能放宽:
 *    模型在自己的 HTML 里再写一条 `<meta http-equiv=Content-Security-Policy>`,浏览器取两条的交集,
 *    而且它写在 body 里 —— meta CSP 只在 head 里生效。我们这条在 head 的第一个位置,早于任何一行模型的内容。
 * 4. **只说一件事**:iframe 往外只发一种消息 —— 它的内容有多高(HEIGHT_MESSAGE)。这一页只认**这个 iframe
 *    自己的 window** 发来的(event.source 比对),高度夹在上下限之间;别的消息一律不看。
 *
 * 剩下的口子写明白:放行的 CDN 上谁都能发包,一个恶意的包能在框里跑任意脚本 —— 但它出不了上面四道墙:
 * 没有网、没有同源、走不了。DNS 预解析之类不归 CSP 管的旁路泄露的只是"查了哪个域名"。
 *
 * ## 为什么不在框里放 `allow-same-origin`
 *
 * 地图库、图表库都不需要它。srcdoc 的 iframe 给了它就**和这一页同源**,第一道墙整个没了 —— 这个开关
 * 无论哪天谁想加,都要先推翻这一段。
 */

/** CDN:常见的地图 / 图表 / UI 库都在上面。只放这几家,不放「任意 https」。 */
export const WIDGET_SCRIPT_HOSTS = ["https://cdn.jsdelivr.net", "https://unpkg.com", "https://cdnjs.cloudflare.com"] as const;
/** 地图瓦片:OpenStreetMap 和 CARTO 的底图(Leaflet 的两种常用底图)。 */
export const WIDGET_TILE_HOSTS = ["https://*.tile.openstreetmap.org", "https://tile.openstreetmap.org", "https://*.basemaps.cartocdn.com"] as const;

const scripts = WIDGET_SCRIPT_HOSTS.join(" ");

export const WIDGET_CSP = [
  "default-src 'none'",
  `script-src 'unsafe-inline' ${scripts}`,
  `style-src 'unsafe-inline' ${scripts} https://fonts.googleapis.com`,
  `img-src data: blob: ${scripts} ${WIDGET_TILE_HOSTS.join(" ")}`,
  `font-src data: ${scripts} https://fonts.gstatic.com`,
  "connect-src 'none'",
  "media-src 'none'",
  "object-src 'none'",
  "frame-src 'none'",
  "worker-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
].join("; ");

/** iframe 的 sandbox。**只有这一项**,理由见文件头第 1、2 条。 */
export const WIDGET_SANDBOX = "allow-scripts";

export const HEIGHT_MESSAGE = "mosael-widget-height";

/** 内嵌时的高度上下限。再高就该点「展开」看全屏,而不是在对话里撑出一整屏。 */
export const WIDGET_MIN_HEIGHT = 48;
export const WIDGET_MAX_HEIGHT = 560;
/** 第一条高度消息到之前先占的高度(一张小地图的样子),免得从 0 跳起来。 */
export const WIDGET_INITIAL_HEIGHT = 240;

/**
 * 框里的引导脚本:报高度、吞链接点击。写在 CSP 之后、模型的内容之前。
 *
 * 高度量的是 documentElement 的 scrollHeight:内容变高变矮(图表画完、面板展开)都会再报一次。
 * 用了 `height:100%` 的地图会报回框自己的高度 —— 稳定在初始那一档,不会越报越高。
 */
const BOOTSTRAP = `(function(){
  var last = -1;
  function report(){
    var h = Math.ceil(document.documentElement.scrollHeight);
    if (h === last) return;
    last = h;
    parent.postMessage({ type: "${HEIGHT_MESSAGE}", height: h }, "*");
  }
  new ResizeObserver(report).observe(document.documentElement);
  addEventListener("load", report);
  document.addEventListener("click", function(event){
    var link = event.target && event.target.closest && event.target.closest("a[href]");
    if (link && link.getAttribute("href").charAt(0) !== "#") event.preventDefault();
  }, true);
})();`;

/** 跟着应用主题的几个变量。框里拿不到这一页的样式表(不同源),所以把值抄进去。 */
export const WIDGET_THEME_VARS = ["--background", "--foreground", "--muted", "--muted-foreground", "--border", "--primary", "--card"] as const;
export type WidgetTheme = { scheme: "light" | "dark"; vars: Partial<Record<(typeof WIDGET_THEME_VARS)[number], string>> };

/** 颜色值只放颜色该有的字符 —— 它们来自我们自己的样式表,但它们会被拼进 <style>,多一道不花钱。 */
const SAFE_CSS_VALUE = /^[#\w\s(),.%/*+-]*$/;

function themeStyle(theme: WidgetTheme): string {
  const vars = Object.entries(theme.vars)
    .filter(([, value]) => typeof value === "string" && value.trim() !== "" && SAFE_CSS_VALUE.test(value))
    .map(([name, value]) => `${name}:${(value as string).trim()};`)
    .join("");
  return `:root{color-scheme:${theme.scheme === "dark" ? "dark" : "light"};${vars}}
html,body{margin:0;background:var(--card);color:var(--foreground);font:14px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",sans-serif}`;
}

/**
 * 交给 iframe `srcDoc` 的整份文档:我们的 head(CSP、主题、引导脚本)在前,模型的 HTML 原样放进 body。
 *
 * 模型给的是一整份文档(带 `<!doctype>`、`<html>`、`<head>`)也照样放进 body:解析器会忽略多出来的
 * html / head / body 标签,里面的 `<script>`、`<style>`、`<link>` 在 body 里照常生效 —— 唯独 meta CSP 不生效,
 * 这正是我们要的(见文件头第 3 条)。
 */
export function buildWidgetDocument(html: string, theme: WidgetTheme): string {
  return [
    "<!doctype html><html><head>",
    `<meta http-equiv="Content-Security-Policy" content="${WIDGET_CSP}">`,
    '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
    `<style>${themeStyle(theme)}</style>`,
    `<script>${BOOTSTRAP}</script>`,
    "</head><body>",
    html,
    "</body></html>",
  ].join("");
}

/** 这一页的主题 → 框里用的那几个变量。 */
export function currentWidgetTheme(root: HTMLElement = document.documentElement): WidgetTheme {
  const style = getComputedStyle(root);
  const vars: WidgetTheme["vars"] = {};
  for (const name of WIDGET_THEME_VARS) vars[name] = style.getPropertyValue(name).trim();
  return { scheme: root.classList.contains("dark") ? "dark" : "light", vars };
}

/**
 * 一条消息是不是**这个框**报的高度;是就给夹好的高度,不是就是 null。
 *
 * 只看 `source`,不看 `origin`:沙箱框的来源是不透明的(序列化成字符串 "null"),任何别的沙箱页面也是 "null",
 * 拿它判身份等于没判。窗口对象是唯一认得出"就是这一个框"的东西。
 */
export function widgetHeightFrom(event: Pick<MessageEvent, "source" | "data">, frame: Window | null | undefined): number | null {
  if (!frame || event.source !== frame) return null;
  const data = event.data as { type?: unknown; height?: unknown } | null;
  if (!data || data.type !== HEIGHT_MESSAGE || typeof data.height !== "number" || !Number.isFinite(data.height)) return null;
  return Math.min(WIDGET_MAX_HEIGHT, Math.max(WIDGET_MIN_HEIGHT, Math.round(data.height)));
}
