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
import { cn } from "@/lib/utils";

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
    refetchOnWindowFocus: true,
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
            <Button variant="ghost" size="icon" className="relative" aria-label={t("notifTitle")}>
              <Bell size={15} />
              {unread > 0 && <em className="absolute -top-0.5 right-[-3px] h-3.5 min-w-3.5 rounded-full bg-primary px-[3px] text-center text-[9.5px] font-bold not-italic leading-[14px] text-primary-foreground">{unread > 99 ? "99+" : unread}</em>}
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>{t("notifTitle")}</TooltipContent>
      </Tooltip>

      <PopoverContent className="w-[340px] overflow-hidden" aria-label={t("notifTitle")}>
        <div className="flex items-center justify-between border-b border-border px-2.5 py-2 [&_strong]:text-[12.5px]">
          <strong>{t("notifTitle")}</strong>
          {unread > 0 && (
            <button
              type="button"
              className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent text-[11px] text-muted-foreground hover:text-destructive"
              disabled={readAll.isPending}
              onClick={() => readAll.mutate()}
            >
              <CheckCheck size={11} /> {t("notifReadAll")}
            </button>
          )}
        </div>
        <div className="grid max-h-[380px] gap-1 overflow-y-auto p-1.5">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="grid cursor-pointer grid-cols-[26px_minmax(0,1fr)_12px] items-start gap-1.5 rounded-md border-0 bg-transparent px-1.5 py-[7px] text-left hover:bg-secondary"
              onClick={() => openItem(item)}
            >
              <span
                className={cn(
                  "grid h-[26px] w-[26px] place-items-center rounded border border-border text-muted-foreground",
                  !item.read_at && "border-[color-mix(in_srgb,var(--primary)_35%,var(--border))] text-primary",
                )}
              >
                {TYPE_ICONS[item.type] ?? <Bell size={13} />}
              </span>
              <span className="grid min-w-0 gap-0.5">
                <span className={cn("truncate text-xs", !item.read_at && "font-semibold")}>{item.title}</span>
                {item.body && <small className="truncate text-[11px] text-muted-foreground">{item.body}</small>}
                <small className="text-[10.5px] text-muted-foreground">{relativeTime(item.created_at, locale)}</small>
              </span>
              {!item.read_at && <i className="mt-[5px] h-1.5 w-1.5 rounded-full bg-primary" />}
            </button>
          ))}
          {items.length === 0 && <p className="m-0 px-3 py-[18px] text-center text-xs leading-[1.6] text-muted-foreground">{t("notifEmpty")}</p>}
        </div>
      </PopoverContent>
    </Popover>
  );
}
