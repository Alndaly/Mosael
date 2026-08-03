import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Plus, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";

type DeploymentUser = {
  id: string;
  username: string;
  display_name: string;
  is_deployment_admin: boolean;
};
type Invite = { code: string; note: string; used: boolean; expires_at: string };

/**
 * 部署级设置 —— 「谁能进这个后端」和「谁对它负责」。
 *
 * **与「团队与成员」是两件事**:那一页管的是某个工作区里谁能做什么;这一页管的是这台后端本身。
 * 一个人可以是三个工作区的 owner 而完全不该碰网络代理、插件启用、解释器路径 —— 反过来,
 * 部署管理员也不因此自动进入任何工作区。
 *
 * 这一页只有部署管理员看得见(后端同判据);其他人连列表都取不到。
 */
export function DeploymentSection({ showAdmins = true }: { showAdmins?: boolean } = {}) {
  const t = useI18n();
  const qc = useQueryClient();
  const users = useQuery({
    queryKey: ["deployment-users"],
    queryFn: () => api<DeploymentUser[]>("/api/auth/users"),
    retry: false,
  });
  const invites = useQuery({
    queryKey: ["registration-invites"],
    queryFn: () => api<Invite[]>("/api/auth/invites"),
    retry: false,
  });

  const setAdmin = useMutation({
    mutationFn: ({ id, granted }: { id: string; granted: boolean }) =>
      api(`/api/auth/users/${id}/deployment-admin`, {
        method: "POST",
        body: JSON.stringify({ granted }),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["deployment-users"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  // 这个部署收不收自助注册。开放时整段邀请码都不该出现 —— 摆一个用不上的生成按钮,
  // 等于让人以为"不发码别人就进不来",而实际上谁都进得来。
  const bootstrap = useQuery({
    queryKey: ["auth-bootstrap"],
    queryFn: () => api<{ open_registration: boolean }>("/api/auth/bootstrap"),
  });
  const inviteOnly = bootstrap.data?.open_registration === false;

  const [note, setNote] = React.useState("");
  const createInvite = useMutation({
    mutationFn: () =>
      api<Invite>("/api/auth/invites", { method: "POST", body: JSON.stringify({ note }) }),
    onSuccess: (invite) => {
      setNote("");
      void qc.invalidateQueries({ queryKey: ["registration-invites"] });
      void navigator.clipboard?.writeText(invite.code);
      toast.success(t("deployInviteCopied"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  // 取不到列表 = 你不是部署管理员。说清楚,而不是显示一个空表让人以为坏了。
  if (users.isError) {
    return (
      <SettingsGroup title={t("deployTitle")} description={t("deployDesc")}>
        <SettingsRow label={t("deployNotAdmin")} description={t("deployNotAdminDesc")} />
      </SettingsGroup>
    );
  }

  const admins = (users.data ?? []).filter((row) => row.is_deployment_admin).length;

  return (
    <>
      {!inviteOnly ? (
        <SettingsGroup title={t("deployInvitesOpenTitle")} description={t("deployInvitesOpenDesc")}>
          <></>
        </SettingsGroup>
      ) : (
      <SettingsGroup title={t("deployInvitesTitle")} description={t("deployInvitesDesc")}>
        <SettingsRow
          label={t("deployInviteNew")}
          description={t("deployInviteNewDesc")}
          className="grid-cols-1 items-start"
        >
          <div className="flex w-full flex-wrap gap-1.5">
            <Input
              className="h-8 max-w-[260px] text-xs"
              value={note}
              placeholder={t("deployInviteNotePlaceholder")}
              onChange={(event) => setNote(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  createInvite.mutate();
                }
              }}
            />
            <Button size="sm" loading={createInvite.isPending} onClick={() => createInvite.mutate()}>
              <Plus size={13} /> {t("deployInviteCreate")}
            </Button>
          </div>
        </SettingsRow>
        {(invites.data ?? []).length > 0 && (
          <SettingsRow label={t("deployInviteList")} className="grid-cols-1 items-start">
            <ul className="m-0 grid w-full list-none gap-1 p-0">
              {(invites.data ?? []).map((invite) => (
                <li
                  key={invite.code}
                  className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-panel px-2.5 py-1.5 text-[11.5px]"
                >
                  <code className="timecode select-all">{invite.code}</code>
                  {invite.note && <span className="text-muted-foreground">{invite.note}</span>}
                  <Badge variant={invite.used ? "secondary" : "outline"} className="ml-auto">
                    {invite.used ? t("deployInviteUsed") : t("deployInviteOpen")}
                  </Badge>
                  {!invite.used && (
                    <button
                      type="button"
                      aria-label={t("deployInviteCopy")}
                      title={t("deployInviteCopy")}
                      className="cursor-pointer border-0 bg-transparent p-0 text-muted-foreground transition-colors hover:text-foreground"
                      onClick={() => {
                        void navigator.clipboard?.writeText(invite.code);
                        toast.success(t("deployInviteCopied"));
                      }}
                    >
                      <Copy size={12} />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </SettingsRow>
        )}
      </SettingsGroup>
      )}

      {showAdmins && (
      <SettingsGroup title={t("deployAdminsTitle")} description={t("deployAdminsDesc")}>
        {(users.data ?? []).map((row) => (
          <SettingsRow
            key={row.id}
            label={row.display_name || row.username}
            description={`@${row.username}`}
          >
            <span className="flex items-center gap-2">
              {row.is_deployment_admin && (
                <Badge variant="default" className="gap-1">
                  <ShieldCheck size={11} /> {t("deployAdminBadge")}
                </Badge>
              )}
              <Switch
                checked={row.is_deployment_admin}
                // 最后一个部署管理员不能被收回 —— 后端会 409,这里先不给点,省掉一次注定失败的往返。
                disabled={setAdmin.isPending || (row.is_deployment_admin && admins <= 1)}
                onCheckedChange={(granted) => setAdmin.mutate({ id: row.id, granted })}
                aria-label={t("deployAdminsTitle")}
              />
            </span>
          </SettingsRow>
        ))}
      </SettingsGroup>
      )}
      {/* 这是一条**规则说明**,不是列表里的一个人。此前它被摆成同一组里的第三行、右边还配
          一个绿勾,读起来像"最后一个不能收回"是某位管理员的名字、而那个勾是他的开关。 */}
      {showAdmins && (
        <p className="mt-1.5 px-0.5 text-[11px] leading-relaxed text-muted-foreground">
          {t("deployLastAdminDesc")}
        </p>
      )}
    </>
  );
}
