/**
 * 内嵌 ComfyUI 的语言跟随 Mosael(维护者:「ComfyUI 工作台让内嵌视图跟随 Mosael 的语言」)。
 *
 * 语言是 ComfyUI 前端**自己的设置** `Comfy.Locale`(值 `en` / `zh` / `zh-TW` / …,和它在「设置」里那个语言下拉是同一个
 * 键),存在 **ComfyUI 服务器上、按 ComfyUI 的用户存**;前端每次载入时整份读回来(`GET /api/settings`,它 settingStore
 * 起来那一步)。所以两头各做一件事,合起来才是「跟着 Mosael 走」:
 *
 * - **页面还没载入**(打开工作台之前):走它的正规口子 `POST <来源>/api/settings/Comfy.Locale`(body 是一个 JSON 串,
 *   如 `"zh"`)把服务器上那个值设成 Mosael 的语言 —— 页面载入时读到的就是它,**一打开就是对的**,不会先闪一下旧语言;
 * - **这个视图的页面已经开着**(收起工作台只是把视图从窗口摘掉,页面还在跑,见 accountViews.hide):**不重新载入**
 *   (ComfyUI 前端很重),走前端自己那条路 —— 页面里的 `app.extensionManager.setting.set("Comfy.Locale", …)`,和用户
 *   在 ComfyUI 设置里换语言是同一下:当场换过来(本机 8120、前端 1.43.18 实测),前端随后自己写回服务器,于是下一次
 *   载入也已经是这个语言。
 *
 * 两个请求都走**这个视图分区的会话**(`session.fromPartition(…).fetch`):带着它的 Cookie 与代理,和页面自己发的
 * 一样 —— ComfyUI 按用户存设置(`--multi-user`)时认的正是这个用户。后端 / 渲染层直接发不行:它的来源闸只放行同源
 * 页面的写请求,别处来的 POST 回 403(本机 8120 实测)。
 *
 * 语言只有一处映射(comfyLocaleOf,和主进程 i18n 的 normalizeLocale 同一条规矩:只看主语言标签)。**认不出的语言什么
 * 都不设** —— 不拿 `en` 顶替。
 */
import { session } from "electron";

import { runInComfyPage } from "./comfyViews";
import { plog } from "./log";

/** 前端的设置键:界面语言。 */
export const COMFY_LOCALE_SETTING = "Comfy.Locale";

/** ComfyUI 那边认的语言里,Mosael 会用的这两个。 */
export type ComfyLocale = "zh" | "en";

/** 设的结果:设好了 / 这版前端没有这个设置 / 视图停在别处 / 前端还没就绪 / 服务器那边没成。 */
export type ComfyLocaleOutcome = "applied" | "unsupported" | "elsewhere" | "notReady" | "failed";

/** 载入之前那一次写等多久:ComfyUI 一般在本机 / 局域网,慢到这份上就是它没在 —— 不该拖着工作台不开。 */
const WRITE_TIMEOUT_MS = 2_000;

/**
 * Mosael 的语言 → `Comfy.Locale` 的值。**只此一处**:`zh-CN` / `en-US`(`zh_CN` 这种写法也一样,和主进程
 * i18n 的 normalizeLocale 同一条规矩:取主语言标签、小写)换成 ComfyUI 认的 `zh` / `en`;认不出的回 `null`,
 * 调用方什么都不设。
 */
export function comfyLocaleOf(locale: unknown): ComfyLocale | null {
  const primary = String(locale ?? "").trim().toLowerCase().split(/[-_]/)[0];
  return primary === "zh" || primary === "en" ? primary : null;
}

/**
 * 这个视图来源下 ComfyUI 的设置那一条路。挂在子路径下(`http://host/comfy/`)时也接得上 —— 按目录拼;
 * 键名照前端自己那样转义(它发的也是 `/settings/<键>`)。
 */
export function comfySettingsUrl(url: string): string {
  const base = new URL(url);
  base.hash = "";
  base.search = "";
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  return new URL(`api/settings/${encodeURIComponent(COMFY_LOCALE_SETTING)}`, base).toString();
}

/**
 * 在页面里把语言换成 Mosael 的脚本。变量只有来源和值,都经 JSON 编码嵌进去。先探测:设置仓库在、这个键登记过、
 * 可选值里有要的这个,才设;已经是它了就不动(前端写回服务器那一下被主进程拦了、或服务器不认,fetch 报错 ——
 * 本地的值已经换好了,吞掉这个错)。和操控方式那段脚本(comfyNavigation.navigationScript)同一种写法。
 */
export function comfyLocaleScript(origin: string, locale: ComfyLocale): string {
  const key = JSON.stringify(COMFY_LOCALE_SETTING);
  const value = JSON.stringify(locale);
  return `(async () => {
  if (location.origin !== ${JSON.stringify(origin)}) return "elsewhere";
  const setting = window.app && window.app.extensionManager && window.app.extensionManager.setting;
  if (!setting || typeof setting.get !== "function" || typeof setting.set !== "function") return "unsupported";
  const definition = setting.settings ? setting.settings[${key}] : null;
  const options = definition && Array.isArray(definition.options) ? definition.options : [];
  const values = options.map((one) => (one && typeof one === "object" ? one.value : one));
  if (!values.includes(${value})) return "unsupported";
  if (setting.get(${key}) !== ${value}) {
    try {
      await setting.set(${key}, ${value});
    } catch (error) {
      // 写回服务器没成:本地的值已经换好了
    }
  }
  return setting.get(${key}) === ${value} ? "applied" : "unsupported";
})()`;
}

/**
 * 载入之前:把这个视图那台 ComfyUI 的语言设成 Mosael 的(页面还没载入才好使 —— 这一页载入时读的就是它)。
 * 请求发不出去、服务器不收都只落日志,不抛:语言跟不跟得上不该挡着工作台开。
 */
export async function setComfyLocaleOnServer(opts: { partition: string; url: string; locale: string }): Promise<ComfyLocaleOutcome> {
  const locale = comfyLocaleOf(opts.locale);
  if (!locale) return "unsupported";
  const endpoint = comfySettingsUrl(opts.url);
  try {
    const response = await session.fromPartition(opts.partition).fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(locale),
      signal: AbortSignal.timeout(WRITE_TIMEOUT_MS),
    });
    if (!response.ok) {
      plog("comfy locale: ComfyUI refused the settings write", response.status, endpoint);
      return "failed";
    }
    return "applied";
  } catch (error) {
    plog("comfy locale: settings write failed", endpoint, String(error));
    return "failed";
  }
}

/**
 * 这个视图**已经开着的那一页**:当场把语言换成 Mosael 的,不重新载入(前端就绪了才跑,载入中也等得起 ——
 * 那时换的正是新载入的那一页)。认不出的语言什么都不做。
 */
export function matchComfyLocaleInPage(opts: { partition: string; locale: string }): Promise<ComfyLocaleOutcome> {
  const locale = comfyLocaleOf(opts.locale);
  if (!locale) return Promise.resolve("unsupported");
  return runInComfyPage<ComfyLocaleOutcome>(opts.partition, (origin) => comfyLocaleScript(origin, locale));
}
