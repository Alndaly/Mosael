import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

export type AppNotification = components["schemas"]["NotificationOut"];
export type NotificationList = components["schemas"]["NotificationListOut"];

export function listNotifications(workspaceId: string): Promise<NotificationList> {
  return api<NotificationList>(`/api/notifications?workspace_id=${workspaceId}`);
}

export function readNotification(id: string): Promise<AppNotification> {
  return api<AppNotification>(`/api/notifications/${id}/read`, { method: "POST" });
}

export function readAllNotifications(workspaceId: string): Promise<{ read: number }> {
  return api(`/api/notifications/read-all?workspace_id=${workspaceId}`, { method: "POST" });
}

export function clearReadNotifications(workspaceId: string): Promise<{ removed: number }> {
  return api(`/api/notifications/read?workspace_id=${workspaceId}`, { method: "DELETE" });
}
