/**
 * mosael:// 深链的解析。
 *
 * ## 为什么只导航、不执行
 *
 * 自定义协议是一个**外部输入面**:任何网页只要 `location = "mosael://…"` 就能触发它,
 * 不需要用户点击确认,也不需要任何权限。所以这里刻意只支持「打开某个页面」,不支持
 * 「运行某个工作流 / 发布某条内容」——后者意味着用户随便访问一个网站,那个网站就能静默
 * 驱动他的自动化:工作流带着登录态、发布权限和模型额度,这是实打实的越权。
 *
 * 导航是安全的:最坏情况是应用被弹到前台、停在某个页面上,没有副作用。
 * 将来要做「链接触发执行」,正确形态是链接只能**发起一个待确认的请求**,由应用内弹确认卡、
 * 用户明确同意后才执行 —— 而不是把执行入口直接暴露在协议上。
 *
 * ## 形状
 *   mosael://open?view=workflows&id=<记录 id>
 * view 必须在白名单里(和前端 StudioView 一一对应);id 可选,用于打开具体记录。
 */

/** 与前端 StudioView 一致。白名单而非透传:避免把任意字符串塞进 location.hash。 */
const ALLOWED_VIEWS = new Set([
  "home",
  "media",
  "editor",
  "ai",
  "publish",
  "kb",
  "settings",
  "workflows",
  "scheduler",
  "plugins",
  "browser-pool",
]);

/** 记录 id 是后端生成的十六进制串;限死字符集,免得经由 hash 注入奇怪的东西。 */
const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export const PROTOCOL = "mosael";
const LEGACY_PROTOCOL = "openstudio";

export interface DeepLink {
  view: string;
  id?: string;
}

/** 解析失败一律返回 null(不抛):输入来自外部,不可信也不该让主进程崩。 */
export function parseDeepLink(raw: string): DeepLink | null {
  if (typeof raw !== "string" || !raw) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== `${PROTOCOL}:` && url.protocol !== `${LEGACY_PROTOCOL}:`) return null;
  // mosael://open?... —— host 是 "open",其余动作一律不认(见文件头:只导航)。
  if (url.hostname !== "open") return null;

  const view = url.searchParams.get("view") || "";
  if (!ALLOWED_VIEWS.has(view)) return null;

  const id = url.searchParams.get("id");
  if (id && !ID_PATTERN.test(id)) return null;

  return id ? { view, id } : { view };
}

/** 从进程参数里挑出深链(Windows/Linux 上协议唤起是作为命令行参数传进来的)。 */
export function deepLinkFromArgv(argv: readonly string[]): DeepLink | null {
  for (const arg of argv) {
    if (typeof arg === "string" && (arg.startsWith(`${PROTOCOL}://`) || arg.startsWith(`${LEGACY_PROTOCOL}://`))) {
      const parsed = parseDeepLink(arg);
      if (parsed) return parsed;
    }
  }
  return null;
}
