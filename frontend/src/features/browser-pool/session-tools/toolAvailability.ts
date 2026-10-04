import type { MessageKey } from "@/app/messages";

export type PageTool = "shot" | "video" | "images" | "note" | "start";

/**
 * 顶栏的每样工具此刻能不能用;不能用时给人看的原因(文案键),能用是 null。
 *
 * - 前台还没打开网页(空白页、加载失败的错误页):都用不了 —— 没有可截、可读、可开工的页面;
 * - 上一个操作还在做:都等一等(同一时刻只做一件,做到哪了由顶栏那句状态说);
 * - 页面还在加载:读页面内容的几样(找视频、找图片、读正文)等它加载完 —— 现在读到的是半截页面;
 *   截屏(截下此刻看到的)和用当前页开工(只要网址)照常。
 */
export function toolAvailability(state: PublishViewState, busy: boolean): Record<PageTool, MessageKey | null> {
  const url = state.url ?? "";
  if (!/^https?:\/\//i.test(url)) return all("browserToolsNeedsPage");
  if (busy) return all("browserToolsBusy");
  const loading = state.loading ? "browserToolsStillLoading" : null;
  return { shot: null, video: loading, images: loading, note: loading, start: null };
}

function all(reason: MessageKey): Record<PageTool, MessageKey> {
  return { shot: reason, video: reason, images: reason, note: reason, start: reason };
}
