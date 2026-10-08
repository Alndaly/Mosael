import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link2, X } from "lucide-react";
import { toast } from "sonner";

import {
  createWorkspaceInviteLink,
  requestInviteSignup,
  type InviteLink,
  type IssuedInviteLink,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { InviteLinkReveal } from "@/components/app/InviteLinkReveal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsListItem } from "@/components/settings/settings-layout";
import { Truncate } from "@/components/ui/truncate";
import { relativeTime } from "@/lib/time";

/** 团队页的邀请链接缓存键:发、撤回、请放行之后都失效它。 */
export const inviteLinksKey = (workspaceId: string) => ["workspace-invite-links", workspaceId] as const;

/**
 * 发一张邀请链接(ADR 0054):选角色 → 生成 → 当场复制(原文只这一次)。7 天、一次性、能撤回。
 *
 * 还没账号的人能不能凭它注册,是部署那道门的事(D48):部署管理员发的自带;部署开放注册时也行;否则这张只对已有账号的人
 * 有效,这里给一颗「请部署管理员放行」。
 */
export function InviteLinkDialog({
  open,
  workspaceId,
  workspaceName,
  onClose,
}: {
  open: boolean;
  workspaceId: string;
  workspaceName: string;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [role, setRole] = React.useState("editor");
  const [issued, setIssued] = React.useState<IssuedInviteLink | null>(null);
  React.useEffect(() => {
    if (open) {
      setRole("editor");
      setIssued(null);
    }
  }, [open]);
  const create = useMutation({
    mutationFn: () => createWorkspaceInviteLink(workspaceId, role),
    onSuccess: (result) => {
      setIssued(result);
      void qc.invalidateQueries({ queryKey: inviteLinksKey(workspaceId) });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const ask = useMutation({
    mutationFn: (linkId: string) => requestInviteSignup(workspaceId, linkId),
    onSuccess: (link) => {
      setIssued((current) => (current ? { ...current, link } : current));
      void qc.invalidateQueries({ queryKey: inviteLinksKey(workspaceId) });
      toast.success(t("inviteLinkSignupRequested"));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const link = issued?.link;
  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && !create.isPending && onClose()}
      title={t("inviteLinkNew")}
      footer={
        issued ? (
          <Button onClick={onClose}>{t("close")}</Button>
        ) : (
          <>
            <Button variant="outline" disabled={create.isPending} onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button loading={create.isPending} onClick={() => create.mutate()}>
              <Link2 size={13} /> {t("inviteLinkCreate")}
            </Button>
          </>
        )
      }
    >
      <p className="m-0 mb-3 text-ui-xs leading-[1.6] text-muted-foreground">
        {t("inviteLinkNewDesc").replace("{name}", workspaceName)}
      </p>
      {issued && link ? (
        <div className="grid gap-3">
          <InviteLinkReveal code={issued.code} webUrl={issued.web_url} />
          <div data-invite-link-signup="" className="grid gap-2 rounded-md bg-secondary px-3 py-2.5 text-ui-xs leading-[1.6] text-muted-foreground">
            <span>
              {link.allows_signup
                ? t("inviteLinkSignupYes")
                : link.signup_requested
                  ? t("inviteLinkSignupWaiting")
                  : t("inviteLinkSignupNo")}
            </span>
            {!link.allows_signup && !link.signup_requested && (
              <span>
                <Button size="sm" variant="outline" loading={ask.isPending} onClick={() => ask.mutate(link.id)}>
                  {t("inviteLinkAskSignup")}
                </Button>
              </span>
            )}
          </div>
        </div>
      ) : (
        <label className={DIALOG_FIELD}>
          <span>{t("teamRole")}</span>
          <Select value={role} onValueChange={setRole}>
            <SelectTrigger aria-label={t("teamRole")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="admin">{t("role_admin")}</SelectItem>
              <SelectItem value="editor">{t("role_editor")}</SelectItem>
              <SelectItem value="viewer">{t("role_viewer")}</SelectItem>
            </SelectContent>
          </Select>
          <small>{t("inviteLinkRoleHint")}</small>
        </label>
      )}
    </ModalShell>
  );
}

/** 一张发出去、还能用的邀请链接:末尾几位、什么角色、能不能顺带注册、谁发的、多久过期,能撤回。 */
export function PendingInviteLinkRow({
  link,
  roleLabel,
  onRevoke,
}: {
  link: InviteLink;
  roleLabel: (role: string) => string;
  onRevoke: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const signup = link.allows_signup
    ? t("inviteLinkBadgeSignup")
    : link.signup_requested
      ? t("inviteLinkBadgeWaiting")
      : t("inviteLinkBadgeMembersOnly");
  return (
    <SettingsListItem data-pending-invite-link={link.id} className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className="inline-flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border border-dashed border-border text-muted-foreground" aria-hidden>
          <Link2 size={12} />
        </span>
        <span className="shrink-0 text-ui-md text-muted-foreground">
          {t("inviteLinkRowName")} <code className="timecode text-ui-xs">··{link.code_hint}</code>
        </span>
        <Badge variant="secondary">{signup}</Badge>
        <Truncate className="text-ui-xs text-muted-foreground">
          {t("inviteLinkRowMeta")
            .replace("{name}", link.created_by_name)
            .replace("{t}", relativeTime(link.expires_at, locale))}
        </Truncate>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <Badge variant="outline">{roleLabel(link.role)}</Badge>
        <IconButton onClick={onRevoke} label={t("inviteLinkRevoke")}>
          <X size={14} />
        </IconButton>
      </div>
    </SettingsListItem>
  );
}
