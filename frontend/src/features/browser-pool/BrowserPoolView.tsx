import React from "react";
import { ActionMenu } from "@/components/layout/ActionMenu";
import { PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Eraser, ExternalLink, Globe, KeyRound, LogIn, LogOut, Plus, RefreshCcw, SquarePen, Trash2, Users, Users2 } from "lucide-react";
import { toast } from "sonner";

import {
  createBrowserProfile,
  deleteBrowserProfile,
  deletePublishAccount,
  listBrowserProfiles,
  listPublishPlatforms,
  patchPublishAccount,
  recheckPublishAccount,
  recordBrowserProfileOpened,
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
  const [openFor, setOpenFor] = React.useState<BrowserProfile | null>(null);
  const [signingOut, setSigningOut] = React.useState<BrowserProfile | null>(null);

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

  // 退出登录 / 清除登录数据:清掉档案分区里的 cookie 和本地存储。发布账号回到「需登录」
  // (主进程回写);通用档案没有登录态可写,只是清干净。
  const signOut = useMutation({
    mutationFn: async (p: BrowserProfile) => {
      if (p.bound_account_id && p.platform) await window.mosaelPublish!.signOut(p.bound_account_id, p.platform);
      else await window.mosaelBrowser!.clearProfile(p.partition);
    },
    onSuccess: (_, p) => {
      toast.success(p.bound_account_id ? t("poolSignedOut") : t("poolDataCleared"));
      setSigningOut(null);
      refresh();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const canSignOut = (p: BrowserProfile) =>
    p.bound_account_id ? Boolean(window.mosaelPublish?.signOut) : Boolean(window.mosaelBrowser?.clearProfile);

  /**
   * 通用档案 = 一个会一直保留的浏览器。它认不出任何站点的登录态,所以这里不谈「去登录」,
   * 只管打开 —— **回到上次停下的那一页**:视图还开着就原样亮出来(resume),视图没了(重启过)
   * 就开上次收起时记下的地址(start_url,见下面收起时那一段)。一次都没开过才问要开哪个。
   * 「打开其他网址」是唯一会导航走的入口。
   */
  const openSite = async (p: BrowserProfile, url: string, resume = false): Promise<boolean> => {
    const res = await window.mosaelBrowser?.openLogin?.({ partition: p.partition, url, name: p.name, proxy: p.proxy, resume });
    if (!res?.ok) {
      toast.error(res?.error ?? t("poolOpenFailed"));
      return false;
    }
    if (!resume) await recordBrowserProfileOpened(p.id, url).catch(() => undefined); // 记不下也不耽误已经打开的页面
    refresh();
    return true;
  };

  const login = (p: BrowserProfile) => {
    if (p.bound_account_id && p.platform) {
      window.mosaelPublish
        ?.login(p.bound_account_id, p.platform)
        .then(() => {
          toast.success(t("poolLoginOpened"));
          // **点完登录必须立刻拉一次。** 上面那条 refetchInterval 只在列表里已经有
          // checking / unknown 时才开始跑,而 openLogin 是在主进程里把状态改成 checking 的 ——
          // 客户端手上还是旧的 login_required,于是判定"没有过渡态"、一次都不轮询。
          // 结果就是登录完成后卡片纹丝不动,非要手动刷新一下才更新。
          refresh();
        })
        .catch((e: Error) => toast.error(e.message));
    } else if (window.mosaelBrowser?.openLogin) {
      if (p.start_url) void openSite(p, p.start_url, true);
      else setOpenFor(p);
    } else {
      toast.info(t("publishNeedDesktop"));
    }
  };
  // 已登录的账号点主按钮是「打开」——**不是**再登一次。openLogin 会导航到平台登录页并起
  // 十分钟登录轮询,对一个登录态好好的账号做这件事纯属倒退:平台通常把已登录的人从登录页
  // 弹走,用户看到的是一次莫名其妙的跳转,而账号还会被标成 checking。openPage 则直接亮出
  // 它的视图(有页面就恢复,没有就进创作首页),这才是「我想看看这个账号」要的东西。
  const openPage = (p: BrowserProfile) => {
    window.mosaelPublish
      ?.openPage(p.bound_account_id!, p.platform!)
      .catch((e: Error) => toast.error(e.message));
  };

  /**
   * 内嵌浏览器收起来的那一刻再拉一次。
   *
   * 登录轮询最长十分钟,而**用户通常在登完的下一秒就点了返回** —— 那时轮询要么刚写完
   * (状态已是 bound),要么被 endLogin 收成 unknown。两种都值得马上让界面看到:
   * 页面焦点事件在这里帮不上忙,内嵌视图是盖在窗口上的一层,收起它不会触发窗口 focus。
   */
  const wasVisible = React.useRef(false);
  // 收起那一刻的状态里已经没有地址了,所以一路记着最后一次「亮着」时停在哪。
  const lastShown = React.useRef<{ viewId: string | null; url?: string }>({ viewId: null });
  const itemsRef = React.useRef<BrowserProfile[]>([]);
  itemsRef.current = profiles.data ?? [];
  React.useEffect(
    () =>
      window.mosaelPublish?.onViewState((next) => {
        if (next.visible) lastShown.current = { viewId: next.accountId, url: next.url };
        if (wasVisible.current && !next.visible) {
          // 通用档案收起时记下停在哪一页 —— 下次(哪怕重启过、视图已经没了)从这里接着开。
          // 通用档案的视图 id 就是它的分区名(见 openPoolLogin)。
          const { viewId, url } = lastShown.current;
          const pool = itemsRef.current.find((one) => !one.bound_account_id && one.partition === viewId);
          if (pool && url && /^https?:\/\//i.test(url) && url !== pool.start_url) {
            void recordBrowserProfileOpened(pool.id, url).catch(() => undefined).finally(refresh);
          } else refresh();
        }
        wasVisible.current = next.visible;
      }),
    // refresh 只依赖 qc 与 workspace.id,重建监听没有意义 —— 用 ref 读最新的即可。
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workspace.id],
  );

  const items = profiles.data ?? [];

  // 空池沿用工作流空页：去掉只剩标题和重复操作的顶栏，让说明与下一步动作一起落在
  // 页面中心。这样中心按整个内容区计算，不会被一条没有内容价值的顶栏向下推。
  if (profiles.isSuccess && items.length === 0) {
    return (
      <div className={STUDIO_PAGE}>
        <PageHeading title={t("poolTitle")} description={t("poolSubtitle")} />
        <EmptyState
          icon={<Boxes size={22} />}
          title={t("poolEmptyTitle")}
          body={t("poolEmptyBody")}
          action={
            <span className="inline-flex items-center gap-2">
              <Button onClick={() => setCreating(true)}>
                <Plus size={15} /> {t("poolCreate")}
              </Button>
              <Button variant="outline" onClick={() => setAddingAccount(true)}>
                <Users size={15} /> {t("publishAccountAdd")}
              </Button>
            </span>
          }
        />
        <AddAccountDialog open={addingAccount} workspace={workspace} onClose={() => setAddingAccount(false)} />
        {creating && (
          <CreateProfileDialog
            onCancel={() => setCreating(false)}
            onCreate={(body) => create.mutate(body)}
            pending={create.isPending}
          />
        )}
      </div>
    );
  }

  return (
    <div className={STUDIO_PAGE}>
      <PageHeading title={t("poolTitle")} description={t("poolSubtitle")} count={items.length} actions={<>
        <Button variant="outline" onClick={() => setAddingAccount(true)}>
          <Users size={14} /> {t("publishAccountAdd")}
        </Button>
        <Button onClick={() => setCreating(true)}>
          <Plus size={14} /> {t("poolCreate")}
        </Button>
      </>} />

      <div className="grid content-start gap-5 grid-cols-[repeat(auto-fill,minmax(min(100%,300px),1fr))]">
        {profiles.isLoading &&
          items.length === 0 &&
          [0, 1, 2, 3].map((i) => (
            <div key={`sk${i}`} className="grid gap-2 rounded-md border border-border bg-panel p-3" aria-hidden>
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
                      "flex min-h-52 flex-col gap-3 overflow-hidden rounded-lg border border-border bg-panel p-5",
                      !p.enabled && "opacity-55",
                    )}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="mr-auto text-ui-sm font-medium text-muted-foreground">
                        {bound ? platformLabel : t("poolGeneric")}
                      </span>
                      <ActionMenu label={`${t("studioActions")}: ${p.name}`} actions={[
                        { label: t("rename"), onSelect: () => setRenaming(p) },
                        { label: t("publishProxySet"), icon: <Globe />, onSelect: () => setProxyEditing(p) },
                        ...(p.is_mine ? [{ label: p.shared ? t("poolUnshare") : t("poolShare"), icon: <Users2 />, disabled: share.isPending, onSelect: () => share.mutate({p, shared:!p.shared}) }] : []),
                        ...(canSignOut(p) && (!bound || loggedIn) ? [{ label: bound ? t("poolSignOut") : t("poolClearData"), icon: bound ? <LogOut /> : <Eraser />, onSelect: () => setSigningOut(p) }] : []),
                        { label: t("delete"), icon: <Trash2 />, destructive:true, onSelect: () => setRemoving(p) },
                      ]} />
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
                            p.binding_status === "bound" && "bg-[color-mix(in_srgb,var(--success)_12%,transparent)] text-success",
                            ["login_required", "manual_required", "permission_required"].includes(p.binding_status ?? "") &&
                              "bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] text-warning",
                          )}
                        >
                          {t(`binding_${p.binding_status}` as never)}
                        </em>
                      )}
                    </div>
                    <strong className="truncate text-ui-md font-semibold tracking-tight">{p.name}</strong>
                    <small className="text-ui-xs text-muted-foreground">
                      {bound
                        ? p.last_checked_at
                          ? t("publishLastChecked").replace("{t}", relativeTime(p.last_checked_at, locale))
                          : t("publishNeverChecked")
                        : [
                            p.last_used_at ? t("poolLastUsed").replace("{t}", relativeTime(p.last_used_at, locale)) : t("poolNeverUsed"),
                            p.start_url && hostOf(p.start_url),
                          ].filter(Boolean).join(" · ")}
                    </small>
                    <small className={cn("truncate text-ui-xs text-destructive", !p.last_error && "invisible")}>
                      {p.last_error ?? " "}
                    </small>
                    {/* flex-wrap:同样三个按钮,中文「打开/重新登录/复检」很短,英文 Open / Log in again /
                        Recheck 就顶穿一张卡的宽度。收字号治不好:三个带文字的按钮加一个开关,
                        在一张 ~276px 的卡里**任何语言都放不下**,中文只是勉强擦过去而已。
                        所以次要动作一律图标化 —— 它们本就是 ghost,标签退到 title/aria 上,
                        宽度从此与语言无关。 */}
                    <div className="mt-auto flex min-h-11 items-center gap-2 border-t border-border pt-4">
                      {/* 登录态决定主按钮是什么:已登录 → 打开;其余(需登录/待人工/检测中) → 去登录。 */}
                      <Button
                        size="sm"
                        variant="outline"
                        title={window.mosaelPublish || window.mosaelBrowser?.openLogin ? undefined : t("publishNeedDesktop")}
                        disabled={bound ? !window.mosaelPublish : !window.mosaelBrowser?.openLogin}
                        onClick={() => (loggedIn ? openPage(p) : login(p))}
                      >
                        {loggedIn || !bound ? (
                          <>
                            <ExternalLink size={13} /> {t("poolOpen")}
                          </>
                        ) : (
                          <>
                            <LogIn size={13} /> {t("poolLogin")}
                          </>
                        )}
                      </Button>
                      {/* 通用档案记得上次的网址,主按钮就直接接着开;要换一个站点走这里。 */}
                      {!bound && p.start_url && (
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          title={t("poolOpenOther")}
                          aria-label={t("poolOpenOther")}
                          disabled={!window.mosaelBrowser?.openLogin}
                          onClick={() => setOpenFor(p)}
                        >
                          <SquarePen />
                        </Button>
                      )}
                      {/* 已登录时「重新登录」退居次要动作:换号/掉线自查还需要它,但它不该是默认那一下。 */}
                      {loggedIn && (
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          title={t("poolRelogin")}
                          aria-label={t("poolRelogin")}
                          onClick={() => login(p)}
                        >
                          {/* 不用 LogIn:那枚「箭头进门」被读成了退出登录(线上有人点它想登出)。 */}
                          <KeyRound />
                        </Button>
                      )}
                      {bound && (
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          loading={recheck.isPending}
                          title={t("publishRecheck")}
                          aria-label={t("publishRecheck")}
                          onClick={() => recheck.mutate(p.bound_account_id!)}
                        >
                          <RefreshCcw />
                        </Button>
                      )}
                      <span className="flex-1" />
                      {/* 开关控制的是「智能体/发布还能不能用这个账号」—— 光一个无字开关猜不出来,
                          把作用写在悬停里(卡上没地方常驻一行说明)。 */}
                      <span title={t("publishAccountEnabledHint")}>
                        <Switch
                          checked={p.enabled}
                          onCheckedChange={(next) => setEnabled.mutate({ p, enabled: next })}
                          aria-label={t("publishAccountEnabled")}
                        />
                      </span>
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
                  {canSignOut(p) && (!bound || loggedIn) && (
                    <ContextMenuItem onSelect={() => setSigningOut(p)}>
                      {bound ? <LogOut /> : <Eraser />} {bound ? t("poolSignOut") : t("poolClearData")}
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

      <AddAccountDialog open={addingAccount} workspace={workspace} onClose={() => setAddingAccount(false)} />
      {openFor && <OpenSiteDialog profile={openFor} onCancel={() => setOpenFor(null)} onOpen={(url) => openSite(openFor, url)} />}
      <ConfirmDialog
        open={signingOut !== null}
        title={signingOut?.bound_account_id ? t("poolSignOut") : t("poolClearData")}
        body={signingOut?.bound_account_id ? t("poolSignOutBody") : t("poolClearDataBody")}
        onCancel={() => setSigningOut(null)}
        pending={signOut.isPending}
        onConfirm={() => signingOut && signOut.mutate(signingOut)}
      />
      {creating && <CreateProfileDialog onCancel={() => setCreating(false)} onCreate={(b) => create.mutate(b)} pending={create.isPending} />}
      <RenameDialog
        open={renaming !== null}
        title={t("rename")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        pending={patchName.isPending}
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
        pending={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
      />
    </div>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function OpenSiteDialog({
  profile,
  onCancel,
  onOpen,
}: {
  profile: BrowserProfile;
  onCancel: () => void;
  onOpen: (url: string) => Promise<boolean>;
}) {
  const t = useI18n();
  const [url, setUrl] = React.useState(profile.start_url ?? "");
  const [pending, setPending] = React.useState(false);
  const open = async () => {
    let u = url.trim();
    if (!u) return;
    if (!/^https?:\/\//i.test(u)) u = `https://${u}`;
    setPending(true);
    const ok = await onOpen(u);
    setPending(false);
    if (ok) onCancel();
  };
  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && onCancel()}
      title={t("poolOpenTitle").replace("{name}", profile.name)}
      footer={
        <>
          <Button variant="outline" size="sm" onClick={onCancel}>{t("cancel")}</Button>
          <Button size="sm" disabled={pending || !url.trim()} onClick={open}>{t("poolOpen")}</Button>
        </>
      }
    >
      <div className="grid gap-2.5">
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com"
          autoFocus
          onKeyDown={(e) => e.key === "Enter" && open()}
        />
        <small className="text-ui-xs text-muted-foreground">{t("poolOpenHint")}</small>
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
    <ModalShell
      open
      onOpenChange={(next) => !next && onCancel()}
      title={t("poolCreate")}
      footer={
        <>
          <Button variant="outline" size="sm" onClick={onCancel}>{t("cancel")}</Button>
          <Button size="sm" disabled={pending || !name.trim()} onClick={() => onCreate({ name: name.trim(), proxy: proxy.trim() || null })}>{t("poolCreate")}</Button>
        </>
      }
    >
      <div className="grid gap-2.5">
        <label className={DIALOG_FIELD}>
          <span>{t("poolNameLabel")}</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("poolNamePlaceholder")} autoFocus />
        </label>
        <label className={DIALOG_FIELD}>
          <span>{t("publishProxySet")}</span>
          <Input value={proxy} onChange={(e) => setProxy(e.target.value)} placeholder="socks5://host:port" />
        </label>
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
    <ModalShell
      open
      onOpenChange={(next) => !next && onCancel()}
      title={t("publishProxySet")}
      footer={
        <>
          <Button variant="outline" size="sm" onClick={onCancel}>{t("cancel")}</Button>
          <Button size="sm" disabled={pending} onClick={() => onSave(proxy.trim() || null)}>{t("save")}</Button>
        </>
      }
    >
      <div className="grid gap-2.5">
        <Input value={proxy} onChange={(e) => setProxy(e.target.value)} placeholder="socks5://host:port" autoFocus />
        <small className="text-ui-xs text-muted-foreground">{t("poolProxyHint")}</small>
      </div>
    </ModalShell>
  );
}
