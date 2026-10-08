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

/** 素材库那一侧收的「打开这一份」(见 MediaLibraryView)。 */
export const OPEN_ASSET_EVENT = "mosael:open-asset";

/** 去素材库,打开这一份的详情。 */
export function gotoAsset(assetId: string): void {
  gotoRecord("/media", OPEN_ASSET_EVENT, assetId);
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

/**
 * 一条通知点进去打开哪一条记录(事件名 + 信箱里的载荷)。认不出就只跳页。
 *
 * **工作流失败开的是失败的那一次运行**,不是工作流本身:此前只选中工作流、打开编辑器,失败原因和那次运行都看不到;
 * 工作流删了就落在空列表上,而任务和事件明明都还在(体检 UM-17)。工作流不在了由工作流页转给任务中心。
 */
export function notificationRecord(
  type: string,
  payload: Record<string, unknown> | null | undefined,
): { event: string; id: string } | null {
  const text = (key: string) => (typeof payload?.[key] === "string" ? (payload[key] as string) : "");
  if (type === "publish" && text("task_id")) return { event: "mosael:open-publish-task", id: text("task_id") };
  if (type === "workflow" && text("workflow_id")) {
    return text("job_id")
      ? { event: OPEN_WORKFLOW_RUN, id: workflowRunLink(text("workflow_id"), text("job_id")) }
      : { event: "mosael:open-workflow", id: text("workflow_id") };
  }
  return null;
}

/** 打开任务中心,并翻到某一条任务的执行详情。
 *
 * 不换页:任务中心是个覆盖层,而"跟进这条任务"多半发生在你正干着别的事的时候 ——
 * 把人从当前页面赶走去看一眼进度,回来还得自己找回原处。
 */
export function gotoJob(jobId: string): void {
  window.dispatchEvent(new CustomEvent("mosael:open-tasks", { detail: jobId }));
}

/**
 * 一篇笔记的地址,可以钉在某个修订上。笔记页从地址里读要打开哪篇(`#/notes?note=…`),所以它既是
 * 链接的 href,也是「现在开着哪篇」的状态 —— 刷新、返回都认它。
 */
export function noteHref(noteId: string, revision?: number | null): string {
  return `#/notes?note=${encodeURIComponent(noteId)}${revision ? `&revision=${revision}` : ""}`;
}

/** 「回到这篇笔记、把这一段定位出来」—— 对话气泡里那行选区摘录点进来时用。 */
export interface NotePassage {
  noteId: string;
  /** 那一段在笔记 Markdown 里的原文(带记号)。编辑器拿它找回那一段。 */
  text: string;
  /** 原文在 Markdown 里的起始下标;同一段字出现多次时挑最近的那处。-1 = 不知道。 */
  start: number;
}

/** 定位请求走信箱(见上面的 emitOpenEvent):笔记页此刻多半还没挂上、那篇也还没取到,编辑器好了自己来取。 */
export const NOTE_PASSAGE_EVENT = "mosael:locate-note-passage";

export function locateNotePassage(passage: NotePassage): void {
  gotoRecord(noteHref(passage.noteId), NOTE_PASSAGE_EVENT, JSON.stringify(passage));
}

/** 信箱里拿出来的那一份 → 定位请求;认不出来就是 null。 */
export function parseNotePassage(raw: string): NotePassage | null {
  try {
    const value = JSON.parse(raw) as Partial<NotePassage>;
    if (typeof value.noteId !== "string" || typeof value.text !== "string" || !value.text) return null;
    return { noteId: value.noteId, text: value.text, start: typeof value.start === "number" ? value.start : -1 };
  } catch {
    return null;
  }
}

/** 画板页收的「打开这一张」(见 BoardsView)。 */
export const OPEN_BOARD_EVENT = "mosael:open-board";

/**
 * 打开某一张画板。**一律走这里**,不要自己写 `location.hash = "#/boards?board=…"`:
 *
 * 只改 hash 只在画板页**还没挂载**时够用。人已经在画板页上时(开着画板 A,从右上角确认中心点「回到那里」去画板 B、
 * 智能体说「带你去看看那张板」),hash 变了却没有东西去重读它,点了没反应 —— 而那个没被接住的 `?board=B` 还留在地址里,
 * 下一次列表变化(新建一张板、改个名)时把人拽到 B 上,新建的那张反倒没打开。信箱两种情形都接得住(design 里
 * `boardNavigation.test.ts` 盯着没人再手写)。
 */
export function openBoard(boardId: string): void {
  gotoRecord(boardHref(boardId), OPEN_BOARD_EVENT, boardId);
}

/** 一张画板的地址(给要一个 href 的地方;要「打开」就用 `openBoard`)。 */
export function boardHref(boardId: string): string {
  return `#/boards?board=${encodeURIComponent(boardId)}`;
}

/**
 * 地址里带着的「打开这一条」(`#/boards?board=…` 这种:深链、书签、只改了 hash 的老调用)交给信箱,**并立刻从地址里拿掉**。
 *
 * 读了参数却不清掉,它就会一直留在地址里;页面下一次因为别的原因重读它(列表变了),就把人带到一个他早就没在要的地方。
 * 交给信箱之后,接不接得住(那一条还没加载出来)由 `useOpenRequest` 管 —— 和别处发来的请求同一条路。挂载时读一次,
 * 之后 hash 再变(人已经在这一页上)也读。
 */
export function useHashOpenRequest(route: string, param: string, event: string): void {
  React.useEffect(() => {
    const take = () => {
      const [path, query = ""] = window.location.hash.replace(/^#\/?/, "").split("?");
      if (`#/${path}` !== route) return;
      const id = new URLSearchParams(query).get(param);
      if (!id) return;
      window.history.replaceState(null, "", route);
      emitOpenEvent(event, id);
    };
    take();
    window.addEventListener("hashchange", take);
    return () => window.removeEventListener("hashchange", take);
  }, [route, param, event]);
}

/** 「打开这张画板、把视野挪到这一格」—— 笔记「加到画板」之后那条提示上的「打开画板」。走信箱:画板页、那张板、
 *  画布都要先就位,画布好了自己来取(见 BoardsView 的 BoardDetail)。 */
export const BOARD_ITEM_EVENT = "mosael:focus-board-item";

export function openBoardItem(boardId: string, itemId: string): void {
  openBoard(boardId);
  emitOpenEvent(BOARD_ITEM_EVENT, JSON.stringify({ boardId, itemId }));
}

export function parseBoardItem(raw: string): { boardId: string; itemId: string } | null {
  try {
    const value = JSON.parse(raw) as { boardId?: unknown; itemId?: unknown };
    return typeof value.boardId === "string" && typeof value.itemId === "string" ? { boardId: value.boardId, itemId: value.itemId } : null;
  } catch {
    return null;
  }
}

/** 打开一篇笔记。 */
export function openNote(noteId: string): void {
  window.location.hash = noteHref(noteId);
}

/** 跳到设置的某个分区(如未配置模型 → 直达「模型服务」)。SettingsView 监听 mosael:open-settings。 */
export function gotoSettings(section: string): void {
  gotoRecord("/settings", "mosael:open-settings", section);
}

/**
 * 跳到管理页的某个 tab(如「N 次未定价」→ 成本规则)。AdminView 监听 mosael:open-admin。
 *
 * 管理页只对部署管理员有入口 —— 调用方先判断 `useIsDeploymentAdmin()`,不是管理员就别给这条路:
 * 后端每条管理接口都会拒绝他,跳过去是一页读不出来的东西。
 */
export function gotoAdmin(tab: string): void {
  gotoRecord("/admin", "mosael:open-admin", tab);
}

/** 打开插件市场并找到某个插件(官网「在 Mosael 中打开」)。已经装了就直接选中它。 */
export const OPEN_PLUGIN_IN_MARKET = "mosael:open-plugin-market";
/**
 * 打开插件市场、只看能做某件事的插件(`provides` 里的一项,如 `audio_denoise`)。设置「能力提供方」里
 * 「去插件市场找」用它:用户知道自己要做什么,不知道哪个插件能做(ADR 0032 §5)。
 */
export const OPEN_MARKET_FOR_CAPABILITY = "mosael:open-market-capability";

/** 跳到插件页并打开市场,按能力筛好。 */
export function findPluginsFor(capability: string): void {
  gotoRecord("/plugins", OPEN_MARKET_FOR_CAPABILITY, capability);
}
/** 打开工作流社区并选中某个官方模板(官网「在 Mosael 中打开」)。 */
export const OPEN_WORKFLOW_TEMPLATE = "mosael:open-workflow-template";

/**
 * 打开某条工作流的**某一次运行**:选中那条工作流,执行历史停在那一次(画布和检查器跟着它)。
 * 载荷是「工作流 id/运行 id」—— 信箱里只放得下一串字。
 */
export const OPEN_WORKFLOW_RUN = "mosael:open-workflow-run";

export function workflowRunLink(workflowId: string, runId: string): string {
  return `${workflowId}/${runId}`;
}

export function parseWorkflowRunLink(link: string): { workflowId: string; runId: string } | null {
  const [workflowId, runId, ...rest] = link.split("/");
  return workflowId && runId && !rest.length ? { workflowId, runId } : null;
}

/** 页面 → 打开单条记录的事件名(mosael:// 深链、任务中心「前往」共用)。没有对应事件的页面就只跳页。 */
export const VIEW_RECORD_EVENTS: Record<string, string> = {
  workflows: "mosael:open-workflow",
  entities: "mosael:open-entity",
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
