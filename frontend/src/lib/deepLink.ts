/** 挂载竞速兜底:目标视图挂载、注册监听器的时机不定(懒加载/慢查询),
 *  单次延迟派发会丢事件。改为 80/300/800ms 三连发 — 监听器打开同一条记录
 *  是幂等的,晚到的重复派发无副作用。 */
export function emitOpenEvent(event: string, id: string): void {
  for (const delay of [80, 300, 800]) {
    window.setTimeout(() => window.dispatchEvent(new CustomEvent(event, { detail: id })), delay);
  }
}

/** 深链通道:跳到业务页,并在页面挂载后用 mosael:open-* 事件打开指定记录。 */
export function gotoRecord(route: string, event?: string, id?: unknown): void {
  window.location.hash = route.replace(/^#/, "");
  if (event && typeof id === "string" && id) emitOpenEvent(event, id);
}

/** 通知类型 → 打开单条记录的事件名 + payload 里的记录 id 字段。 */
export const NOTIFICATION_DEEP_LINKS: Record<string, { event: string; payloadKey: string }> = {
  publish: { event: "mosael:open-publish-task", payloadKey: "task_id" },
  workflow: { event: "mosael:open-workflow", payloadKey: "workflow_id" },
};

/** 跳到设置的某个分区(如未配置模型 → 直达「模型服务」)。SettingsView 监听 mosael:open-settings。 */
export function gotoSettings(section: string): void {
  gotoRecord("/settings", "mosael:open-settings", section);
}

/** mosael:// 深链里 view → 打开单条记录的事件名。没有对应事件的页面就只跳页。 */
const VIEW_RECORD_EVENTS: Record<string, string> = {
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
    const link = (event as CustomEvent<{ view?: string; id?: string }>).detail;
    if (!link?.view) return;
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
