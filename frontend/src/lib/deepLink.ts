/** 挂载竞速兜底:目标视图挂载、注册监听器的时机不定(懒加载/慢查询),
 *  单次延迟派发会丢事件。改为 80/300/800ms 三连发 — 监听器打开同一条记录
 *  是幂等的,晚到的重复派发无副作用。 */
export function emitOpenEvent(event: string, id: string): void {
  for (const delay of [80, 300, 800]) {
    window.setTimeout(() => window.dispatchEvent(new CustomEvent(event, { detail: id })), delay);
  }
}

/** 深链通道:跳到业务页,并在页面挂载后用 openstudio:open-* 事件打开指定记录。 */
export function gotoRecord(route: string, event?: string, id?: unknown): void {
  window.location.hash = route.replace(/^#/, "");
  if (event && typeof id === "string" && id) emitOpenEvent(event, id);
}

/** 通知类型 → 打开单条记录的事件名 + payload 里的记录 id 字段。 */
export const NOTIFICATION_DEEP_LINKS: Record<string, { event: string; payloadKey: string }> = {
  publish: { event: "openstudio:open-publish-task", payloadKey: "task_id" },
  workflow: { event: "openstudio:open-workflow", payloadKey: "workflow_id" },
};

/** 跳到设置的某个分区(如未配置模型 → 直达「模型服务」)。SettingsView 监听 openstudio:open-settings。 */
export function gotoSettings(section: string): void {
  gotoRecord("/settings", "openstudio:open-settings", section);
}
