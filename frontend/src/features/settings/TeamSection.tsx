import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Clock,
  Download,
  KeyRound,
  LogOut,
  Pencil,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Upload,
  UserPlus,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import {
  inviteMember,
  listActivity,
  deleteWorkspace,
  listMembers,
  removeMember,
  renameWorkspace,
  setMemberRole,
  type Workspace,
  type WorkspaceMember,
  type ActivityEvent,
} from "@/api/client";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Form, FormControl, FormField, FormItem, FormLabel } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { SettingsBlock, SettingsGroup, SettingsList, SettingsListItem } from "@/features/settings/ui";
import { relativeTime } from "@/lib/time";

/** Per-permission icon for the member-permissions popover (scannability). */
const ROLE_RANK: Record<string, number> = { viewer: 0, editor: 1, admin: 2, owner: 3 };
const atLeast = (role: string, min: string) => (ROLE_RANK[role] ?? -1) >= ROLE_RANK[min];
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
  const onErr = (error: Error) => toast.error(error.message);
  const [renameOpen, setRenameOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);

  const myRole = members.data?.my_role ?? workspace.role ?? "viewer";
  const canManage = atLeast(myRole, "admin");
  const isOwner = myRole === "owner";
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
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
    onError: onErr,
  });
  const renameMut = useMutation({
    mutationFn: (name: string) => renameWorkspace(wid, name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success(t("saved"));
    },
    onError: onErr,
  });
  const deleteMut = useMutation({
    mutationFn: () => deleteWorkspace(wid),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success(t("workspaceDeleted"));
    },
    onError: onErr,
  });

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
                <span className="truncate text-ui-md font-[600]">{workspace.name}</span>
                <Badge variant="outline">{roleLabel(myRole)}</Badge>
              </div>
              <span className="text-ui-xs text-muted-foreground">
                {t("workspaceMemberCount").replace("{n}", String(members.data?.members.length ?? "…"))}
              </span>
            </div>
          </div>
          <div className="flex shrink-0 gap-1.5">
            {canManage && (
              <Button variant="outline" size="sm" onClick={() => setRenameOpen(true)}>
                <Pencil size={13} /> {t("rename")}
              </Button>
            )}
            {isOwner && (
              <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" onClick={() => setDeleteOpen(true)}>
                <Trash2 size={13} /> {t("deleteWorkspace")}
              </Button>
            )}
          </div>
        </div>
      </SettingsBlock>

      <SettingsBlock>
        <div className="mb-3 flex items-center gap-2 text-ui-md font-semibold">
          <Clock size={15} /> {t("teamActivity")}
        </div>
        <SettingsList>
          {(activity.data ?? []).slice(0, 20).map((event) => (
            <ActivityRow key={event.id} event={event} />
          ))}
          {activity.isSuccess && activity.data.length === 0 && (
            <div className="px-3 py-5 text-center text-ui-sm text-muted-foreground">{t("teamActivityEmpty")}</div>
          )}
        </SettingsList>
      </SettingsBlock>

      <SettingsBlock>
        <SettingsList>
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
            />
          ))}
        </SettingsList>
      </SettingsBlock>

      {canManage && (
        <SettingsBlock>
          <InviteMemberForm
            onInvite={async (body) => {
              await inviteMember(wid, body);
              invalidate();
            }}
          />
        </SettingsBlock>
      )}

      <RenameDialog
        open={renameOpen}
        title={t("renameWorkspace")}
        initialValue={workspace.name}
        onCancel={() => setRenameOpen(false)}
        onSubmit={(name) => {
          setRenameOpen(false);
          renameMut.mutate(name);
        }}
      />
      <ConfirmDialog
        open={deleteOpen}
        title={t("deleteWorkspace")}
        body={t("deleteWorkspaceConfirm").replace("{name}", workspace.name)}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={() => {
          setDeleteOpen(false);
          deleteMut.mutate();
        }}
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
        <div className="truncate text-ui-sm"><span className="font-semibold">{actor}</span> {summary}</div>
        <div className="mt-0.5 truncate text-ui-xs text-muted-foreground">{subject} · {event.subject_id}</div>
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
}: {
  member: WorkspaceMember;
  canManage: boolean;
  isOwner: boolean;
  selfId?: string;
  roleLabel: (role: string) => string;
  onRole: (role: string) => void;
  onRemove: () => void;
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
        <span className="truncate text-ui-md">{memberName}</span>
        {memberName !== member.username && <span className="truncate text-xs text-muted-foreground">@{member.username}</span>}
        {isSelf && <Badge variant="secondary">{t("teamYou")}</Badge>}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {canEditRole ? (
          <Select value={member.role} onValueChange={onRole}>
            <SelectTrigger className="h-[30px] w-[116px]">
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
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setConfirmOpen(true)}
              aria-label={isSelf ? t("teamLeave") : t("teamRemove")}
            >
              {isSelf ? <LogOut size={14} /> : <Trash2 size={14} />}
            </Button>
            <ConfirmDialog
              open={confirmOpen}
              title={isSelf ? t("teamLeave") : t("teamRemove")}
              body={(isSelf ? t("teamLeaveConfirm") : t("teamRemoveConfirm")).replace("{name}", member.username)}
              onCancel={() => setConfirmOpen(false)}
              onConfirm={() => {
                setConfirmOpen(false);
                onRemove();
              }}
            />
          </>
        )}
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
          <Button type="submit" size="sm" disabled={form.formState.isSubmitting}>
            <UserPlus size={13} /> {t("teamInvite")}
          </Button>
          <span className="text-ui-xs text-muted-foreground">{t("teamInviteHint")}</span>
        </div>
      </form>
    </Form>
  );
}
