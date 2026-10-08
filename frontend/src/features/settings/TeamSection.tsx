import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Clock,
  LogOut,
  Pencil,
  Trash2,
  UserPlus,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  inviteMember,
  listActivity,
  listMembers,
  removeMember,
  revokeInvitation,
  sentInvitations,
  setMemberRole,
  type Workspace,
  type WorkspaceMember,
  type ActivityEvent,
  type WorkspaceInvitation,
} from "@/api/client";
import { workspaceKeys } from "@/api/queryKeys";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsBlock, SettingsBlockTitle, SettingsGroup, SettingsList, SettingsListBlock, SettingsListItem } from "@/components/settings/settings-layout";
import { atLeast, workspaceDeleteBlockedReason, workspaceMenuState } from "@/components/layout/workspaceMenu";
import { DeleteWorkspaceDialog } from "@/components/layout/DeleteWorkspaceDialog";
import { relativeTime } from "@/lib/time";
import { useDeleteWorkspace, useRenameWorkspace, useWorkspaces } from "@/lib/workspaces";

const ASSIGNABLE = ["admin", "editor", "viewer"] as const;
const ACTIVITY_LABELS: Record<string, string> = {
  "board.created": "activity_board_created",
  "board.updated": "activity_board_updated",
  "board.renamed": "activity_board_renamed",
  "board.deleted": "activity_board_deleted",
  "workflow.revision_created": "activity_workflow_revision_created",
  "sequence.operation": "activity_sequence_operation",
  "job.created": "activity_job_created",
  "comment.created": "activity_comment_created",
  "review.requested": "activity_review_requested",
  "review.approved": "activity_review_approved",
  "review.changes_requested": "activity_review_changes_requested",
  "review.cancelled": "activity_review_cancelled",
};
const ACTIVITY_SUBJECT_LABELS: Record<string, string> = {
  board: "activitySubject_board",
  workflow: "activitySubject_workflow",
  sequence: "activitySubject_sequence",
  asset: "activitySubject_asset",
  job: "activitySubject_job",
};

export function TeamSection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const { user } = useAuth();
  const wid = workspace.id;
  const key = ["members", wid];
  const members = useQuery({ queryKey: key, queryFn: () => listMembers(wid) });
  const activity = useQuery({ queryKey: ["activity", wid], queryFn: () => listActivity(wid) });
  const invalidate = () => void qc.invalidateQueries({ queryKey: key });
  const sentKey = ["sent-invitations", wid];
  const onErr = (error: Error) => toast.error(error.message);
  const [renameOpen, setRenameOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);

  const myRole = members.data?.my_role ?? workspace.role ?? "viewer";
  const canManage = atLeast(myRole, "admin");
  const isOwner = myRole === "owner";
  //: 发出去、还没应答的邀请列在成员下面,能撤回 —— 此前发出去就看不见了,邀错了人只能等对方拒绝(体检 UM-07)。
  //: 只有能发邀请的人看得到(和后端同一道闸)。
  const sent = useQuery({ queryKey: sentKey, queryFn: () => sentInvitations(wid), enabled: canManage });
  const [revoking, setRevoking] = React.useState<WorkspaceInvitation | null>(null);
  const revokeMut = useMutation({
    mutationFn: (invitation: WorkspaceInvitation) => revokeInvitation(wid, invitation.id),
    onSuccess: (_, invitation) => {
      toast.success(t("teamInviteRevoked").replace("{name}", invitation.invitee_name));
      void qc.invalidateQueries({ queryKey: sentKey });
    },
    onSettled: () => setRevoking(null),
  });
  //: 改名 / 删除工作区的门槛和切换器同一份(workspaceMenuState):包括「只剩一个不许删」。
  //: 权限不够的直接不摆;只剩一个的摆出来但灰掉,并说原因 —— 他有权限,只是现在不能删。
  const workspaces = useWorkspaces();
  const gate = workspaceMenuState(myRole, workspaces.data?.length ?? 0);
  const deleteReason = workspaceDeleteBlockedReason(gate);
  const roleLabel = (role: string) => t(`role_${role}` as never) as string;

  const roleMut = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) => setMemberRole(wid, userId, role),
    onSuccess: invalidate,
    onError: onErr,
  });
  const removeMut = useMutation({
    mutationFn: (userId: string) => removeMember(wid, userId),
    onSuccess: () => {
      invalidate();
      void qc.invalidateQueries({ queryKey: workspaceKeys.all() });
    },
    onError: onErr,
  });
  //: 改名、删除和切换器共用 lib/workspaces 那一份;删的若是当前工作区,WorkspaceGate 自己落到下一个。
  const renameMut = useRenameWorkspace({ onSettled: () => setRenameOpen(false) });
  const deleteMut = useDeleteWorkspace({ onSettled: () => setDeleteOpen(false) });

  return (
    <SettingsGroup title={t("teamTitle")} description={t("teamDesc")}>
      <SettingsBlock>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-[15px] font-bold text-primary" aria-hidden>
              {workspace.name.slice(0, 1).toUpperCase()}
            </span>
            <div className="grid min-w-0 gap-0.5">
              <div className="flex min-w-0 items-center gap-2">
                <Truncate className="text-ui-md font-[600]">{workspace.name}</Truncate>
                <Badge variant="outline">{roleLabel(myRole)}</Badge>
              </div>
              <span className="text-ui-xs text-muted-foreground">
                {t("workspaceMemberCount").replace("{n}", String(members.data?.members.length ?? "…"))}
              </span>
            </div>
          </div>
          <div className="flex shrink-0 gap-1.5">
            {gate.renameBlockedBy !== "role" && (
              <Button variant="outline" size="sm" onClick={() => setRenameOpen(true)}>
                <Pencil size={13} /> {t("rename")}
              </Button>
            )}
            {gate.deleteBlockedBy !== "role" && (
              <Hint disabledReason={gate.deleteDisabled && deleteReason ? t(deleteReason) : undefined}>
              <Button
                variant="outline"
                size="sm"
                className="text-destructive hover:text-destructive"
                disabled={gate.deleteDisabled}
                onClick={() => setDeleteOpen(true)}
              >
                <Trash2 size={13} /> {t("deleteWorkspace")}
              </Button>
              </Hint>
            )}
          </div>
        </div>
      </SettingsBlock>

      <SettingsBlock>
        <SettingsBlockTitle>
          <Clock size={15} /> {t("teamActivity")}
        </SettingsBlockTitle>
        <SettingsList scrollable>
          {(activity.data ?? []).slice(0, 20).map((event) => (
            <ActivityRow key={event.id} event={event} />
          ))}
          {activity.isSuccess && activity.data.length === 0 && (
            <div className="px-3 py-5 text-center text-ui-sm text-muted-foreground">{t("teamActivityEmpty")}</div>
          )}
        </SettingsList>
      </SettingsBlock>

      <SettingsListBlock>
        {members.data?.members.map((m) => (
          <MemberRow
            key={m.user_id}
            member={m}
            canManage={canManage}
            isOwner={isOwner}
            selfId={user?.id}
            roleLabel={roleLabel}
            onRole={(role) => roleMut.mutate({ userId: m.user_id, role })}
            onRemove={() => removeMut.mutate(m.user_id)}
            removing={removeMut.isPending && removeMut.variables === m.user_id}
            workspaceName={workspace.name}
          />
        ))}
        {canManage && (sent.data?.invitations ?? []).map((invitation) => (
          <PendingInvitationRow
            key={invitation.id}
            invitation={invitation}
            roleLabel={roleLabel}
            onRevoke={() => setRevoking(invitation)}
          />
        ))}
      </SettingsListBlock>

      {canManage && (
        <SettingsBlock>
          <InviteMemberForm
            onInvite={async (body) => {
              await inviteMember(wid, body);
              invalidate();
              void qc.invalidateQueries({ queryKey: sentKey });
            }}
          />
        </SettingsBlock>
      )}

      <ConfirmDialog
        open={revoking !== null}
        title={t("teamInviteRevoke")}
        body={t("teamInviteRevokeConfirm").replace("{name}", revoking?.invitee_name ?? "")}
        confirmLabel={t("teamInviteRevoke")}
        onCancel={() => setRevoking(null)}
        pending={revokeMut.isPending}
        onConfirm={() => revoking && revokeMut.mutate(revoking)}
      />
      <RenameDialog
        open={renameOpen}
        title={t("renameWorkspace")}
        initialValue={workspace.name}
        onCancel={() => setRenameOpen(false)}
        pending={renameMut.isPending}
        onSubmit={(name) => renameMut.mutate({ id: wid, name })}
      />
      <DeleteWorkspaceDialog
        workspace={deleteOpen ? workspace : null}
        onCancel={() => setDeleteOpen(false)}
        pending={deleteMut.isPending}
        onConfirm={() => deleteMut.mutate(wid)}
      />
    </SettingsGroup>
  );
}

function ActivityRow({ event }: { event: ActivityEvent }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const actor = event.actor?.display_name || event.actor?.username || t("teamSystemActor");
  const actionKey = ACTIVITY_LABELS[event.action];
  const summary = actionKey ? t(actionKey as never) : event.summary;
  const subjectKey = ACTIVITY_SUBJECT_LABELS[event.subject_type];
  const subject = subjectKey ? t(subjectKey as never) : event.subject_type;
  return (
    <SettingsListItem className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <Truncate as="div" className="text-ui-sm"><span className="font-semibold">{actor}</span> {summary}</Truncate>
        <Truncate as="div" className="mt-0.5 text-ui-xs text-muted-foreground">{subject} · {event.subject_id}</Truncate>
      </div>
      <span className="shrink-0 text-ui-xs text-muted-foreground">{relativeTime(event.created_at, locale)}</span>
    </SettingsListItem>
  );
}

function MemberRow({
  member,
  canManage,
  isOwner,
  selfId,
  roleLabel,
  onRole,
  onRemove,
  removing,
  workspaceName,
}: {
  member: WorkspaceMember;
  canManage: boolean;
  isOwner: boolean;
  selfId?: string;
  roleLabel: (role: string) => string;
  onRole: (role: string) => void;
  onRemove: () => void;
  /** 移除 / 退出正在进行 —— 确认框开着、确认键转圈,完成后这一行自己就没了。 */
  removing: boolean;
  /** 退出确认里说的是退出哪个工作区(此前把自己的用户名填进了「{name}」所在的工作区)。 */
  workspaceName: string;
}) {
  const t = useI18n();
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const isSelf = member.is_self || member.user_id === selfId;
  const memberName = member.display_name || member.username;
  // Only an owner may re-role an owner row; managing others needs admin+.
  const canEditRole = canManage && (member.role !== "owner" || isOwner) && !(isSelf && member.role === "owner");
  const canRemove = (isSelf || canManage) && member.role !== "owner";

  return (
    <SettingsListItem className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className="inline-flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full bg-[color-mix(in_oklab,var(--primary)_16%,var(--background))] text-xs font-semibold text-primary" aria-hidden>
          {memberName.slice(0, 1).toUpperCase()}
        </span>
        <Truncate className="text-ui-md">{memberName}</Truncate>
        {memberName !== member.username && <Truncate className="text-xs text-muted-foreground">@{member.username}</Truncate>}
        {isSelf && <Badge variant="secondary">{t("teamYou")}</Badge>}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {canEditRole ? (
          <Select value={member.role} onValueChange={onRole}>
            <SelectTrigger size="sm" className="w-[116px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(isOwner ? (["owner", ...ASSIGNABLE] as const) : ASSIGNABLE).map((role) => (
                <SelectItem key={role} value={role}>
                  {roleLabel(role)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Badge variant="outline">{roleLabel(member.role)}</Badge>
        )}


        {canRemove && (
          <>
            <IconButton onClick={() => setConfirmOpen(true)} label={isSelf ? t("teamLeave") : t("teamRemove")}>
              {isSelf ? <LogOut size={14} /> : <Trash2 size={14} />}
            </IconButton>
            <ConfirmDialog
              open={confirmOpen}
              title={isSelf ? t("teamLeave") : t("teamRemove")}
              body={isSelf ? t("teamLeaveConfirm").replace("{name}", workspaceName) : t("teamRemoveConfirm").replace("{name}", memberName)}
              onCancel={() => setConfirmOpen(false)}
              pending={removing}
              onConfirm={onRemove}
            />
          </>
        )}
      </div>
    </SettingsListItem>
  );
}

/** 一条发出去、还没应答的邀请:谁、什么角色、多久前发的,能撤回。 */
function PendingInvitationRow({
  invitation,
  roleLabel,
  onRevoke,
}: {
  invitation: WorkspaceInvitation;
  roleLabel: (role: string) => string;
  onRevoke: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  return (
    <SettingsListItem data-pending-invitation={invitation.id} className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className="inline-flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border border-dashed border-border text-muted-foreground" aria-hidden>
          <Clock size={12} />
        </span>
        <Truncate className="text-ui-md text-muted-foreground">{invitation.invitee_name}</Truncate>
        <Badge variant="secondary">{t("teamInvitePending")}</Badge>
        <span className="shrink-0 text-ui-xs text-muted-foreground">
          {t("teamInviteSentAgo").replace("{t}", relativeTime(invitation.created_at, locale)).replace("{name}", invitation.inviter_name)}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <Badge variant="outline">{roleLabel(invitation.role)}</Badge>
        <IconButton onClick={onRevoke} label={t("teamInviteRevoke")}>
          <X size={14} />
        </IconButton>
      </div>
    </SettingsListItem>
  );
}

function InviteMemberForm({ onInvite }: { onInvite: (body: { username: string; role: string }) => Promise<void> }) {
  const t = useI18n();
  const schema = React.useMemo(
    () =>
      z.object({
        username: z.string().min(2, t("teamUsernameShort")),
        role: z.string(),
      }),
    [t],
  );
  const form = useForm<{ username: string; role: string }>({
    resolver: zodResolver(schema),
    defaultValues: { username: "", role: "editor" },
  });
  const submit = form.handleSubmit(async (values) => {
    try {
      await onInvite(values);
      toast.success(t("teamInviteSent").replace("{name}", values.username));
      form.reset({ username: "", role: "editor" });
    } catch (error) {
      form.setError("username", { message: (error as Error).message });
    }
  });

  return (
    <Form {...form}>
      <form className="grid gap-2.5" onSubmit={submit} noValidate>
        <div className="flex items-center gap-1.5 text-xs font-[550] text-foreground">
          <UserPlus size={14} /> {t("teamInvite")}
        </div>
        <div className="grid grid-cols-[1.6fr_0.8fr] gap-2.5 max-[720px]:grid-cols-1">
          <FormField
            control={form.control}
            name="username"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t("teamUsername")}</FormLabel>
                <FormControl>
                  <Input autoComplete="off" placeholder={t("teamInvitePlaceholder")} {...field} />
                </FormControl>
                {/* 后端按界面语言给了原因(没有这个用户名、已经是成员、已经邀请过);此前只把标签染红,一句话都没有(体检 UM-07)。 */}
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="role"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t("teamRole")}</FormLabel>
                <Select value={field.value} onValueChange={field.onChange}>
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value="admin">{t("role_admin")}</SelectItem>
                    <SelectItem value="editor">{t("role_editor")}</SelectItem>
                    <SelectItem value="viewer">{t("role_viewer")}</SelectItem>
                  </SelectContent>
                </Select>
              </FormItem>
            )}
          />
        </div>
        <div className="flex items-center gap-2.5">
          <Button type="submit" size="sm" loading={form.formState.isSubmitting}>
            <UserPlus size={13} /> {t("teamInvite")}
          </Button>
          <span className="text-ui-xs text-muted-foreground">{t("teamInviteHint")}</span>
        </div>
      </form>
    </Form>
  );
}
