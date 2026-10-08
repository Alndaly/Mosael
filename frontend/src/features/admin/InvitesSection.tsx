import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, KeyRound, Plus } from "lucide-react";
import { toast } from "sonner";

import {
  approveInviteSignup,
  authBootstrap,
  createDeploymentInvite,
  deploymentInvites,
  invitesAwaitingSignup,
  revokeDeploymentInvite,
  type InviteLink,
  type IssuedInviteLink,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { ConfirmDialog, DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { InviteLinkReveal } from "@/components/app/InviteLinkReveal";
import { EmptyState } from "@/components/layout/EmptyState";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { isImeKeystroke } from "@/lib/shortcuts";
import { relativeTime } from "@/lib/time";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

const INVITES_KEY = ["admin", "deployment-invites"] as const;
const AWAITING_KEY = ["admin", "invites-awaiting-signup"] as const;

/**
 * 邀请(ADR 0054):关掉自助注册之后,新成员凭邀请进来。
 *
 * - **不带工作区的邀请**:只进这台部署(此前的「邀请码」,升级前发出去的那些也在这里,照样用到过期,D50)。对方注册完
 *   自己建工作区,或者再被人拉进去;
 * - **等你放行**:工作区管理员发的邀请链接只管进工作区;要让还没账号的人也能凭它注册,得部署管理员点头(D48)。
 *
 * 链接原文只在生成的那一次给(库里只有哈希),列表里认它靠末尾几位。**开放注册时不摆发邀请的按钮** —— 摆一个用不上的
 * 「生成」,等于让人以为"不发邀请别人就进不来",而实际上谁都进得来。
 */
export function InvitesSection({ onOpenDeployment }: { onOpenDeployment: () => void }) {
  const t = useI18n();
  const bootstrap = useQuery({ queryKey: ["auth-bootstrap"], queryFn: authBootstrap });
  const inviteOnly = bootstrap.data?.open_registration === false;
  const invites = useQuery({ queryKey: INVITES_KEY, queryFn: deploymentInvites, retry: false, enabled: inviteOnly });
  const awaiting = useQuery({ queryKey: AWAITING_KEY, queryFn: invitesAwaitingSignup, retry: false, enabled: inviteOnly });
  const [creating, setCreating] = React.useState(false);
  const rows = invites.data ?? [];
  //: 发错了人、消息被转走了:作废还没用过的那张(体检 UM-09)。
  const qc = useQueryClient();
  const [revoking, setRevoking] = React.useState<InviteLink | null>(null);
  const revoke = useMutation({
    mutationFn: (link: InviteLink) => revokeDeploymentInvite(link.id),
    onSuccess: () => {
      toast.success(t("deployInviteRevoked"));
      void qc.invalidateQueries({ queryKey: INVITES_KEY });
    },
    onError: (error: Error) => toast.error(error.message),
    onSettled: () => setRevoking(null),
  });

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
      {inviteOnly && <AwaitingSignup links={awaiting.data ?? []} />}
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
          rows.map((link) => <InviteRow key={link.id} link={link} onRevoke={() => setRevoking(link)} />)
        )}
      </div>
      <InviteDialog open={creating} onClose={() => setCreating(false)} />
      <ConfirmDialog
        open={revoking !== null}
        title={t("deployInviteRevoke")}
        body={t("deployInviteRevokeConfirm")}
        confirmLabel={t("deployInviteRevoke")}
        onCancel={() => setRevoking(null)}
        pending={revoke.isPending}
        onConfirm={() => revoking && revoke.mutate(revoking)}
      />
    </AdminSection>
  );
}

function InviteRow({ link, onRevoke }: { link: InviteLink; onRevoke: () => void }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const open = link.state === "open";
  const stateLabel: Record<string, string> = {
    open: t("deployInviteOpen"),
    used: t("deployInviteUsed"),
    expired: t("deployInviteExpired"),
    revoked: t("deployInviteRevokedBadge"),
  };
  return (
    <AdminRow
      label={<code data-deploy-invite={link.id} className="timecode font-normal">··{link.code_hint}</code>}
      description={
        (link.note || open) && <>
          {/* 备注是管理员自己写的数据,按行内 markdown 渲染(和别处数据文本同一个规矩)。 */}
          {link.note && <InlineMarkdown text={link.note} links={false} />}
          {link.note && open && " · "}
          {open && t("deployInviteExpires").replace("{t}", relativeTime(link.expires_at, locale))}
        </>
      }
    >
      <Badge variant={open ? "outline" : "secondary"}>{stateLabel[link.state] ?? link.state}</Badge>
      {/* 用过、过期的没有「作废」,但那一格照样占着 —— 否则几行的状态标签对不齐。 */}
      {open ? (
        <IconButton label={t("deployInviteRevoke")} onClick={onRevoke}>
          <Ban />
        </IconButton>
      ) : (
        <span aria-hidden className="w-8" />
      )}
    </AdminRow>
  );
}

/** 工作区管理员请你放行的邀请链接:放行之后,还没账号的人也能凭它注册、直接进那个工作区。 */
function AwaitingSignup({ links }: { links: InviteLink[] }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const approve = useMutation({
    mutationFn: (link: InviteLink) => approveInviteSignup(link.id),
    onSuccess: () => {
      toast.success(t("deployInviteApproved"));
      void qc.invalidateQueries({ queryKey: AWAITING_KEY });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  if (links.length === 0) return null;
  return (
    <div data-invites-awaiting-signup="" className={ADMIN_CARD}>
      {links.map((link) => (
        <AdminRow
          key={link.id}
          label={t("deployInviteAwaitingLabel").replace("{name}", link.created_by_name)}
          description={t("deployInviteAwaitingDesc")
            .replace("{hint}", link.code_hint)
            .replace("{role}", t(`role_${link.role}` as never))
            .replace("{t}", relativeTime(link.expires_at, locale))}
        >
          <Button
            size="sm"
            variant="outline"
            loading={approve.isPending && approve.variables?.id === link.id}
            onClick={() => approve.mutate(link)}
          >
            <Check size={13} /> {t("deployInviteApprove")}
          </Button>
        </AdminRow>
      ))}
    </div>
  );
}

/** 生成一张不带工作区的邀请。备注只给管理员自己看;生成之后链接当场给出(只这一次)。 */
function InviteDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [note, setNote] = React.useState("");
  const [issued, setIssued] = React.useState<IssuedInviteLink | null>(null);
  React.useEffect(() => {
    if (open) {
      setNote("");
      setIssued(null);
    }
  }, [open]);
  const create = useMutation({
    mutationFn: () => createDeploymentInvite(note),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: INVITES_KEY });
      setIssued(result);
    },
    onError: (error: Error) => toast.error(error.message),
  });
  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && !create.isPending && onClose()}
      title={t("deployInviteNew")}
      footer={
        issued ? (
          <Button onClick={onClose}>{t("close")}</Button>
        ) : (
          <>
            <Button variant="outline" disabled={create.isPending} onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button loading={create.isPending} onClick={() => create.mutate()}>
              {t("deployInviteCreate")}
            </Button>
          </>
        )
      }
    >
      {issued ? (
        <InviteLinkReveal code={issued.code} webUrl={issued.web_url} />
      ) : (
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
      )}
    </ModalShell>
  );
}
