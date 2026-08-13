import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import { Activity, Coins, ShieldCheck, Trash2, Users } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/app/modals";
import { Switch } from "@/components/ui/switch";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/app/chart";
import { EmptyState } from "@/components/layout/EmptyState";
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

// 成功 vs 失败,而不是"总数 vs 失败" —— 后者在全失败的部署上等于把同一根柱子画两遍,
// 一眼看不出任何东西。堆叠之后柱子的高度仍然是当天的总数。
const jobsConfig = {
  succeeded: { label: "", color: "var(--chart-ok)" },
  failed: { label: "", color: "var(--chart-fail)" },
} satisfies ChartConfig;

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
    <div className="grid h-full min-h-0 content-start gap-4 overflow-y-auto p-4">
      {/* `overflow-y-auto` 只有在**高度被约束**时才会滚:没有 h-full/min-h-0,这个 grid 会一直
          长下去、把溢出甩给外层,而外层并没在滚 —— 于是整页卡住。仓库里能滚的几页都是这个写法。 */}
      {/* 四个数放在最上面:它们是"这台部署现在多大"的一句话回答。 */}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("adminStatUsers")} value={stats?.users} hint={t("adminStatActive").replace("{n}", String(stats?.active_users_7d ?? 0))} />
        <Stat label={t("adminStatWorkspaces")} value={stats?.workspaces} />
        <Stat label={t("adminStatAssets")} value={stats?.assets} />
        <Stat label={t("adminStatWindow")} value={stats?.window_days} hint={t("adminStatWindowHint")} />
      </div>

      <SettingsGroup title={t("adminJobsTitle")} description={t("adminJobsDesc")}>
        <div className="w-full">
          {(stats?.jobs_by_day ?? []).length === 0 ? (
            /* 空状态走全局那一个 —— 自己糊一行灰字,和别处的空状态长得不一样,读者会以为
               "这里坏了"而不是"这里还没有东西"。 */
            <EmptyState
              icon={<Activity size={18} />}
              title={t("adminNoDataTitle")}
              body={t("adminNoData")}
            />
          ) : (
            <ChartContainer config={jobsConfig} className="h-[180px]">
              <BarChart data={stats?.jobs_by_day ?? []}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="day" tickLine={false} axisLine={false} tickFormatter={(day: string) => day.slice(5)} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="succeeded" stackId="jobs" fill="var(--color-succeeded)" radius={[0, 0, 2, 2]} />
                <Bar dataKey="failed" stackId="jobs" fill="var(--color-failed)" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ChartContainer>
          )}
        </div>
      </SettingsGroup>

      {/* 花销**按人分**:一个总数说明不了任何该做的决定,而按人分的这一列直接指向要谈的那个人。 */}
      <SettingsGroup title={t("adminSpendTitle")} description={t("adminSpendDesc")}>
        {spend.length === 0 ? (
          <EmptyState
            icon={<Coins size={18} />}
            title={t("adminNoSpendTitle")}
            body={t("adminNoSpend")}
          />
        ) : (
          <ul className="m-0 grid w-full list-none gap-1 p-0">
            {spend.map((row) => (
              <li key={row.user_id || "unknown"} className="flex items-center gap-2 text-ui-sm">
                <span className="w-28 shrink-0 truncate">{row.username || t("adminNoOwner")}</span>
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-secondary">
                  <span
                    className="block h-full rounded-full bg-primary"
                    style={{ width: `${Math.max(2, (row.cost_micros / spend[0].cost_micros) * 100)}%` }}
                  />
                </span>
                <span className="w-24 shrink-0 text-right tabular-nums text-muted-foreground">
                  ¥{(row.cost_micros / 1_000_000).toFixed(2)} · {row.calls}
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
    <div className="grid gap-0.5 rounded-lg border border-border bg-panel p-3">
      <span className="text-ui-xs text-muted-foreground">{label}</span>
      <strong className="text-[22px] font-semibold tabular-nums leading-none">{value ?? "—"}</strong>
      {hint && <span className="text-ui-2xs text-muted-foreground">{hint}</span>}
    </div>
  );
}
