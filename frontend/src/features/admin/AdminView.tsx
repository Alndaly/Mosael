import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import { Activity, Coins, ShieldCheck, Users } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/app/chart";
import { EmptyState } from "@/components/layout/EmptyState";
import { DeploymentSection } from "@/features/settings/DeploymentSection";
import { ProviderDefaultsSection } from "@/features/settings/ProviderDefaultsSection";
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
              <li key={row.user_id || "unknown"} className="flex items-center gap-2 text-[12px]">
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
              <code className="timecode text-[11px] text-muted-foreground">
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
            </span>
          </SettingsRow>
        ))}
      </SettingsGroup>

      {/* 部署默认模型:**还没设过的人用哪个**。它是必要的一层 —— 取默认模型没有"随便挑一个"
          的兜底(那个兜底会让界面显示 A 而回答来自 B),所以新人的起点必须有人替他回答。

          **复用设置页那个组件**(只是把读写换成 /api/admin 那一对):选模型这件事已经解决过了
          —— 一个下拉、跨连接列候选、选项里带连接名消歧。在这里再写一份只读列表,就是第二份
          会漂移的实现,而它第一版连标签都是空的。 */}
      <ProviderDefaultsSection
        forDeployment
        capabilities={["chat", "image", "video"]}
        title={t("adminDefaultsTitle")}
        description={t("adminDefaultsDesc")}
      />

      {/* 邀请码与部署管理员的授予仍是同一段逻辑,原样复用,不复制一份。 */}
      <DeploymentSection showAdmins={false} />
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value?: number; hint?: string }) {
  return (
    <div className="grid gap-0.5 rounded-lg border border-border bg-panel p-3">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <strong className="text-[22px] font-semibold tabular-nums leading-none">{value ?? "—"}</strong>
      {hint && <span className="text-[10.5px] text-muted-foreground">{hint}</span>}
    </div>
  );
}
