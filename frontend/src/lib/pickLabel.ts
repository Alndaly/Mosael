/**
 * 一条**名字**:要么是一句,要么是一张按语言分的表(`{"zh": "加载图像", "en": "LoadImage"}`)。
 *
 * **为什么挑语言在前端**:名字天生是多语言的一组事实,不是"后端挑好的一句话"。宿主在边界上把插件交回的那一对塌成
 * 一句,塌完另一种语言里的信息就没了 —— 界面显示「加载图像」时,画布上写着的 `Load Image` 在数据里根本不存在,
 * 搜索按显示的那一条比就搜不到(维护者:「节点名称明明是 Load Image,搜索这个却搜索不到」)。挑哪种语言要在这里做:
 * 前端知道 Mosael 的界面语言,而搜索要拿**表里全部语言**去比(见 labelValues)。
 *
 * 翻译只认官方那一条路(`custom_nodes/<包>/locales/<lang>/*.json` → 聚合进 `/i18n`),这里不碰第三方汉化的私有路由:
 * 插件把那一条路上的结果交回来,这里只负责挑。
 *
 * 读的那一头按 `unknown` 收:插件没给就是空串,远端数据不合规时还可能是别的。
 */

/** 语言标签的主语言:`zh-CN` / `zh_Hans` / `ZH` 都认成 `zh`(和后端 mosael_formats 的 `primary_tag` 同一套)。 */
function primaryLanguage(tag: string): string {
  return tag.trim().toLowerCase().split(/[-_]/)[0] ?? "";
}

/** 一条名字里**每一种语言**的写法:字符串就是它自己,表就是表里全部非空的值(按写在前面的先来)。搜索拿它当 haystack。 */
export function labelValues(value: unknown): string[] {
  if (typeof value === "string") return value ? [value] : [];
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.values(value as Record<string, unknown>).filter((one): one is string => typeof one === "string" && one !== "");
}

/**
 * 一条名字按界面语言挑一句:字符串原样;表的挑法是 **界面语言 → `en` → 表里任意一个 → 空串**。
 *
 * 退路给 `en` 是因为它是这一类数据的原文语言(ComfyUI 的 `object_info` 就是英文);再退一步给表里写在前面的那一条 ——
 * 有一种语言的写法总比空白强(后端 `pick_text` 的退路也是给原文,不是给空)。都没有就是空串,由调用方决定退回什么
 * (名字那一格一般退回键名)。
 */
export function pickLabel(value: unknown, locale: string): string {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const byLanguage = new Map<string, string>();
  for (const [language, one] of Object.entries(value as Record<string, unknown>)) {
    if (typeof one !== "string" || !one) continue;
    const key = primaryLanguage(language);
    if (key && !byLanguage.has(key)) byLanguage.set(key, one);
  }
  return byLanguage.get(primaryLanguage(locale)) ?? byLanguage.get("en") ?? byLanguage.values().next().value ?? "";
}
