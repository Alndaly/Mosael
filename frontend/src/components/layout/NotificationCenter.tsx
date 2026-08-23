import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, Bot, Check, CheckCheck, GitBranch, Send, Trash2, Users, X } from "lucide-react";

import {
  clearReadNotifications,
  listNotifications,
  myInvitations,
  readAllNotifications,
  readNotification,
  respondInvitation,
  type AppNotification,
} from "@/api/client";
import { EmptyState } from "@/components/layout/EmptyState";
import { useI18n, usePreferences } from "@/app/preferences";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { NOTIFICATION_DEEP_LINKS, gotoRecord } from "@/lib/deepLink";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

const TYPE_ICONS: Record<string, React.ReactNode> = {
  publish: <Send size={13} />,
  workflow: <GitBranch size={13} />,
  team: <Users size={13} />,
  agent: <Bot size={13} />,
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
  const clearRead = useMutation({
    mutationFn: () => clearReadNotifications(workspaceId),
    onSuccess: invalidate,
  });

  // 待处理邀请:用户级接口(不受当前工作区限制),邀请卡置顶渲染 接受/拒绝。
  const invitations = useQuery({
    queryKey: ["my-invitations"],
    queryFn: myInvitations,
    refetchInterval: 30000,
    refetchOnWindowFocus: true,
  });
  const respond = useMutation({
    mutationFn: ({ id, accept }: { id: string; accept: boolean }) => respondInvitation(id, accept),
    onSuccess: (inv, vars) => {
      toast.success(
        vars.accept
          ? t("notifInviteAccepted").replace("{ws}", inv.workspace_name)
          : t("notifInviteDeclined"),
      );
      void qc.invalidateQueries({ queryKey: ["my-invitations"] });
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
      invalidate();
    },
  });
  const pendingInvites = invitations.data?.invitations ?? [];

  const items = query.data?.items ?? [];
  const unread = (query.data?.unread ?? 0) + pendingInvites.length;

  // 点通知 → 跳业务页并打开那条记录(payload 里带记录 id,走 openstudio:open-* 深链通道)。
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
        <div className="flex items-center justify-between border-b border-border px-2.5 py-2 [&_strong]:text-ui-sm">
          <strong>{t("notifTitle")}</strong>
          <span className="flex items-center gap-2.5">
            {unread > 0 && (
              <button
                type="button"
                className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent text-ui-xs text-muted-foreground hover:text-foreground"
                disabled={readAll.isPending}
                onClick={() => readAll.mutate()}
              >
                <CheckCheck size={11} /> {t("notifReadAll")}
              </button>
            )}
            {/* 全是已读时头部原来空空如也 —— 50 条旧通知只能一直霸着面板。
                清空只删已读:未读是还没送达的信息,不该被顺手带走。 */}
            {items.some((item) => item.read_at) && (
              <button
                type="button"
                className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent text-ui-xs text-muted-foreground hover:text-destructive"
                disabled={clearRead.isPending}
                onClick={() => clearRead.mutate()}
              >
                <Trash2 size={11} /> {t("notifClearRead")}
              </button>
            )}
          </span>
        </div>
        {/* 单列 grid 的隐式列是 max-content —— 一条长通知正文会把整个弹层撑到能左右滚
            (任务中心同一处坑)。锁住列宽,行内的 truncate 才有定数可截。 */}
        <div className="grid max-h-[380px] grid-cols-[minmax(0,1fr)] gap-1 overflow-y-auto overflow-x-hidden p-1.5">
          {pendingInvites.map((inv) => (
            <div
              key={inv.id}
              className="grid gap-1.5 rounded-lg border border-[color-mix(in_srgb,var(--primary)_28%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_5%,transparent)] px-2.5 py-2"
            >
              <span className="text-xs font-semibold">
                {t("notifInviteTitle").replace("{ws}", inv.workspace_name)}
              </span>
              <small className="text-ui-xs text-muted-foreground">
                {t("notifInviteBody").replace("{name}", inv.inviter_name).replace("{role}", t(`role_${inv.role}` as never))}
              </small>
              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  className="h-7"
                  loading={respond.isPending}
                  onClick={() => respond.mutate({ id: inv.id, accept: true })}
                >
                  <Check size={12} /> {t("notifInviteAccept")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-muted-foreground"
                  loading={respond.isPending}
                  onClick={() => respond.mutate({ id: inv.id, accept: false })}
                >
                  <X size={12} /> {t("notifInviteDecline")}
                </Button>
              </div>
            </div>
          ))}
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="grid cursor-pointer grid-cols-[26px_minmax(0,1fr)_12px] items-start gap-1.5 rounded-md border-0 bg-transparent px-1.5 py-[7px] text-left hover:bg-secondary"
              onClick={() => openItem(item)}
            >
              <span
                className={cn(
                  "grid h-[26px] w-[26px] place-items-center rounded-md border border-border text-muted-foreground",
                  !item.read_at && "border-[color-mix(in_srgb,var(--primary)_35%,var(--border))] text-primary",
                )}
              >
                {TYPE_ICONS[item.type] ?? <Bell size={13} />}
              </span>
              <span className="grid min-w-0 gap-0.5">
                <span className={cn("truncate text-xs", !item.read_at && "font-semibold")}>{item.title}</span>
                {item.body && <small className="truncate text-ui-xs text-muted-foreground">{item.body}</small>}
                <small className="text-ui-2xs text-muted-foreground">{relativeTime(item.created_at, locale)}</small>
              </span>
              {!item.read_at && <i className="mt-[5px] h-1.5 w-1.5 rounded-full bg-primary" />}
            </button>
          ))}
          {items.length === 0 && pendingInvites.length === 0 && (
            <EmptyState size="compact" icon={<BellOff size={15} />} title={t("notifEmptyTitle")} body={t("notifEmpty")} />
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
