import React from "react";
import { PageHeading } from "@/components/layout/StudioPage";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Coins, ShieldCheck, Trash2, Users } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/app/modals";
import { Switch } from "@/components/ui/switch";
import { AdminActivityChart } from "./AdminActivityChart";
import { EmptyState } from "@/components/layout/EmptyState";
import { formatMicros } from "@/lib/money";
import { DeploymentSection } from "@/features/settings/DeploymentSection";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { relativeTime } from "@/lib/time";

type AdminUser = components["schemas"]["AdminUserOut"];
type Overview = components["schemas"]["AdminOverviewOut"];

/**
 * 管理员控制台 —— **这台部署**的状况。
 *
 * 和「设置」是两件事,所以它是侧边栏里独立的一格,不挤在设置页里:设置回答"我怎么用这个应用"
 * (外观、我的密钥、我的默认模型);这里回答"这台部署怎么样" —— 谁进来了、谁在花钱、谁的
 * 客户端还停在旧版本。
 *
 * 入口只对部署管理员显示(见 AppShell),后端每条路由也各自把关 —— 藏起来的入口不是权限。
 */

export function AdminView() {
  const t = useI18n();
  const qc = useQueryClient();
  const overview = useQuery({ queryKey: ["admin-overview"], queryFn: () => api<Overview>("/api/admin/overview") });
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api<AdminUser[]>("/api/admin/users") });

  // 删账号:此前完全没有这条路 —— 能授予、能收回管理员,却删不掉一个账号,于是"清掉那个测试
  // 账号"只能去手改数据库。删的范围与边界在后端(domain/members.delete_account):他独占的
  // 工作区跟着走,还有别人在的挡下来并说清是哪几个。
  const [removing, setRemoving] = React.useState<AdminUser | null>(null);
  const removeUser = useMutation({
    mutationFn: (id: string) => api(`/api/admin/users/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setRemoving(null);
      void qc.invalidateQueries({ queryKey: ["admin-users"] });
      void qc.invalidateQueries({ queryKey: ["admin-overview"] });
    },
    // 挡下来的那句话(哪几个工作区里还有别人)本身就是下一步该做什么,原样给他看。
    onError: (error: Error) => toast.error(error.message),
  });

  const setAdmin = useMutation({
    mutationFn: ({ id, granted }: { id: string; granted: boolean }) =>
      api(`/api/auth/users/${id}/deployment-admin`, { method: "POST", body: JSON.stringify({ granted }) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin-users"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  const stats = overview.data;
  const admins = (users.data ?? []).filter((row) => row.is_deployment_admin).length;
  const spend = (stats?.spend_by_user ?? []).filter((row) => row.cost_micros > 0);

  return (
    <div className="grid h-full min-h-0 content-start gap-7 overflow-y-auto px-6 py-7 xl:px-9 xl:py-8 [&_[data-slot=settings-group-title]]:text-ui-md [&_[data-slot=settings-group-description]]:text-ui-sm">
      <PageHeading title={t("navAdmin")} description={t("studioAdminDesc")} />
      {/* `overflow-y-auto` 只有在**高度被约束**时才会滚:没有 h-full/min-h-0,这个 grid 会一直
          长下去、把溢出甩给外层,而外层并没在滚 —— 于是整页卡住。仓库里能滚的几页都是这个写法。 */}
      {/* 四个数放在最上面:它们是"这台部署现在多大"的一句话回答。 */}
      <div className="grid gap-0 divide-x divide-border rounded-xl border border-border bg-panel sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("adminStatUsers")} value={stats?.users} hint={t("adminStatActive").replace("{n}", String(stats?.active_users_7d ?? 0))} />
        <Stat label={t("adminStatWorkspaces")} value={stats?.workspaces} />
        <Stat label={t("adminStatAssets")} value={stats?.assets} />
        <Stat label={t("adminStatWindow")} value={stats?.window_days} hint={t("adminStatWindowHint")} />
      </div>

      <SettingsGroup title={t("adminJobsTitle")} description={t("adminJobsDesc")}>
        <AdminActivityChart points={stats?.jobs_by_day ?? []} loading={overview.isPending} error={overview.isError} onRetry={() => void overview.refetch()} />
      </SettingsGroup>

      {/* 花销**按人分**:一个总数说明不了任何该做的决定,而按人分的这一列直接指向要谈的那个人。 */}
      <SettingsGroup title={t("adminSpendTitle")} description={t("adminSpendDesc")}>
        {spend.length === 0 ? (
          <EmptyState
            size="compact"
            className="my-3 max-w-none gap-2 rounded-lg border border-border bg-panel py-6"
            icon={<Coins size={18} />}
            title={t("adminNoSpendTitle")}
            body={t("adminNoSpend")}
          />
        ) : (
          /* 和这一页其它段落同一种壳:卡片 + 行。此前这一摞是**裸的** —— 上下都是带边框的卡,
             中间夹一条没有容器的进度条,读起来像掉出去的一行。 */
          <ul className="m-0 grid w-full list-none gap-2.5 rounded-md border border-border bg-panel p-2.5">
            {spend.map((row) => (
              <li
                key={row.user_id || "unknown"}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-2 gap-y-1 text-ui-sm"
              >
                <span className="min-w-0 truncate">{row.username || t("adminNoOwner")}</span>
                {/* 金额**不设固定宽、不换行**:此前 w-24 装不下「0.0007 USD · 6」,
                    调用次数被挤到第二行(真机截图)。 */}
                <span className="whitespace-nowrap text-right text-ui-xs tabular-nums text-muted-foreground">
                  {formatMicros(row.cost_micros, stats?.currency ?? "USD")} · {row.calls}
                </span>
                <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-secondary">
                  <span
                    className="block h-full rounded-full bg-primary"
                    style={{ width: `${Math.max(2, (row.cost_micros / (spend[0]?.cost_micros || 1)) * 100)}%` }}
                  />
                </span>
              </li>
            ))}
          </ul>
        )}
      </SettingsGroup>

      <SettingsGroup title={t("adminUsersTitle")} description={t("adminUsersDesc")}>
        {users.isSuccess && (users.data ?? []).length === 0 && (
          <EmptyState icon={<Users size={18} />} title={t("adminNoUsersTitle")} body={t("adminNoUsers")} />
        )}
        {(users.data ?? []).map((row) => (
          <SettingsRow
            key={row.id}
            label={row.display_name || row.username}
            description={`@${row.username} · ${
              row.last_seen_at ? t("adminSeen").replace("{t}", relativeTime(row.last_seen_at, "zh-CN")) : t("adminNeverSeen")
            } · ${row.workspaces} ${t("adminWorkspacesUnit")}`}
          >
            <span className="flex items-center gap-2">
              {/* 版本由客户端自报;报不上来的老客户端显示"未知",不编一个号出来。 */}
              <code className="timecode text-ui-xs text-muted-foreground">
                {row.client_version ? `v${row.client_version}` : t("adminUnknownVersion")}
              </code>
              {row.is_deployment_admin && (
                <Badge variant="default" className="gap-1">
                  <ShieldCheck size={11} /> {t("deployAdminBadge")}
                </Badge>
              )}
              <Switch
                checked={row.is_deployment_admin}
                // 最后一个部署管理员不能被收回 —— 后端会 409,这里先不给点。
                disabled={setAdmin.isPending || (row.is_deployment_admin && admins <= 1)}
                onCheckedChange={(granted) => setAdmin.mutate({ id: row.id, granted })}
                aria-label={t("deployAdminsTitle")}
              />
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-destructive"
                // 最后一个管理员删不得,同上。
                disabled={removeUser.isPending || (row.is_deployment_admin && admins <= 1)}
                onClick={() => setRemoving(row)}
                aria-label={t("adminDeleteUser")}
              >
                <Trash2 size={13} />
              </Button>
            </span>
          </SettingsRow>
        ))}
      </SettingsGroup>

      {/* 邀请码与部署管理员的授予仍是同一段逻辑,原样复用,不复制一份。 */}
      <DeploymentSection showAdmins={false} />

      <ConfirmDialog
        open={removing !== null}
        title={t("adminDeleteUser")}
        // 说清后果再问 —— 这一步不可撤销,而"删掉账号"四个字没说他的工作区也跟着走。
        body={t("adminDeleteUserBody").replace("{name}", removing?.display_name || removing?.username || "")}
        onCancel={() => setRemoving(null)}
        onConfirm={() => removing && removeUser.mutate(removing.id)}
      />
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value?: number; hint?: string }) {
  return (
    <div className="flex flex-col gap-3 p-6">
      <span className="text-ui-xs text-muted-foreground">{label}</span>
      <strong className="text-3xl font-semibold tabular-nums leading-tight">{value ?? "—"}</strong>
      {hint && <span className="text-ui-2xs text-muted-foreground">{hint}</span>}
    </div>
  );
}
