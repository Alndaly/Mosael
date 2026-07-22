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
  deleteWorkspace,
  listMembers,
  removeMember,
  renameWorkspace,
  setMemberPerms,
  setMemberRole,
  type Workspace,
  type WorkspaceMember,
} from "@/api/client";
import { useAuth } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Form, FormControl, FormField, FormItem, FormLabel } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

/** Per-permission icon for the member-permissions popover (scannability). */
const PERM_ICONS: Record<string, React.ReactNode> = {
  upload: <Upload size={13} />,
  edit: <Pencil size={13} />,
  delete: <Trash2 size={13} />,
  export: <Download size={13} />,
  ai: <Sparkles size={13} />,
  credentials: <KeyRound size={13} />,
  schedule: <Clock size={13} />,
  members: <Users size={13} />,
  publish: <Send size={13} />,
};

const ROLE_RANK: Record<string, number> = { viewer: 0, editor: 1, admin: 2, owner: 3 };
const atLeast = (role: string, min: string) => (ROLE_RANK[role] ?? -1) >= ROLE_RANK[min];
const ASSIGNABLE = ["admin", "editor", "viewer"] as const;

export function TeamSection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const { user } = useAuth();
  const wid = workspace.id;
  const key = ["members", wid];
  const members = useQuery({ queryKey: key, queryFn: () => listMembers(wid) });
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
  const permMut = useMutation({
    mutationFn: ({ userId, perms }: { userId: string; perms: Record<string, boolean> }) => setMemberPerms(wid, userId, perms),
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
          <div className="flex min-w-0 items-center gap-2">
            <span className="text-[13px] font-[550]">{workspace.name}</span>
            <Badge variant="outline">{roleLabel(myRole)}</Badge>
          </div>
          <div className="flex shrink-0 gap-1.5">
            {canManage && (
              <Button variant="outline" size="sm" onClick={() => setRenameOpen(true)}>
                <Pencil size={13} /> {t("rename")}
              </Button>
            )}
            {isOwner && (
              <Button variant="outline" size="sm" onClick={() => setDeleteOpen(true)}>
                <Trash2 size={13} /> {t("deleteWorkspace")}
              </Button>
            )}
          </div>
        </div>
      </SettingsBlock>

      <SettingsBlock>
        <div className="grid gap-1.5">
          {members.data?.members.map((m) => (
            <MemberRow
              key={m.user_id}
              member={m}
              canManage={canManage}
              isOwner={isOwner}
              selfId={user?.id}
              permKeys={members.data!.perm_keys}
              roleDefaults={members.data!.role_defaults}
              roleLabel={roleLabel}
              onRole={(role) => roleMut.mutate({ userId: m.user_id, role })}
              onPerms={(perms) => permMut.mutate({ userId: m.user_id, perms })}
              onRemove={() => removeMut.mutate(m.user_id)}
            />
          ))}
        </div>
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

function MemberRow({
  member,
  canManage,
  isOwner,
  selfId,
  permKeys,
  roleDefaults,
  roleLabel,
  onRole,
  onPerms,
  onRemove,
}: {
  member: WorkspaceMember;
  canManage: boolean;
  isOwner: boolean;
  selfId?: string;
  permKeys: string[];
  roleDefaults: Record<string, Record<string, boolean>>;
  roleLabel: (role: string) => string;
  onRole: (role: string) => void;
  onPerms: (perms: Record<string, boolean>) => void;
  onRemove: () => void;
}) {
  const t = useI18n();
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const isSelf = member.is_self || member.user_id === selfId;
  const memberName = member.display_name || member.username;
  // Only an owner may re-role an owner row; managing others needs admin+.
  const canEditRole = canManage && (member.role !== "owner" || isOwner) && !(isSelf && member.role === "owner");
  const canOverride = canManage && member.role !== "owner";
  const canRemove = (isSelf || canManage) && member.role !== "owner";

  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-2.5 py-[7px]">
      <div className="flex min-w-0 items-center gap-2">
        <span className="inline-flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full bg-[color-mix(in_oklab,var(--primary)_16%,var(--background))] text-xs font-semibold text-primary" aria-hidden>
          {memberName.slice(0, 1).toUpperCase()}
        </span>
        <span className="truncate text-[13px]">{memberName}</span>
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

        {canOverride && (
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="icon" aria-label={t("teamPerms")}>
                <SlidersHorizontal size={14} />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="grid w-[270px] gap-px p-[7px]" align="end">
              <div className="mb-[5px] flex items-center gap-1.5 border-b border-border px-1.5 pb-2 pt-px text-xs font-semibold text-foreground [&_svg]:text-primary">
                <ShieldCheck size={13} /> {t("teamPermsFor").replace("{name}", member.username)}
              </div>
              {permKeys.map((perm) => (
                <label className="flex cursor-pointer items-center justify-between gap-2.5 rounded-md px-1.5 py-[5px] text-[12.5px] text-foreground transition-colors duration-100 hover:bg-secondary" key={perm}>
                  <span className="inline-flex min-w-0 items-center gap-2">
                    <span className="inline-flex text-muted-foreground">{PERM_ICONS[perm] ?? <ShieldCheck size={13} />}</span>
                    {t(`perm_${perm}` as never) as string}
                  </span>
                  <Switch
                    checked={member.perms[perm] ?? false}
                    onCheckedChange={(next) => {
                      const effective = { ...member.perms, [perm]: next };
                      // Persist only deltas from the role default (mirrors the backend model).
                      const defaults = roleDefaults[member.role] ?? {};
                      const overrides: Record<string, boolean> = {};
                      for (const p of permKeys) if (effective[p] !== defaults[p]) overrides[p] = effective[p];
                      onPerms(overrides);
                    }}
                  />
                </label>
              ))}
              <p className="mb-0 mt-1.5 border-t border-border px-1.5 pb-0 pt-[7px] text-[11px] leading-[1.45] text-muted-foreground">{t("teamPermsHint")}</p>
            </PopoverContent>
          </Popover>
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
    </div>
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
          <span className="text-[11px] text-muted-foreground">{t("teamInviteHint")}</span>
        </div>
      </form>
    </Form>
  );
}
