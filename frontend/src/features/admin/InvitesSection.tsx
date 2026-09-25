import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Plus } from "lucide-react";
import { toast } from "sonner";

import { authBootstrap, createRegistrationInvite, registrationInvites } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { isImeKeystroke } from "@/lib/shortcuts";
import { relativeTime } from "@/lib/time";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

/**
 * 邀请码:关掉自助注册之后,新成员凭它建账号。
 *
 * **开放注册时不摆发码的按钮** —— 摆一个用不上的「生成」,等于让人以为"不发码别人就进不来",
 * 而实际上谁都进得来。那时这一节只说一句「现在不需要邀请码」,并给一条去改的路。
 */
export function InvitesSection({ onOpenDeployment }: { onOpenDeployment: () => void }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const bootstrap = useQuery({ queryKey: ["auth-bootstrap"], queryFn: authBootstrap });
  const inviteOnly = bootstrap.data?.open_registration === false;
  const invites = useQuery({
    queryKey: ["registration-invites"],
    queryFn: registrationInvites,
    retry: false,
    enabled: inviteOnly,
  });
  const [creating, setCreating] = React.useState(false);
  const rows = invites.data ?? [];

  return (
    <AdminSection
      id="invites"
      title={t("deployInvitesTitle")}
      description={inviteOnly ? t("deployInvitesDesc") : undefined}
      actions={
        inviteOnly && (
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus size={13} /> {t("deployInviteNew")}
          </Button>
        )
      }
    >
      <div className={ADMIN_CARD}>
        {bootstrap.isPending || (inviteOnly && invites.isPending) ? (
          <div className="px-4 py-3">
            <Skeleton className="h-8 w-full" />
          </div>
        ) : !inviteOnly ? (
          <AdminRow label={t("adminInvitesOpenTitle")} description={t("adminInvitesOpenNote")}>
            <Button variant="outline" size="sm" onClick={onOpenDeployment}>
              {t("adminInvitesOpenAction")}
            </Button>
          </AdminRow>
        ) : invites.isSuccess && rows.length === 0 ? (
          <EmptyState size="compact" icon={<KeyRound size={15} />} title={t("adminNoInvites")} />
        ) : (
          rows.map((invite) => (
            <AdminRow
              key={invite.code}
              label={<code className="timecode select-all font-normal">{invite.code}</code>}
              description={
                (invite.note || !invite.used) && <>
                  {/* 备注是管理员自己写的数据,按行内 markdown 渲染(和别处数据文本同一个规矩)。 */}
                  {invite.note && <InlineMarkdown text={invite.note} links={false} />}
                  {invite.note && !invite.used && " · "}
                  {!invite.used && t("deployInviteExpires").replace("{t}", relativeTime(invite.expires_at, locale))}
                </>
              }
            >
              <Badge variant={invite.used ? "secondary" : "outline"}>{invite.used ? t("deployInviteUsed") : t("deployInviteOpen")}</Badge>
              {/* 用过的码没有「复制」,但那一格照样占着 —— 否则两行的状态标签对不齐。 */}
              {invite.used ? (
                <span aria-hidden className="size-8" />
              ) : (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("deployInviteCopy")}
                  title={t("deployInviteCopy")}
                  onClick={() => {
                    void navigator.clipboard?.writeText(invite.code);
                    toast.success(t("deployInviteCopied"));
                  }}
                >
                  <Copy />
                </Button>
              )}
            </AdminRow>
          ))
        )}
      </div>
      <InviteDialog open={creating} onClose={() => setCreating(false)} />
    </AdminSection>
  );
}

/** 生成一个码。备注只给管理员自己看;生成后直接复制到剪贴板。 */
function InviteDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [note, setNote] = React.useState("");
  React.useEffect(() => {
    if (open) setNote("");
  }, [open]);
  const create = useMutation({
    mutationFn: () => createRegistrationInvite(note),
    onSuccess: (invite) => {
      void qc.invalidateQueries({ queryKey: ["registration-invites"] });
      void navigator.clipboard?.writeText(invite.code);
      toast.success(t("deployInviteCopied"));
      onClose();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && !create.isPending && onClose()}
      title={t("deployInviteNew")}
      footer={
        <>
          <Button variant="outline" disabled={create.isPending} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button loading={create.isPending} onClick={() => create.mutate()}>
            {t("deployInviteCreate")}
          </Button>
        </>
      }
    >
      <label className={DIALOG_FIELD}>
        <span>{t("deployInviteNoteLabel")}</span>
        <Input
          autoFocus
          value={note}
          placeholder={t("deployInviteNotePlaceholder")}
          onChange={(event) => setNote(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (isImeKeystroke(event)) return;
            if (event.key === "Enter") {
              event.preventDefault();
              if (!create.isPending) create.mutate();
            }
          }}
        />
        <small>{t("deployInviteNewDesc")}</small>
      </label>
    </ModalShell>
  );
}
