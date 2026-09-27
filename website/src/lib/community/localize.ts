/**
 * 社区服务回来的**双语字段**换成这一页的语言。
 *
 * 官方条目(从仓库里的静态索引迁进去的那一批)的标题、简介、准备项、步骤存的是 `{zh, en}`,和插件索引
 * `registry.json` 同一个约定 —— 桌面应用读的也是这一份,所以服务端不替我们挑。用户提交的条目是普通字符串。
 * 此前页面把 `{zh, en}` 直接当成字符串渲染,整页崩在「Objects are not valid as a React child」。
 *
 * 规则只有一条:**键恰好是 zh / en 的子集、且至少有一个**的对象,换成这一页语言的那一段(没有就用另一段)。
 * 在读数据的入口统一做一次(serverGet、列表翻页、communityFetch),组件拿到的永远是字符串。
 */
const LANG_KEYS = new Set(["zh", "en"]);

function isLocalized(value: object): value is { zh?: unknown; en?: unknown } {
  const keys = Object.keys(value);
  return keys.length > 0 && keys.every((key) => LANG_KEYS.has(key));
}

/** `language` 可以是路由段(`zh`)或 BCP 47(`zh-CN`、`en-US`);认前缀。 */
export function localizeTree<T>(value: T, language: string): T {
  const primary = language.toLowerCase().startsWith("zh") ? "zh" : "en";
  const fallback = primary === "zh" ? "en" : "zh";
  const walk = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(walk);
    if (node && typeof node === "object") {
      if (isLocalized(node)) {
        const record = node as Record<string, unknown>;
        return walk(record[primary] ?? record[fallback]);
      }
      return Object.fromEntries(Object.entries(node).map(([key, child]) => [key, walk(child)]));
    }
    return node;
  };
  return walk(value) as T;
}
