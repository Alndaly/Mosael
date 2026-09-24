import React from "react";

/**
 * 「打开某一条记录」的请求,**放进信箱**,而不是按时间猜对方什么时候准备好。
 *
 * 目标页面什么时候挂载、它的列表什么时候加载完,发请求的一方不知道。此前的做法是按 80 / 300 /
 * 800ms 连发三次,赌其中一次赶上 —— 慢一点的机器上三次都赶不上,请求就丢了;而页面早就卸掉之后
 * 那几个定时器还会照样触发(CI 上就是这么红的:测试结束、jsdom 拆掉,800ms 那一发撞上一个
 * 不存在的 window)。
 *
 * 现在:请求留在信箱里,并立即广播一次。已经挂着的页面当场收;还没挂载的,挂载时自己来取;
 * 接不住(列表还没加载出那一条)就先留着,等它说准备好了再投。收下就从信箱里拿走,不会重复打开。
 */
const mailbox = new Map<string, string>();

export function emitOpenEvent(event: string, id: string): void {
  mailbox.set(event, id);
  window.dispatchEvent(new CustomEvent(event, { detail: id }));
}

/**
 * 收 `mosael:open-*` 的那一侧。`onOpen` 返回 `false` 表示"现在还接不住"(比如那一条还没加载出来),
 * 请求就留在信箱里;`deps` 一变(列表到货了)再投一次。
 */
export function useOpenRequest(event: string, onOpen: (id: string) => boolean | void, deps: React.DependencyList = []): void {
  const handler = React.useRef(onOpen);
  handler.current = onOpen;
  const deliver = React.useCallback(
    (id: string) => {
      if (handler.current(id) === false) return;
      if (mailbox.get(event) === id) mailbox.delete(event);
    },
    [event],
  );
  // 挂载时、以及接收方说"准备好了"(deps 变了)时,取一次信箱。
  React.useEffect(() => {
    const waiting = mailbox.get(event);
    if (waiting) deliver(waiting);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deliver, event, ...deps]);
  React.useEffect(() => {
    const onEvent = (e: Event) => {
      const id = (e as CustomEvent<unknown>).detail;
      if (typeof id === "string" && id) deliver(id);
    };
    window.addEventListener(event, onEvent);
    return () => window.removeEventListener(event, onEvent);
  }, [deliver, event]);
}

/** 深链通道:跳到业务页,并在页面挂载后用 mosael:open-* 事件打开指定记录。 */
export function gotoRecord(route: string, event?: string, id?: unknown): void {
  window.location.hash = route.replace(/^#/, "");
  if (event && typeof id === "string" && id) emitOpenEvent(event, id);
}

/**
 * 「进入某个页面的**起点**」—— 列表页,而不是它上次停在的那条详情。
 *
 * 侧栏点进一个页面,页面会恢复上次的样子(工作流详情、素材库的筛选都是有意记住的,用户要过)。
 * 但从一个**数字**点过去不是那个意思:统计页上「工作流 12」点进去,要看的是那 12 个工作流,
 * 而不是半小时前开着的某一个 —— 此前它就是这么落进某条工作流详情里的。
 *
 * 所以这是另一种导航,不是 `gotoRecord` 少传一个 id:起点长什么样只有页面自己知道(清掉选中、
 * 清掉筛选),导航层只负责把"从起点进来"这句话送到。`entry` 默认 `"root"`;页面若认得别的
 * 入口(发布页的 `"succeeded"` 这类筛选),就按它来,不认得的一律当起点。
 * 送信走信箱(见上面的 `emitOpenEvent`):目标页此刻多半还没挂载,挂载时自己来取。
 */
const SECTION_ROOT = "root";
const sectionEvent = (view: string) => `mosael:open-section:${view}`;

export function gotoSection(view: string, entry: string = SECTION_ROOT): void {
  gotoRecord(`/${view}`, sectionEvent(view), entry);
}

/**
 * 页面这一侧:收「从起点进来」的请求。返回**此刻还在信箱里等着的**入口 —— 渲染期只读、不取走,
 * 让页面第一帧就能按起点画:工作流页若先按记住的那条渲染一帧详情再跳回列表,人会看到一闪,
 * 整张画布也白挂载一次。真正的处理(清选中、改筛选)在 `onEnter` 里,由 effect 投递。
 */
export function useSectionEntry(view: string, onEnter: (entry: string) => void): string | null {
  const event = sectionEvent(view);
  useOpenRequest(event, onEnter);
  return mailbox.get(event) ?? null;
}

/** 通知类型 → 打开单条记录的事件名 + payload 里的记录 id 字段。 */
export const NOTIFICATION_DEEP_LINKS: Record<string, { event: string; payloadKey: string }> = {
  publish: { event: "mosael:open-publish-task", payloadKey: "task_id" },
  workflow: { event: "mosael:open-workflow", payloadKey: "workflow_id" },
};

/** 打开任务中心,并翻到某一条任务的执行详情。
 *
 * 不换页:任务中心是个覆盖层,而"跟进这条任务"多半发生在你正干着别的事的时候 ——
 * 把人从当前页面赶走去看一眼进度,回来还得自己找回原处。
 */
export function gotoJob(jobId: string): void {
  window.dispatchEvent(new CustomEvent("mosael:open-tasks", { detail: jobId }));
}

/** 跳到设置的某个分区(如未配置模型 → 直达「模型服务」)。SettingsView 监听 mosael:open-settings。 */
export function gotoSettings(section: string): void {
  gotoRecord("/settings", "mosael:open-settings", section);
}

/** 打开插件市场并找到某个插件(官网「在 Mosael 中打开」)。已经装了就直接选中它。 */
export const OPEN_PLUGIN_IN_MARKET = "mosael:open-plugin-market";
/** 打开工作流社区并选中某个官方模板(官网「在 Mosael 中打开」)。 */
export const OPEN_WORKFLOW_TEMPLATE = "mosael:open-workflow-template";

/** 页面 → 打开单条记录的事件名(mosael:// 深链、任务中心「前往」共用)。没有对应事件的页面就只跳页。 */
export const VIEW_RECORD_EVENTS: Record<string, string> = {
  workflows: "mosael:open-workflow",
  publish: "mosael:open-publish-task",
  settings: "mosael:open-settings",
};

/**
 * 挂上 mosael:// 深链与「拖到应用图标上的文件」的监听。桌面端 preload 把主进程的
 * IPC 转成同名 window 事件,这里是渲染层这一侧的落点。
 *
 * 深链只导航:主进程那边已经把 view 限死在白名单里、id 限死了字符集(见
 * electron/system/deepLink.ts 头部关于「为什么只导航不执行」的说明),这里不再放宽。
 */
export function listenDesktopDeepLinks(onFiles: (paths: string[]) => void): () => void {
  const onLink = (event: Event) => {
    const link = (event as CustomEvent<{ view?: string; id?: string; market?: string; template?: string }>).detail;
    if (!link?.view) return;
    //: 官网社区页的「在 Mosael 中打开」:没装的插件、没添加的模板在本机没有记录 id,
    //: 要的是「打开市场 / 社区,找到它」—— 装、添加仍由人点(只导航,见 electron/system/deepLink)。
    if (link.market) return gotoRecord("/plugins", OPEN_PLUGIN_IN_MARKET, link.market);
    if (link.template) return gotoRecord("/workflows", OPEN_WORKFLOW_TEMPLATE, link.template);
    gotoRecord(`/${link.view}`, VIEW_RECORD_EVENTS[link.view], link.id);
  };
  const onOpenFiles = (event: Event) => {
    const paths = (event as CustomEvent<string[]>).detail;
    if (Array.isArray(paths) && paths.length) onFiles(paths);
  };
  window.addEventListener("mosael:deep-link", onLink);
  window.addEventListener("mosael:open-files", onOpenFiles);
  return () => {
    window.removeEventListener("mosael:deep-link", onLink);
    window.removeEventListener("mosael:open-files", onOpenFiles);
  };
}

/** 官网文档的一页。
 *
 * 站点按语言分段(`/zh/docs/...`、`/en/docs/...`),而应用里的语言偏好是 zh-CN / en-US
 * —— 取前缀就够,别处再各拼一次的话,改站点结构时要满仓库找。
 */
export function docsUrl(path: string, locale: string): string {
  const lang = locale.startsWith("zh") ? "zh" : "en";
  return `https://mosael.com/${lang}/docs/${path.replace(/^\/+/, "")}`;
}
