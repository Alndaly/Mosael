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
  addMember,
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
        <div className="team-ws">
          <div className="team-ws-meta">
            <span className="team-ws-name">{workspace.name}</span>
            <Badge variant="outline">{roleLabel(myRole)}</Badge>
          </div>
          <div className="team-ws-actions">
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
        <div className="team-members">
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
          <AddMemberForm
            onAdd={async (body) => {
              await addMember(wid, body);
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
    <div className="team-member">
      <div className="team-member-id">
        <span className="team-avatar" aria-hidden>
          {memberName.slice(0, 1).toUpperCase()}
        </span>
        <span className="team-member-name">{memberName}</span>
        {memberName !== member.username && <span className="team-member-account">@{member.username}</span>}
        {isSelf && <Badge variant="secondary">{t("teamYou")}</Badge>}
      </div>
      <div className="team-member-actions">
        {canEditRole ? (
          <Select value={member.role} onValueChange={onRole}>
            <SelectTrigger className="team-role-trigger">
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
            <PopoverContent className="team-perms" align="end">
              <div className="team-perms-head">
                <ShieldCheck size={13} /> {t("teamPermsFor").replace("{name}", member.username)}
              </div>
              {permKeys.map((perm) => (
                <label className="team-perm-row" key={perm}>
                  <span className="team-perm-label">
                    <span className="team-perm-icon">{PERM_ICONS[perm] ?? <ShieldCheck size={13} />}</span>
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
              <p className="team-perms-hint">{t("teamPermsHint")}</p>
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

function AddMemberForm({ onAdd }: { onAdd: (body: { username: string; password: string; role: string }) => Promise<void> }) {
  const t = useI18n();
  const schema = React.useMemo(
    () =>
      z.object({
        username: z.string().min(2, t("teamUsernameShort")),
        password: z.string().min(4, t("teamPasswordShort")),
        role: z.string(),
      }),
    [t],
  );
  const form = useForm<{ username: string; password: string; role: string }>({
    resolver: zodResolver(schema),
    defaultValues: { username: "", password: "", role: "editor" },
  });
  const submit = form.handleSubmit(async (values) => {
    try {
      await onAdd(values);
      toast.success(t("teamMemberAdded").replace("{name}", values.username));
      form.reset({ username: "", password: "", role: "editor" });
    } catch (error) {
      form.setError("username", { message: (error as Error).message });
    }
  });

  return (
    <Form {...form}>
      <form className="team-add-form" onSubmit={submit} noValidate>
        <div className="team-add-head">
          <UserPlus size={14} /> {t("teamAddMember")}
        </div>
        <div className="team-add-grid">
          <FormField
            control={form.control}
            name="username"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t("teamUsername")}</FormLabel>
                <FormControl>
                  <Input autoComplete="off" {...field} />
                </FormControl>
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t("teamInitialPassword")}</FormLabel>
                <FormControl>
                  <Input type="password" autoComplete="new-password" {...field} />
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
                <FormControl>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ASSIGNABLE.map((role) => (
                        <SelectItem key={role} value={role}>
                          {t(`role_${role}` as never) as string}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormControl>
              </FormItem>
            )}
          />
        </div>
        <div className="team-add-actions">
          <Button type="submit" size="sm" disabled={form.formState.isSubmitting}>
            <UserPlus size={13} /> {t("teamAddMember")}
          </Button>
          <span className="team-add-hint">{t("teamAddHint")}</span>
        </div>
      </form>
    </Form>
  );
}
