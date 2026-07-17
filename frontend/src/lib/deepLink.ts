/** 深链通道:跳到业务页,并在页面挂载后用 mibu:open-* 事件打开指定记录。
 *  延迟派发是因为 hash 切换后目标视图要先挂载、注册监听器(与任务中心既有约定一致)。 */
export function gotoRecord(route: string, event?: string, id?: unknown): void {
  window.location.hash = route.replace(/^#/, "");
  if (event && typeof id === "string" && id) {
    window.setTimeout(() => window.dispatchEvent(new CustomEvent(event, { detail: id })), 80);
  }
}

/** 通知类型 → 打开单条记录的事件名 + payload 里的记录 id 字段。 */
export const NOTIFICATION_DEEP_LINKS: Record<string, { event: string; payloadKey: string }> = {
  publish: { event: "mibu:open-publish-task", payloadKey: "task_id" },
  workflow: { event: "mibu:open-workflow", payloadKey: "workflow_id" },
  batch: { event: "mibu:open-batch", payloadKey: "batch_id" },
};

/** 跳到设置的某个分区(如未配置模型 → 直达「模型服务」)。SettingsView 监听 mibu:open-settings。 */
export function gotoSettings(section: string): void {
  gotoRecord("/settings", "mibu:open-settings", section);
}
