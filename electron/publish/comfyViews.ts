/**
 * ComfyUI 连接的内嵌视图(分区 `persist:pool-comfyui-<连接 id>`)在主进程这一侧要记住的事:
 *
 * - **打开它用的地址**:之后注入的脚本都按这个来源核对(视图停在别的站点就什么都不做);
 * - **操控方式**(见 comfyNavigation):渲染层按连接记着「触控板 / 鼠标」,告诉这里;这里在页面就绪后设好,**每次载入 / 刷新之后
 *   再设一次**;
 * - **设置写回的闸**:只装在这个分区的会话上,拦下操控方式那几个键写回 ComfyUI 服务器(别的分区、别的键都不碰);
 * - **载入之后**还要做的事(工作台的桥):登记一个回调,每次这个视图的页面载入完都跑一遍。
 */
import { session, type Session, type WebContents } from "electron";

import { sharedViews } from "./accountViews";
import { comfyReady } from "./comfyEditor";
import {
  navigationScript,
  settingsWriteVerdict,
  type ComfyNavigation,
  type NavigationOutcome,
} from "./comfyNavigation";

//: 前端起来要多久(和 comfyEditor 同一个数):第一次打开要下整套前端
const READY_TIMEOUT_MS = 60_000;
const SCRIPT_TIMEOUT_MS = 15_000;

const origins = new Map<string, string>();
const modes = new Map<string, ComfyNavigation>();
const guarded = new Set<string>();
const hooked = new WeakSet<WebContents>();
const onLoaded = new Map<string, Set<(partition: string) => void>>();

/** 打开 / 回到这个视图之前调一次:记下来源、装上设置写回的闸。要在页面载入之前,闸才拦得住第一次写回。 */
export function comfyViewOpening(partition: string, url: string): void {
  origins.set(partition, new URL(url).origin);
  guardSettings(session.fromPartition(partition), partition);
}

/** 视图建好、亮出来之后调一次:给当前那一页挂上「载入完」的监听(同一页只挂一次)。 */
export function comfyViewShown(partition: string): void {
  const contents = sharedViews()?.currentContents(partition);
  if (!contents || hooked.has(contents)) return;
  hooked.add(contents);
  contents.on("did-finish-load", () => {
    if (modes.has(partition)) void applyNavigation(partition).catch(() => undefined);
    for (const callback of onLoaded.get(partition) ?? []) callback(partition);
  });
}

/** 每次这个视图的页面载入完都调 `callback`(工作台据此重新注入桥)。返回取消。 */
export function onComfyLoaded(partition: string, callback: (partition: string) => void): () => void {
  const set = onLoaded.get(partition) ?? new Set();
  set.add(callback);
  onLoaded.set(partition, set);
  return () => set.delete(callback);
}

/** 这个视图打开时用的来源(没打开过是 null)。 */
export function comfyOrigin(partition: string): string | null {
  return origins.get(partition) ?? null;
}

/**
 * 设操控方式:记下来(以后每次载入都按它),页面就绪后设好。视图还没经工作流库打开过(不知道来源)、或者前端一直没就绪,
 * 回 notReady —— 下次载入时照样会设。
 */
export async function setComfyNavigation(partition: string, mode: ComfyNavigation): Promise<NavigationOutcome> {
  modes.set(partition, mode);
  comfyViewShown(partition);
  return applyNavigation(partition);
}

async function applyNavigation(partition: string): Promise<NavigationOutcome> {
  const origin = origins.get(partition);
  const mode = modes.get(partition);
  const driver = sharedViews()?.existingDriver(partition);
  if (!origin || !mode || !driver) return "notReady";
  if (!(await driver.waitForFunction(comfyReady(origin), READY_TIMEOUT_MS))) return "notReady";
  return driver.evaluate<NavigationOutcome>(navigationScript(origin, mode), SCRIPT_TIMEOUT_MS);
}

/**
 * 只在这个分区的会话上装:操控方式那几个键写回 ComfyUI 服务器的请求拦下(见 comfyNavigation.settingsWriteVerdict);
 * 批量写回里混着别的键时,拦下整批、把剩下的键原样补发一次(带着这个会话的 Cookie,和页面自己发的一样)。
 * 一个会话的 onBeforeRequest 只能挂一个(后挂的覆盖先挂的),这个分区上只有这里挂。
 */
export function guardSettings(target: Pick<Session, "webRequest" | "fetch">, partition: string): void {
  if (guarded.has(partition)) return;
  guarded.add(partition);
  target.webRequest.onBeforeRequest({ urls: ["*://*/*api/settings*"] }, (details, callback) => {
    const body = (details.uploadData ?? [])
      .map((part) => (part.bytes ? Buffer.from(part.bytes).toString("utf8") : ""))
      .join("");
    const verdict = settingsWriteVerdict({ method: details.method, url: details.url, body });
    if (verdict.action === "allow") {
      callback({});
      return;
    }
    callback({ cancel: true });
    if (verdict.action === "reissue") {
      void target
        .fetch(details.url, { method: details.method, body: verdict.body, headers: { "Content-Type": "application/json" } })
        .catch(() => undefined);
    }
  });
}

/** 测试用:清掉记住的一切。 */
export function resetComfyViews(): void {
  origins.clear();
  modes.clear();
  guarded.clear();
  onLoaded.clear();
}
