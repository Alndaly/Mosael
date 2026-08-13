import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, ExternalLink, Globe, LogIn, Plus, RefreshCcw, Trash2, Users, Users2 } from "lucide-react";
import { toast } from "sonner";

import {
  createBrowserProfile,
  deleteBrowserProfile,
  deletePublishAccount,
  listBrowserProfiles,
  listPublishPlatforms,
  patchPublishAccount,
  recheckPublishAccount,
  setResourceShared,
  updateBrowserProfile,
  type BrowserProfile,
  type Workspace,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, DIALOG_FIELD, ModalShell, RenameDialog } from "@/components/app/modals";
import { AddAccountDialog } from "@/features/publish/AddAccountDialog";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

// 过渡态:后台复检/登录在改登录态时轮询把徽标拉回真实值。
const TRANSITIONAL = new Set(["checking", "unknown"]);

/** 浏览器池:所有持久登录身份(BrowserProfile)一屏管全。发布账号 = 挂平台的档案,复用其登录/复检;
 *  通用档案任意站点复用(工作流/智能体)。账号矩阵从发布页抽离到这里。 */
export function BrowserPoolView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const [creating, setCreating] = React.useState(false);
  const [addingAccount, setAddingAccount] = React.useState(false);
  const [renaming, setRenaming] = React.useState<BrowserProfile | null>(null);
  const [proxyEditing, setProxyEditing] = React.useState<BrowserProfile | null>(null);
  const [removing, setRemoving] = React.useState<BrowserProfile | null>(null);
  const [loginFor, setLoginFor] = React.useState<BrowserProfile | null>(null);

  const platforms = useQuery({ queryKey: ["publish-platforms"], queryFn: listPublishPlatforms });
  const profiles = useQuery({
    queryKey: ["browser-profiles", workspace.id],
    queryFn: () => listBrowserProfiles(workspace.id),
    refetchInterval: (query) => {
      const data = (query.state.data ?? []) as BrowserProfile[];
      return data.some((p) => p.platform && TRANSITIONAL.has(p.binding_status ?? "")) ? 4000 : false;
    },
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["browser-profiles", workspace.id] });
    void qc.invalidateQueries({ queryKey: ["publish-accounts", workspace.id] });
  };

  const create = useMutation({
    mutationFn: (body: { name: string; proxy: string | null }) =>
      createBrowserProfile({ workspace_id: workspace.id, name: body.name, proxy: body.proxy }),
    onSuccess: () => {
      setCreating(false);
      refresh();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  // 发布账号(bound)的字段以 publish account 为准(worker 读它);同时同步档案,避免池页显示漂移。
  const patchName = useMutation({
    mutationFn: async ({ p, name }: { p: BrowserProfile; name: string }) => {
      if (p.bound_account_id) await patchPublishAccount(p.bound_account_id, { name });
      await updateBrowserProfile(p.id, { name });
    },
    onSuccess: () => {
      setRenaming(null);
      refresh();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const patchProxy = useMutation({
    mutationFn: async ({ p, proxy }: { p: BrowserProfile; proxy: string | null }) => {
      if (p.bound_account_id) await patchPublishAccount(p.bound_account_id, { proxy });
      await updateBrowserProfile(p.id, { proxy });
    },
    onSuccess: () => {
      setProxyEditing(null);
      refresh();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const setEnabled = useMutation({
    mutationFn: async ({ p, enabled }: { p: BrowserProfile; enabled: boolean }) => {
      if (p.bound_account_id) await patchPublishAccount(p.bound_account_id, { enabled });
      await updateBrowserProfile(p.id, { enabled });
    },
    onSuccess: refresh,
    onError: (e: Error) => toast.error(e.message),
  });
  // 共享的是**这个登录身份**:发布账号和它的浏览器档案会一起动(耦合在后端 domain/sharing 里,
  // 这里只按卡片实际代表的那一类发一次请求)。
  const share = useMutation({
    mutationFn: ({ p, shared }: { p: BrowserProfile; shared: boolean }) =>
      p.bound_account_id
        ? setResourceShared("publish_account", p.bound_account_id, workspace.id, shared)
        : setResourceShared("browser_profile", p.id, workspace.id, shared),
    onSuccess: refresh,
  });

  const recheck = useMutation({
    mutationFn: (accountId: string) => recheckPublishAccount(accountId),
    onSuccess: refresh,
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: async (p: BrowserProfile) => {
      if (p.bound_account_id) await deletePublishAccount(p.bound_account_id); // 级联删发布任务;解绑后档案可删
      await deleteBrowserProfile(p.id);
    },
    onSuccess: () => {
      setRemoving(null);
      refresh();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const login = (p: BrowserProfile) => {
    if (p.bound_account_id && p.platform) {
      window.openStudioPublish
        ?.login(p.bound_account_id, p.platform)
        .then(() => toast.success(t("poolLoginOpened")))
        .catch((e: Error) => toast.error(e.message));
    } else if (window.openStudioBrowser?.openLogin) {
      setLoginFor(p); // 通用档案:填登录网址 → 在该档案分区开可见登录窗
    } else {
      toast.info(t("publishNeedDesktop"));
    }
  };
  // 已登录的账号点主按钮是「打开」——**不是**再登一次。openLogin 会导航到平台登录页并起
  // 十分钟登录轮询,对一个登录态好好的账号做这件事纯属倒退:平台通常把已登录的人从登录页
  // 弹走,用户看到的是一次莫名其妙的跳转,而账号还会被标成 checking。openPage 则直接亮出
  // 它的视图(有页面就恢复,没有就进创作首页),这才是「我想看看这个账号」要的东西。
  const openPage = (p: BrowserProfile) => {
    window.openStudioPublish
      ?.openPage(p.bound_account_id!, p.platform!)
      .catch((e: Error) => toast.error(e.message));
  };

  const items = profiles.data ?? [];

  return (
    <div className="grid min-h-full grid-rows-[auto_minmax(0,1fr)] gap-2 p-3">
      <div className="flex items-center gap-2">
        <h2 className="m-0 inline-flex items-center gap-1.5 text-[15px] font-semibold text-foreground">
          <Boxes size={17} /> {t("poolTitle")}
        </h2>
        <small className="text-ui-xs text-muted-foreground">{t("poolSubtitle")}</small>
        <span className="flex-1" />
        <Button variant="outline" size="sm" onClick={() => setAddingAccount(true)}>
          <Users size={14} /> {t("publishAccountAdd")}
        </Button>
        <Button size="sm" onClick={() => setCreating(true)}>
          <Plus size={14} /> {t("poolCreate")}
        </Button>
      </div>

      {profiles.isSuccess && items.length === 0 ? (
        <div className="grid place-items-center">
          <EmptyState icon={<Boxes size={22} />} title={t("poolEmptyTitle")} body={t("poolEmptyBody")} />
        </div>
      ) : (
        <div className="grid content-start gap-1.5 grid-cols-[repeat(auto-fill,minmax(240px,1fr))]">
          {profiles.isLoading &&
            items.length === 0 &&
            [0, 1, 2, 3].map((i) => (
              <div key={`sk${i}`} className="space-y-2 rounded-md border border-border bg-panel p-3" aria-hidden>
                <Skeleton className="h-4 w-1/2 rounded" />
                <Skeleton className="h-3 w-2/3 rounded" />
                <Skeleton className="h-3 w-1/3 rounded" />
              </div>
            ))}
          {items.map((p) => {
            const bound = Boolean(p.bound_account_id);
            // 「已登录」只认 bound 这一个状态:checking/unknown 是"还不知道",不能当成"能用"。
            const loggedIn = bound && p.binding_status === "bound";
            const platformLabel = (platforms.data ?? []).find((m) => m.platform === p.platform)?.label ?? p.platform;
            return (
              <ContextMenu key={p.id}>
                <ContextMenuTrigger asChild>
                  <div
                    className={cn(
                      "flex min-h-32 flex-col gap-[3px] overflow-hidden rounded-lg border border-border bg-panel p-2.5 shadow-[var(--shadow-panel)]",
                      !p.enabled && "opacity-55",
                    )}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="mr-auto text-ui-2xs font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                        {bound ? platformLabel : t("poolGeneric")}
                      </span>
                      {p.proxy && (
                        <em
                          className="inline-flex max-w-[130px] items-center gap-[3px] overflow-hidden whitespace-nowrap rounded-full bg-[color-mix(in_oklab,var(--primary)_10%,transparent)] px-1.5 text-ui-2xs not-italic text-primary"
                          title={p.proxy}
                        >
                          <Globe size={10} /> {t("publishProxyOn")}
                        </em>
                      )}
                      {p.shared && (
                        <em
                          className="rounded-full bg-secondary px-1.5 text-ui-2xs not-italic text-muted-foreground"
                          title={t("poolSharedHint")}
                        >
                          <Users2 size={10} className="inline align-[-1px]" />
                        </em>
                      )}
                      {bound && (
                        <em
                          className={cn(
                            "rounded-full bg-secondary px-1.5 text-ui-2xs not-italic text-muted-foreground",
                            p.binding_status === "bound" && "bg-[color-mix(in_srgb,#16a34a_12%,transparent)] text-[#16a34a]",
                            ["login_required", "manual_required", "permission_required"].includes(p.binding_status ?? "") &&
                              "bg-[color-mix(in_srgb,#d97706_12%,transparent)] text-[#d97706]",
                          )}
                        >
                          {t(`binding_${p.binding_status}` as never)}
                        </em>
                      )}
                    </div>
                    <strong className="truncate text-ui-md">{p.name}</strong>
                    <small className="text-ui-xs text-muted-foreground">
                      {bound
                        ? p.last_checked_at
                          ? t("publishLastChecked").replace("{t}", relativeTime(p.last_checked_at, locale))
                          : t("publishNeverChecked")
                        : p.last_used_at
                          ? t("poolLastUsed").replace("{t}", relativeTime(p.last_used_at, locale))
                          : t("poolNeverUsed")}
                    </small>
                    <small className={cn("truncate text-ui-xs text-destructive", !p.last_error && "invisible")}>
                      {p.last_error ?? " "}
                    </small>
                    <div className="mt-auto flex min-h-[33px] items-center gap-1 pt-[5px]">
                      {/* 登录态决定主按钮是什么:已登录 → 打开;其余(需登录/待人工/检测中) → 去登录。 */}
                      <Button
                        size="sm"
                        variant="outline"
                        title={window.openStudioPublish || window.openStudioBrowser?.openLogin ? undefined : t("publishNeedDesktop")}
                        disabled={bound ? !window.openStudioPublish : !window.openStudioBrowser?.openLogin}
                        onClick={() => (loggedIn ? openPage(p) : login(p))}
                      >
                        {loggedIn ? (
                          <>
                            <ExternalLink size={13} /> {t("poolOpen")}
                          </>
                        ) : (
                          <>
                            <LogIn size={13} /> {t("poolLogin")}
                          </>
                        )}
                      </Button>
                      {/* 已登录时「重新登录」退居次要动作:换号/掉线自查还需要它,但它不该是默认那一下。 */}
                      {loggedIn && (
                        <Button size="sm" variant="ghost" onClick={() => login(p)}>
                          <LogIn size={13} /> {t("poolRelogin")}
                        </Button>
                      )}
                      {bound && (
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={recheck.isPending}
                          onClick={() => recheck.mutate(p.bound_account_id!)}
                        >
                          <RefreshCcw size={13} /> {t("publishRecheck")}
                        </Button>
                      )}
                      <span className="flex-1" />
                      <Switch
                        checked={p.enabled}
                        onCheckedChange={(next) => setEnabled.mutate({ p, enabled: next })}
                        aria-label={t("publishAccountEnabled")}
                      />
                    </div>
                  </div>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem onSelect={() => setRenaming(p)}>{t("rename")}</ContextMenuItem>
                  <ContextMenuItem onSelect={() => setProxyEditing(p)}>
                    <Globe /> {t("publishProxySet")}
                  </ContextMenuItem>
                  {p.is_mine && (
                    <ContextMenuItem onSelect={() => share.mutate({ p, shared: !p.shared })}>
                      <Users2 /> {p.shared ? t("poolUnshare") : t("poolShare")}
                    </ContextMenuItem>
                  )}
                  <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setRemoving(p)}>
                    <Trash2 /> {t("delete")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            );
          })}
        </div>
      )}

      <AddAccountDialog open={addingAccount} workspace={workspace} onClose={() => setAddingAccount(false)} />
      {loginFor && <LoginUrlDialog profile={loginFor} onCancel={() => setLoginFor(null)} onDone={refresh} />}
      {creating && <CreateProfileDialog onCancel={() => setCreating(false)} onCreate={(b) => create.mutate(b)} pending={create.isPending} />}
      <RenameDialog
        open={renaming !== null}
        title={t("rename")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        onSubmit={(name) => renaming && patchName.mutate({ p: renaming, name })}
      />
      {proxyEditing && (
        <ProxyDialog
          initial={proxyEditing.proxy ?? ""}
          onCancel={() => setProxyEditing(null)}
          onSave={(proxy) => patchProxy.mutate({ p: proxyEditing, proxy })}
          pending={patchProxy.isPending}
        />
      )}
      <ConfirmDialog
        open={removing !== null}
        title={t("delete")}
        body={removing?.bound_account_id ? t("poolDeleteBoundBody") : t("poolDeleteBody")}
        onCancel={() => setRemoving(null)}
        onConfirm={() => removing && remove.mutate(removing)}
      />
    </div>
  );
}

function LoginUrlDialog({
  profile,
  onCancel,
  onDone,
}: {
  profile: BrowserProfile;
  onCancel: () => void;
  onDone: () => void;
}) {
  const t = useI18n();
  const [url, setUrl] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const open = async () => {
    let u = url.trim();
    if (!u) return;
    if (!/^https?:\/\//i.test(u)) u = `https://${u}`;
    setPending(true);
    const res = await window.openStudioBrowser?.openLogin?.({ partition: profile.partition, url: u, name: profile.name, proxy: profile.proxy });
    setPending(false);
    if (res?.ok) {
      toast.success(t("poolLoginOpened"));
      onDone();
      onCancel();
    } else {
      toast.error(res?.error ?? t("poolLoginFailed"));
    }
  };
  return (
    <ModalShell open onOpenChange={(next) => !next && onCancel()} title={t("poolLoginTitle").replace("{name}", profile.name)}>
      <div className="grid gap-2.5">
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/login"
          autoFocus
          onKeyDown={(e) => e.key === "Enter" && open()}
        />
        <small className="text-ui-xs text-muted-foreground">{t("poolLoginHint")}</small>
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={pending || !url.trim()} onClick={open}>
            {t("poolLogin")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

function CreateProfileDialog({
  onCancel,
  onCreate,
  pending,
}: {
  onCancel: () => void;
  onCreate: (body: { name: string; proxy: string | null }) => void;
  pending: boolean;
}) {
  const t = useI18n();
  const [name, setName] = React.useState("");
  const [proxy, setProxy] = React.useState("");
  return (
    <ModalShell open onOpenChange={(next) => !next && onCancel()} title={t("poolCreate")}>
      <div className="grid gap-2.5">
        <label className={DIALOG_FIELD}>
          <span>{t("poolNameLabel")}</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("poolNamePlaceholder")} autoFocus />
        </label>
        <label className={DIALOG_FIELD}>
          <span>{t("publishProxySet")}</span>
          <Input value={proxy} onChange={(e) => setProxy(e.target.value)} placeholder="socks5://host:port" />
        </label>
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={pending || !name.trim()} onClick={() => onCreate({ name: name.trim(), proxy: proxy.trim() || null })}>
            {t("poolCreate")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

function ProxyDialog({
  initial,
  onCancel,
  onSave,
  pending,
}: {
  initial: string;
  onCancel: () => void;
  onSave: (proxy: string | null) => void;
  pending: boolean;
}) {
  const t = useI18n();
  const [proxy, setProxy] = React.useState(initial);
  return (
    <ModalShell open onOpenChange={(next) => !next && onCancel()} title={t("publishProxySet")}>
      <div className="grid gap-2.5">
        <Input value={proxy} onChange={(e) => setProxy(e.target.value)} placeholder="socks5://host:port" autoFocus />
        <small className="text-ui-xs text-muted-foreground">{t("poolProxyHint")}</small>
        <div className="mt-1 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={pending} onClick={() => onSave(proxy.trim() || null)}>
            {t("save")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}
