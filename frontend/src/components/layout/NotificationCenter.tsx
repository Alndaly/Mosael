import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck, GitBranch, Layers, Send, Users } from "lucide-react";

import {
  listNotifications,
  readAllNotifications,
  readNotification,
  type AppNotification,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { NOTIFICATION_DEEP_LINKS, gotoRecord } from "@/lib/deepLink";
import { relativeTime } from "@/lib/time";

const TYPE_ICONS: Record<string, React.ReactNode> = {
  publish: <Send size={13} />,
  workflow: <GitBranch size={13} />,
  batch: <Layers size={13} />,
  team: <Users size={13} />,
};

/** 站内通知中心:发布结果、工作流失败、批量完成、团队协作申请等
 * 「值得留痕的结果」都落在这里,与任务中心(进行中的进度)互补。 */
export function NotificationCenter({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);

  const query = useQuery({
    queryKey: ["notifications", workspaceId],
    queryFn: () => listNotifications(workspaceId),
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
  });
  const invalidate = () => void qc.invalidateQueries({ queryKey: ["notifications", workspaceId] });
  const readOne = useMutation({ mutationFn: readNotification, onSuccess: invalidate });
  const readAll = useMutation({
    mutationFn: () => readAllNotifications(workspaceId),
    onSuccess: invalidate,
  });

  const items = query.data?.items ?? [];
  const unread = query.data?.unread ?? 0;

  // 点通知 → 跳业务页并打开那条记录(payload 里带记录 id,走 mibu:open-* 深链通道)。
  const openItem = (item: AppNotification) => {
    if (!item.read_at) readOne.mutate(item.id);
    if (item.link) {
      const deep = NOTIFICATION_DEEP_LINKS[item.type];
      gotoRecord(item.link, deep?.event, deep ? item.payload?.[deep.payloadKey] : undefined);
      setOpen(false);
    }
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) void query.refetch();
      }}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="notif-btn" aria-label={t("notifTitle")}>
              <Bell size={15} />
              {unread > 0 && <em className="taskcenter-badge">{unread > 99 ? "99+" : unread}</em>}
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{t("notifTitle")}</TooltipContent>
      </Tooltip>

      <PopoverContent className="notif-pop" aria-label={t("notifTitle")}>
        <div className="taskcenter-head">
          <strong>{t("notifTitle")}</strong>
          {unread > 0 && (
            <button
              type="button"
              className="taskcenter-clear"
              disabled={readAll.isPending}
              onClick={() => readAll.mutate()}
            >
              <CheckCheck size={11} /> {t("notifReadAll")}
            </button>
          )}
        </div>
        <div className="notif-list">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={item.read_at ? "notif-row" : "notif-row unread"}
              onClick={() => openItem(item)}
            >
              <span className="notif-icon">{TYPE_ICONS[item.type] ?? <Bell size={13} />}</span>
              <span className="notif-body">
                <span className="notif-title">{item.title}</span>
                {item.body && <small className="notif-desc">{item.body}</small>}
                <small className="notif-time">{relativeTime(item.created_at, locale)}</small>
              </span>
              {!item.read_at && <i className="notif-dot" />}
            </button>
          ))}
          {items.length === 0 && <p className="taskcenter-empty">{t("notifEmpty")}</p>}
        </div>
      </PopoverContent>
    </Popover>
  );
}
