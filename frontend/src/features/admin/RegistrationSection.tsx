import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Plus } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  SettingsBlock,
  SettingsBlockTitle,
  SettingsGroup,
  SettingsList,
  SettingsListItem,
  SettingsRow,
  SettingsSectionStack,
  SETTINGS_FIELD_WIDTH,
} from "@/components/settings/settings-layout";

type Invite = { code: string; note: string; used: boolean; expires_at: string };

/**
 * 谁能进这台部署:开不开放自助注册,不开放时发邀请码。
 *
 * 只在管理控制台里出现 —— 它管的是这台后端,不是某个人怎么用应用,所以不在「设置」里。
 * 谁是部署管理员、删账号,在控制台的成员列表里,这里不再各写一份。
 */
export function RegistrationSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const invites = useQuery({
    queryKey: ["registration-invites"],
    queryFn: () => api<Invite[]>("/api/auth/invites"),
    retry: false,
  });

  // 这个部署收不收自助注册。开放时整段邀请码都不该出现 —— 摆一个用不上的生成按钮,
  // 等于让人以为"不发码别人就进不来",而实际上谁都进得来。
  const bootstrap = useQuery({
    queryKey: ["auth-bootstrap"],
    queryFn: () => api<{ open_registration: boolean }>("/api/auth/bootstrap"),
  });
  const inviteOnly = bootstrap.data?.open_registration === false;
  // 开关在这里改,不必去改环境变量重启后端 —— 谁能进这个部署,是部署管理员在界面上就该能做
  // 的决定(和发邀请码、授予管理员同一类)。
  const setRegistration = useMutation({
    mutationFn: (open: boolean) => api("/api/admin/registration", { method: "PUT", body: JSON.stringify({ open }) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["auth-bootstrap"] });
      void qc.invalidateQueries({ queryKey: ["registration-invites"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

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

  return (
    <SettingsSectionStack>
      <SettingsGroup title={t("deployRegistrationTitle")} description={t("deployRegistrationDesc")}>
        <SettingsRow label={t("deployRegistrationOpen")} description={t("deployRegistrationOpenHint")}>
          <Switch
            checked={!inviteOnly}
            disabled={setRegistration.isPending || bootstrap.isLoading}
            onCheckedChange={(open) => setRegistration.mutate(open)}
            aria-label={t("deployRegistrationOpen")}
          />
        </SettingsRow>
      </SettingsGroup>

      {!inviteOnly ? null : (
      <SettingsGroup title={t("deployInvitesTitle")} description={t("deployInvitesDesc")}>
        <SettingsRow
          label={t("deployInviteNew")}
          description={t("deployInviteNewDesc")}
          className="grid-cols-1 items-start"
        >
          <div className="flex w-full flex-wrap gap-1.5">
            <Input
              className={SETTINGS_FIELD_WIDTH}
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
            <Button loading={createInvite.isPending} onClick={() => createInvite.mutate()}>
              <Plus size={13} /> {t("deployInviteCreate")}
            </Button>
          </div>
        </SettingsRow>
        {(invites.data ?? []).length > 0 && (
          <SettingsBlock>
            <SettingsBlockTitle>{t("deployInviteList")}</SettingsBlockTitle>
            <SettingsList className="w-full">
              {(invites.data ?? []).map((invite) => (
                <SettingsListItem
                  key={invite.code}
                  className="flex flex-wrap items-center gap-2 text-ui-xs"
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
                </SettingsListItem>
              ))}
            </SettingsList>
          </SettingsBlock>
        )}
      </SettingsGroup>
      )}
    </SettingsSectionStack>
  );
}
