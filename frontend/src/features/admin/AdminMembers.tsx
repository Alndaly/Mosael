import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck, ShieldOff, Trash2, Users } from "lucide-react";
import { toast } from "sonner";

import { adminUsers, deleteAccount, setDeploymentAdmin, type AdminUser } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { ConfirmDialog } from "@/components/app/modals";
import { ActionMenu } from "@/components/layout/ActionMenu";
import { EmptyState } from "@/components/layout/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ADMIN_CARD, AdminSection } from "./adminLayout";
import { InvitesSection } from "./InvitesSection";

/**
 * 「哪个界面」要不要加个前缀。
 *
 * `app` 是默认那一个,不加前缀(每一行都写「桌面端」等于什么都没说);扩展加。
 * 空 = 老客户端报的是旧语法(裸版本号),那就只显示版本 —— 编一个界面出来比留白更糟。
 */
const SURFACE_LABEL = { "browser-extension": "adminSurfaceExtension" } as const;

/** 表头与单元格共用的横向内边距;窄的时候先藏「工作区」,再藏「客户端」。 */
const CELL = "px-4 py-3 text-left align-middle";
const WIDE_ONLY = "hidden @min-[720px]/accounts:table-cell";
const MEDIUM_UP = "hidden @min-[560px]/accounts:table-cell";

/** 成员 tab:账户列表 + 邀请码。 */
export function AdminMembers({ onOpenDeployment }: { onOpenDeployment: () => void }) {
  return (
    <>
      <AccountsSection />
      <InvitesSection onOpenDeployment={onOpenDeployment} />
    </>
  );
}

function AccountsSection() {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: adminUsers });

  // 删账号:删的范围与边界在后端(domain/members.delete_account):他独占的工作区跟着走,
  // 还有别人在的挡下来并说清是哪几个。
  const [removing, setRemoving] = React.useState<AdminUser | null>(null);
  const removeUser = useMutation({
    mutationFn: (id: string) => deleteAccount(id),
    onSuccess: () => {
      setRemoving(null);
      void qc.invalidateQueries({ queryKey: ["admin-users"] });
      void qc.invalidateQueries({ queryKey: ["admin-overview"] });
    },
    // 挡下来的那句话(哪几个工作区里还有别人)本身就是下一步该做什么,原样给他看。
    onError: (error: Error) => toast.error(error.message),
  });
  const setAdmin = useMutation({
    mutationFn: ({ id, granted }: { id: string; granted: boolean }) => setDeploymentAdmin(id, granted),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin-users"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  const rows = users.data ?? [];
  const admins = rows.filter((row) => row.is_deployment_admin).length;

  return (
    <AdminSection
      id="accounts"
      title={t("adminUsersTitle")}
      description={t("adminUsersDesc")}
      count={users.isSuccess ? rows.length : undefined}
    >
      <div className={cn(ADMIN_CARD, "@container/accounts")}>
        {users.isSuccess && rows.length === 0 ? (
          <EmptyState size="compact" icon={<Users size={15} />} title={t("adminNoUsersTitle")} body={t("adminNoUsers")} />
        ) : (
          <table className="w-full table-fixed border-collapse text-ui-sm">
            <thead className="text-ui-xs text-muted-foreground">
              <tr className="border-b border-divider">
                <th scope="col" className={cn(CELL, "py-2.5 font-medium")}>{t("adminColMember")}</th>
                <th scope="col" className={cn(CELL, "w-[9.5rem] py-2.5 font-medium")}>{t("adminColRole")}</th>
                <th scope="col" className={cn(CELL, MEDIUM_UP, "w-[8.5rem] py-2.5 font-medium")}>{t("adminColLastSeen")}</th>
                <th scope="col" className={cn(CELL, WIDE_ONLY, "w-[6rem] py-2.5 text-right font-medium")}>{t("adminColWorkspaces")}</th>
                <th scope="col" className={cn(CELL, WIDE_ONLY, "w-[10rem] py-2.5 font-medium")}>{t("adminColClient")}</th>
                <th scope="col" className={cn(CELL, "w-14 py-2.5")}>
                  <span className="sr-only">{t("adminRowActions")}</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-divider">
              {users.isPending &&
                [0, 1, 2].map((key) => (
                  <tr key={key}>
                    <td className={CELL} colSpan={6}>
                      <Skeleton className="h-8 w-full" />
                    </td>
                  </tr>
                ))}
              {rows.map((row) => {
                // 最后一个部署管理员不能被收回、也删不得 —— 后端会 409,这里先不给点。
                const lastAdmin = row.is_deployment_admin && admins <= 1;
                const name = row.display_name || row.username;
                const seen = row.last_seen_at ? relativeTime(row.last_seen_at, locale) : t("adminNeverSeen");
                return (
                  <tr key={row.id} data-account={row.username}>
                    <td className={CELL}>
                      <div className="flex min-w-0 items-center gap-3">
                        <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-full bg-secondary text-ui-xs font-semibold uppercase text-muted-foreground">
                          {Array.from(name)[0]}
                        </span>
                        <div className="grid min-w-0 gap-0.5">
                          <span className="truncate font-medium" title={name}>{name}</span>
                          <span className="truncate text-ui-xs text-muted-foreground" title={`@${row.username}`}>
                            @{row.username}
                            {/* 窄的时候「最近活跃」那一列藏起来了,它挪到名字下面。 */}
                            <span className="@min-[560px]/accounts:hidden"> · {seen}</span>
                          </span>
                        </div>
                      </div>
                    </td>
                    <td className={CELL}>
                      {row.is_deployment_admin ? (
                        <Badge variant="default" className="gap-1 whitespace-nowrap">
                          <ShieldCheck size={11} /> {t("deployAdminBadge")}
                        </Badge>
                      ) : (
                        <span className="text-ui-xs text-muted-foreground">{t("adminRoleMember")}</span>
                      )}
                    </td>
                    <td className={cn(CELL, MEDIUM_UP, "text-ui-xs tabular-nums text-muted-foreground")}>{seen}</td>
                    <td className={cn(CELL, WIDE_ONLY, "text-right tabular-nums")}>{row.workspaces}</td>
                    <td className={cn(CELL, WIDE_ONLY)}>
                      {/* 版本由客户端自报;报不上来的老客户端显示"未知",不编一个号出来。界面和版本是
                          **两栏**:浏览器扩展往版本里塞的是产品名,只有一栏时渲染出「vbrowser-extension」。 */}
                      <code className="timecode block truncate text-ui-xs text-muted-foreground">
                        {row.client_version
                          ? `${
                              row.client_surface in SURFACE_LABEL
                                ? `${t(SURFACE_LABEL[row.client_surface as keyof typeof SURFACE_LABEL])} `
                                : ""
                            }v${row.client_version}`
                          : t("adminUnknownVersion")}
                      </code>
                    </td>
                    <td className={cn(CELL, "text-right")}>
                      <ActionMenu
                        label={`${t("adminRowActions")} · ${name}`}
                        actions={[
                          row.is_deployment_admin
                            ? {
                                label: t("adminRevokeAdmin"),
                                icon: <ShieldOff size={14} />,
                                hint: lastAdmin ? t("adminLastAdminHint") : undefined,
                                disabled: lastAdmin || setAdmin.isPending,
                                onSelect: () => setAdmin.mutate({ id: row.id, granted: false }),
                              }
                            : {
                                label: t("adminGrantAdmin"),
                                icon: <ShieldCheck size={14} />,
                                disabled: setAdmin.isPending,
                                onSelect: () => setAdmin.mutate({ id: row.id, granted: true }),
                              },
                          {
                            label: t("adminDeleteUser"),
                            icon: <Trash2 size={14} />,
                            destructive: true,
                            hint: lastAdmin ? t("adminLastAdminHint") : undefined,
                            disabled: lastAdmin || removeUser.isPending,
                            onSelect: () => setRemoving(row),
                          },
                        ]}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <ConfirmDialog
        open={removing !== null}
        title={t("adminDeleteUser")}
        // 说清后果再问 —— 这一步不可撤销,而"删掉账号"四个字没说他的工作区也跟着走。
        body={t("adminDeleteUserBody").replace("{name}", removing?.display_name || removing?.username || "")}
        onCancel={() => setRemoving(null)}
        pending={removeUser.isPending}
        onConfirm={() => removing && removeUser.mutate(removing.id)}
      />
    </AdminSection>
  );
}
