import type { MessageKey } from "@/app/messages";
import type { Locale } from "@/app/preferencesContext";

/**
 * 运行时的文案表:**只取当前那种语言**。
 *
 * 此前 preferences 在运行时 `import { messages }`,两种语言五千多条、源码五百多 KB 一起进了首屏要先解析完的那一块
 * (`index.html` 里 modulepreload 的那个),而每个人只用得到其中一种。现在每种语言一块,按需取:启动时 `main.tsx`
 * 和外壳一起并行取存着的那一种,切语言时先取到再切。
 *
 * `app/messages.ts` 仍然把两种语言拼在一起 —— 它给类型(`MessageKey`)和测试用;运行时的代码不许再引它
 * (app/pageChunks.test.ts 盯着首屏闭包里没有文案正文)。
 */
export type MessageTable = Readonly<Record<MessageKey, string>>;

const LOADERS: Record<Locale, () => Promise<MessageTable>> = {
  "zh-CN": () => import("@/app/messages/zh-CN").then((module) => module.zhCN),
  "en-US": () => import("@/app/messages/en-US").then((module) => module.enUS),
};

const loaded = new Map<Locale, MessageTable>();
const pending = new Map<Locale, Promise<MessageTable>>();

/** 取一种语言的表(取过的直接给)。失败时不留着那次失败:下一次再取会重新去取。 */
export function loadMessages(locale: Locale): Promise<MessageTable> {
  const ready = loaded.get(locale);
  if (ready) return Promise.resolve(ready);
  const inFlight = pending.get(locale);
  if (inFlight) return inFlight;
  const request = LOADERS[locale]()
    .then((table) => {
      loaded.set(locale, table);
      return table;
    })
    .finally(() => pending.delete(locale));
  pending.set(locale, request);
  return request;
}

/** 这种语言的表取到了没有(取到了就能同步切过去,不必等一拍)。 */
export function messagesLoaded(locale: Locale): boolean {
  return loaded.has(locale);
}

/**
 * 同步取一种语言的表。还没取到时退到已经取到的那一种(切语言的那一拍、或者存着的语言恰好没取成),一种都没有就直说 ——
 * 那是启动顺序错了(`main.tsx` 要先 `loadMessages` 再渲染),不该悄悄显示键名。
 */
export function messagesFor(locale: Locale): MessageTable {
  const table = loaded.get(locale) ?? loaded.values().next().value;
  if (!table) throw new Error(`Mosael: the "${locale}" message table was used before it was loaded (see app/messageTables).`);
  return table;
}
