"use client";

import { useState } from "react";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupLabel, SidebarHeader, SidebarInset, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Switch } from "@/components/ui/switch";
import { toast } from "@/components/ui/use-toast";
import { LocaleSwitch } from "@/components/locale-switch";
import { ThemeToggle } from "@/components/theme-toggle";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Activity, Boxes, Cable, CreditCard, LayoutDashboard, Loader2, Menu, ScrollText, Server, Users } from "lucide-react";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import {
  adminInvalidation,
  useAdminAudit,
  useAdminChannels,
  useAdminModels,
  useAdminOrders,
  useAdminOverview,
  useAdminPlans,
  useAdminPrices,
  useAdminProviders,
  useAdminUsage,
  useAdminUsers,
} from "@/lib/admin-queries";
import { queryKeys } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import {
  CloudApiError,
  cloudAdmin,
  type AdminAudit,
  type AdminChannel,
  type AdminChannelTest,
  type AdminModel,
  type AdminOrder,
  type AdminPlan,
  type AdminProvider,
  type AdminUsage,
  type AdminUser,
  type CloudUser,
} from "@/lib/cloud";

function failureText(error: unknown, copy: Messages["admin"], locale: Locale): string {
  return error instanceof CloudApiError ? error.text(locale) : copy.error;
}

function date(value: string | null, locale: Locale): string {
  return value ? new Date(value).toLocaleDateString(locale === "zh" ? "zh-CN" : "en") : "—";
}

function money(cents: number | null): string {
  return cents === null ? "—" : `¥${(cents / 100).toFixed(2)}`;
}

function roleLabel(role: string, copy: Messages["admin"]): string {
  return role === "admin" ? copy.roleAdmin : copy.roleMember;
}

function modelReasonLabel(reason: string, copy: Messages["admin"]): string {
  if (reason === "disabled") return copy.reasonDisabled;
  if (reason === "missing_price") return copy.reasonMissingPrice;
  if (reason === "missing_channel") return copy.reasonMissingChannel;
  return reason;
}

function periodLabel(period: AdminPlan["period"], copy: Messages["admin"]): string {
  if (period === "month") return copy.month;
  if (period === "quarter") return copy.quarter;
  return copy.year;
}

function orderStatusLabel(status: string, copy: Messages["admin"]): string {
  if (status === "pending") return copy.statusPending;
  if (status === "paid") return copy.statusPaid;
  if (status === "closed") return copy.statusClosed;
  return status;
}

function orderChannelLabel(channel: string, copy: Messages["admin"]): string {
  if (channel === "alipay") return copy.channelAlipay;
  if (channel === "wechat") return copy.channelWechat;
  return channel;
}

function protocolLabel(protocol: string, copy: Messages["admin"]): string {
  return protocol === "openai" ? copy.protocolOpenai : protocol;
}

function auditTargetLabel(target: string, copy: Messages["admin"]): string {
  const labels: Record<string, string> = {
    user: copy.targetUser,
    model: copy.targetModel,
    provider: copy.targetProvider,
    channel: copy.targetChannel,
    plan: copy.targetPlan,
  };
  return labels[target] ?? target;
}

function auditActionLabel(action: string, copy: Messages["admin"]): string {
  const labels: Record<string, string> = {
    "user.role": copy.auditUserRole,
    "user.reset_password": copy.auditUserResetPassword,
    "user.credits": copy.auditUserCredits,
    "user.subscribe": copy.auditUserSubscribe,
    "model.create": copy.auditModelCreate,
    "model.update": copy.auditModelUpdate,
    "model.price": copy.auditModelPrice,
    "provider.create": copy.auditProviderCreate,
    "provider.update": copy.auditProviderUpdate,
    "channel.create": copy.auditChannelCreate,
    "channel.update": copy.auditChannelUpdate,
    "plan.create": copy.auditPlanCreate,
    "plan.update": copy.auditPlanUpdate,
  };
  return labels[action] ?? action;
}

/** 管理台采用 shadcn 的标准密度（36px），不继承官网营销页的 48px 大字段。 */
function AButton({ className, loading = false, disabled, children, ...props }: React.ComponentProps<typeof Button> & { loading?: boolean }) {
  return (
    <Button {...props} disabled={loading || disabled} className={cn("h-9 rounded-md px-3 text-sm", className)}>
      {loading && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
      {children}
    </Button>
  );
}

function AInput({ className, ...props }: React.ComponentProps<typeof Input>) {
  return <Input {...props} className={cn("h-9 rounded-md border-input bg-transparent px-3 py-1 text-sm shadow-sm", className)} />;
}

function ASelectTrigger({ className, ...props }: React.ComponentProps<typeof SelectTrigger>) {
  return <SelectTrigger size="sm" {...props} className={cn("w-full rounded-md text-sm", className)} />;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
      {label}
      {children}
    </Label>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-4 grid min-h-[280px] place-items-center rounded-xl border border-dashed border-border px-6 py-10 text-center">
      <div className="grid max-w-sm gap-2">
        <span className="mx-auto grid size-10 place-items-center rounded-full bg-secondary text-muted-foreground">·</span>
        <p className="m-0 text-sm text-muted-foreground">{children}</p>
      </div>
    </div>
  );
}

const ADMIN_TABS = ["overview", "users", "providers", "models", "channels", "plans", "operations", "audit"] as const;
type AdminTab = (typeof ADMIN_TABS)[number];

function readTab(value: string | null): AdminTab {
  return ADMIN_TABS.includes(value as AdminTab) ? (value as AdminTab) : "overview";
}

export function AdminConsole({ locale, copy, viewer }: { locale: Locale; copy: Messages["admin"]; viewer: CloudUser }) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const tab = readTab(searchParams.get("tab"));
  const queryClient = useQueryClient();
  const overviewQuery = useAdminOverview();
  const usersQuery = useAdminUsers();
  const modelsQuery = useAdminModels();
  const providersQuery = useAdminProviders();
  const channelsQuery = useAdminChannels();
  const plansQuery = useAdminPlans();
  const ordersQuery = useAdminOrders();
  const usageQuery = useAdminUsage();
  const auditQuery = useAdminAudit();
  const queries = [
    overviewQuery,
    usersQuery,
    modelsQuery,
    providersQuery,
    channelsQuery,
    plansQuery,
    ordersQuery,
    usageQuery,
    auditQuery,
  ];
  const loading = queries.some((query) => query.isLoading);
  const fetching = useIsFetching({ queryKey: queryKeys.admin() }) > 0;
  const queryFailure = queries.find((query) => query.error)?.error;

  const invalidate = (...keys: readonly (readonly unknown[])[]) => {
    for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
  };
  const refresh = () => invalidate(...adminInvalidation.all);
  const selectTab = (next: string) => {
    const target = readTab(next);
    if (target === tab) return;
    const params = new URLSearchParams(searchParams.toString());
    if (target === "overview") params.delete("tab");
    else params.set("tab", target);
    const query = params.toString();
    // 把「当前在哪一页」写进地址:刷新 / 回到这一页 / 分享链接都还停在同一个分区。
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  const users = usersQuery.data ?? [];
  const models = modelsQuery.data ?? [];
  const providers = providersQuery.data ?? [];
  const channels = channelsQuery.data ?? [];
  const plans = plansQuery.data ?? [];
  const orders = ordersQuery.data ?? [];
  const usage = usageQuery.data ?? null;
  const audit = auditQuery.data ?? [];
  const overview = overviewQuery.data ?? null;
  const failure = queryFailure ? failureText(queryFailure, copy, locale) : "";
  const notifyFailure = (failure: unknown) => toast({ title: failureText(failure, copy, locale) });

  return (
    <SidebarProvider>
      <AdminSidebar tab={tab} onSelect={selectTab} copy={copy} locale={locale} viewer={viewer} />
      <SidebarInset>
        <div className="mx-auto max-w-[100rem] px-4 py-8 sm:px-6 lg:px-10">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex items-start gap-3">
              <SidebarTrigger aria-label={copy.title} className="mt-1"><Menu className="size-4" /></SidebarTrigger>
              <div>
                <p className="m-0 text-xs font-semibold tracking-[0.18em] text-muted-foreground uppercase">{copy.controlEyebrow}</p>
                <h1 className="mt-2 mb-0 font-display text-4xl font-semibold tracking-[-0.04em]">{copy.title}</h1>
                <p className="mt-2 mb-0 max-w-2xl text-sm leading-6 text-muted-foreground">{copy.lede}</p>
              </div>
            </div>
            <AButton variant="outline" onClick={refresh} loading={fetching}>{fetching ? copy.loading : copy.refresh}</AButton>
          </div>

          {failure && <div className="mt-5 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">{failure}</div>}

          <div className="mt-8">
            {tab === "overview" && (overview ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {[
                  [copy.users, overview.users],
                  [copy.admins, overview.admins],
                  [copy.subscriptions, overview.subscriptions],
                  [copy.models, overview.models],
                  [copy.providers, overview.providers],
                  [copy.channels, overview.channels],
                  [copy.orders, overview.orders],
                ].map(([label, value]) => (
                  <Card key={String(label)} className="bg-card/60 ring-border">
                    <CardHeader><CardDescription>{label}</CardDescription><CardTitle className="text-3xl">{value}</CardTitle></CardHeader>
                  </Card>
                ))}
              </div>
            ) : <Empty>{loading ? copy.loading : copy.noUsers}</Empty>)}
            {tab === "users" && <UsersPanel copy={copy} locale={locale} users={users} plans={plans} onChanged={() => invalidate(...adminInvalidation.user)} onFailure={notifyFailure} />}
            {tab === "models" && <ModelsPanel copy={copy} locale={locale} models={models} onChanged={() => invalidate(...adminInvalidation.model)} onFailure={notifyFailure} />}
            {tab === "providers" && <ProvidersPanel copy={copy} providers={providers} onChanged={() => invalidate(...adminInvalidation.provider)} onFailure={notifyFailure} />}
            {tab === "channels" && <ChannelsPanel copy={copy} models={models} providers={providers} channels={channels} onChanged={() => invalidate(...adminInvalidation.channel)} onFailure={notifyFailure} />}
            {tab === "plans" && <PlansPanel copy={copy} plans={plans} onChanged={() => invalidate(...adminInvalidation.plan)} onFailure={notifyFailure} />}
            {tab === "operations" && <OperationsPanel copy={copy} locale={locale} orders={orders} usage={usage} />}
            {tab === "audit" && <AuditPanel copy={copy} locale={locale} audit={audit} />}
          </div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}

function AdminSidebar({ tab, onSelect, copy, locale, viewer }: { tab: string; onSelect: (tab: string) => void; copy: Messages["admin"]; locale: Locale; viewer: CloudUser }) {
  const name = viewer.display_name?.trim() || viewer.handle?.trim() || viewer.email?.trim() || viewer.phone || copy.adminFallback;
  const initial = Array.from(name)[0]?.toUpperCase() ?? "A";
  const items = [
    { id: "overview", label: copy.tabOverview, icon: LayoutDashboard },
    { id: "users", label: copy.tabUsers, icon: Users },
    { id: "providers", label: copy.tabProviders, icon: Server },
    { id: "models", label: copy.tabModels, icon: Boxes },
    { id: "channels", label: copy.tabChannels, icon: Cable },
    { id: "plans", label: copy.tabPlans, icon: CreditCard },
    { id: "operations", label: copy.tabOperations, icon: Activity },
    { id: "audit", label: copy.tabAudit, icon: ScrollText },
  ];
  return (
    <Sidebar>
      <SidebarHeader>
        <div className="flex items-center gap-2">
          <span className="grid size-8 place-items-center rounded-lg bg-foreground text-sm font-bold text-background">M</span>
          <div className="grid gap-0.5">
            <strong className="text-sm font-semibold">MosaelCloud</strong>
            <span className="text-[11px] text-muted-foreground">{copy.sidebarSubtitle}</span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>{copy.sidebarWorkspace}</SidebarGroupLabel>
          <SidebarMenu>
            {items.map(({ id, label, icon: Icon }) => (
              <SidebarMenuItem key={id}>
                <SidebarMenuButton isActive={tab === id} onClick={() => onSelect(id)}>
                  <Icon className="size-4" aria-hidden />
                  {label}
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <div className="mb-3 flex items-center gap-2.5">
          <Avatar>
            <AvatarFallback>{initial}</AvatarFallback>
          </Avatar>
          <div className="grid min-w-0 flex-1 gap-0.5">
            <strong className="truncate text-xs font-semibold">{name}</strong>
            <span className="truncate text-[11px] text-muted-foreground">{viewer.email || viewer.phone || viewer.id}</span>
          </div>
          <Badge variant="secondary">{roleLabel(viewer.role || "admin", copy)}</Badge>
        </div>
        <Separator className="mb-3" />
        <div className="flex items-center justify-between gap-2">
          <LocaleSwitch locale={locale} label={copy.language} />
          <ThemeToggle label={copy.theme} />
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}

function UsersPanel({ copy, locale, users, plans, onChanged, onFailure }: {
  copy: Messages["admin"];
  locale: Locale;
  users: AdminUser[];
  plans: AdminPlan[];
  onChanged: () => void;
  onFailure: (failure: unknown) => void;
}) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<AdminUser[] | null>(null);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [searching, setSearching] = useState(false);
  const search = async () => {
    setSearching(true);
    try {
      setFound((await cloudAdmin.users(query)).users);
    } catch (failure) {
      onFailure(failure);
    } finally {
      setSearching(false);
    }
  };
  const visible = found ?? users;
  return (
    <>
      <Card className="bg-card/60 ring-border">
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <CardTitle>{copy.users}</CardTitle>
          <div className="flex min-w-0 gap-2">
            <AInput value={query} onChange={(event) => setQuery(event.target.value)} placeholder={copy.searchUsers} className="w-[min(22rem,50vw)]" />
            <AButton variant="outline" onClick={() => void search()} loading={searching}>{copy.search}</AButton>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>{copy.users}</TableHead><TableHead>{copy.role}</TableHead><TableHead>{copy.credits}</TableHead><TableHead>{copy.plan}</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {visible.map((user) => (
                <TableRow key={user.id}>
                  <TableCell><strong className="block font-medium">{user.display_name || user.handle || user.email || user.phone}</strong><span className="text-xs text-muted-foreground">{user.email || user.phone}</span></TableCell>
                  <TableCell><Badge variant={user.role === "admin" ? "default" : "secondary"}>{roleLabel(user.role, copy)}</Badge>{user.official && <Badge variant="outline" className="ml-1">{copy.official}</Badge>}</TableCell>
                  <TableCell>{user.credits}</TableCell>
                  <TableCell>{user.subscription?.name || "—"}</TableCell>
                  <TableCell className="text-right"><AButton size="sm" variant="outline" onClick={() => setSelected(user)}>{copy.edit}</AButton></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {visible.length === 0 && <Empty>{copy.noUsers}</Empty>}
        </CardContent>
      </Card>
      {selected && (
        <UserDialog
          key={selected.id}
          copy={copy}
          locale={locale}
          user={selected}
          plans={plans}
          onClose={() => setSelected(null)}
          onUser={(next) => { setSelected(next); onChanged(); }}
          onFailure={onFailure}
        />
      )}
    </>
  );
}

function UserDialog({ copy, locale, user, plans, onClose, onUser, onFailure }: {
  copy: Messages["admin"];
  locale: Locale;
  user: AdminUser;
  plans: AdminPlan[];
  onClose: () => void;
  onUser: (user: AdminUser) => void;
  onFailure: (failure: unknown) => void;
}) {
  const [current, setCurrent] = useState(user);
  const [credits, setCredits] = useState("100");
  const [days, setDays] = useState("30");
  const [note, setNote] = useState("");
  const [plan, setPlan] = useState(plans[0]?.slug ?? "");
  const [temporary, setTemporary] = useState("");
  const [busy, setBusy] = useState("");
  const update = (next: AdminUser) => { setCurrent(next); onUser(next); };
  const role = async () => {
    setBusy("role");
    try { update((await cloudAdmin.setRole(current.id, current.role === "admin" ? "member" : "admin")).user); }
    catch (failure) { onFailure(failure); } finally { setBusy(""); }
  };
  const reset = async () => {
    setBusy("reset");
    try { setTemporary((await cloudAdmin.resetPassword(current.id)).temporary_password); }
    catch (failure) { onFailure(failure); } finally { setBusy(""); }
  };
  const gift = async () => {
    setBusy("gift");
    try { update((await cloudAdmin.gift(current.id, Number(credits), Number(days), note)).user); }
    catch (failure) { onFailure(failure); } finally { setBusy(""); }
  };
  const subscribe = async () => {
    if (!plan) return;
    setBusy("subscribe");
    try { update((await cloudAdmin.subscribe(current.id, plan)).user); }
    catch (failure) { onFailure(failure); } finally { setBusy(""); }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="w-[min(40rem,calc(100vw-2rem))]">
        <DialogHeader>
          <DialogTitle>{current.display_name || current.handle || current.email || current.phone}</DialogTitle>
          <DialogDescription>{current.email || current.phone || current.id} · {roleLabel(current.role, copy)} · {copy.credits} {current.credits}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-5">
          <div className="flex flex-wrap gap-2">
            <AButton variant="outline" onClick={() => void role()} loading={busy === "role"} disabled={Boolean(busy)}>{current.role === "admin" ? copy.removeAdmin : copy.makeAdmin}</AButton>
            <AButton variant="outline" onClick={() => void reset()} loading={busy === "reset"} disabled={Boolean(busy)}>{copy.resetPassword}</AButton>
          </div>
          {temporary && (
            <div className="grid gap-1 rounded-lg bg-warning/10 p-3">
              <span className="text-xs text-muted-foreground">{copy.temporaryPassword}</span>
              <code className="font-mono text-sm [overflow-wrap:anywhere]">{temporary}</code>
            </div>
          )}
          <div className="grid gap-2 border-t border-border pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <strong className="text-sm">{copy.plan}</strong>
              <span className="text-xs text-muted-foreground">{current.subscription ? `${current.subscription.name} · ${date(current.subscription.ends_at, locale)}` : copy.noPlan}</span>
            </div>
            <div className="flex gap-2">
              <Select value={plan} onValueChange={setPlan} disabled={plans.length === 0}><ASelectTrigger className="min-w-0 flex-1"><SelectValue placeholder={plans.length === 0 ? copy.noPlansYet : copy.choosePlan} /></ASelectTrigger><SelectContent>{plans.map((one) => <SelectItem key={one.slug} value={one.slug}>{one.name}</SelectItem>)}</SelectContent></Select>
              <AButton variant="outline" onClick={() => void subscribe()} loading={busy === "subscribe"} disabled={!plan || Boolean(busy)}>{copy.subscribe}</AButton>
            </div>
          </div>
          <div className="grid gap-3 border-t border-border pt-4">
            <strong className="text-sm">{copy.giftCredits}</strong>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={copy.credits}><AInput value={credits} onChange={(event) => setCredits(event.target.value)} /></Field>
              <Field label={copy.days}><AInput value={days} onChange={(event) => setDays(event.target.value)} /></Field>
              <Field label={copy.note}><AInput value={note} onChange={(event) => setNote(event.target.value)} /></Field>
            </div>
            <AButton className="w-full" variant="outline" onClick={() => void gift()} loading={busy === "gift"} disabled={Boolean(busy)}>{copy.grant}</AButton>
          </div>
          {current.credit_batches?.length ? <div className="grid gap-1 border-t border-border pt-4 text-xs text-muted-foreground">{current.credit_batches.map((batch, index) => <p key={`${batch.expires_at}-${index}`} className="m-0">{batch.remaining} · {batch.source} · {date(batch.expires_at, locale)}</p>)}</div> : null}
          <div className="grid gap-1 border-t border-border pt-4">
            <strong className="text-sm">{copy.orders}</strong>
            {current.orders?.length ? current.orders.map((order) => <p key={order.id} className="m-0 py-1 text-xs text-muted-foreground">{order.plan?.name || "—"} · {orderStatusLabel(order.status, copy)} · {money(order.amount_cents)} · {date(order.created_at, locale)}</p>) : <p className="m-0 py-2 text-xs text-muted-foreground">{copy.noOrders}</p>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ModelsPanel({ copy, locale, models, onChanged, onFailure }: {
  copy: Messages["admin"]; locale: Locale; models: AdminModel[]; onChanged: () => void; onFailure: (failure: unknown) => void;
}) {
  const [dialog, setDialog] = useState<{ model: AdminModel | null } | null>(null);
  const [priceFor, setPriceFor] = useState<AdminModel | null>(null);
  return (
    <>
      <Card className="bg-card/60 ring-border">
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle>{copy.tabModels}</CardTitle><AButton onClick={() => setDialog({ model: null })}>{copy.addModel}</AButton></CardHeader>
        <CardContent>
          <Table><TableHeader><TableRow><TableHead>{copy.label}</TableHead><TableHead>{copy.currentPrice}</TableHead><TableHead>{copy.channelsCount}</TableHead><TableHead>{copy.listed}</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{models.map((model) => (
              <TableRow key={model.id}>
                <TableCell><strong className="block">{model.display_label}</strong><span className="text-xs text-muted-foreground">{model.max_output_tokens} token</span></TableCell>
                <TableCell>{model.current_price ? `${model.current_price.input_per_1k} / ${model.current_price.output_per_1k}` : copy.noPrice}</TableCell>
                <TableCell>{model.active_channel_count}/{model.channel_count}</TableCell>
                <TableCell><Badge variant={model.listed ? "default" : "secondary"}>{model.listed ? copy.listed : model.not_listed_reasons.map((reason) => modelReasonLabel(reason, copy)).join(", ")}</Badge></TableCell>
                <TableCell className="text-right"><div className="flex justify-end gap-1"><AButton size="sm" variant="outline" onClick={() => setDialog({ model })}>{copy.edit}</AButton><AButton size="sm" variant="ghost" onClick={() => setPriceFor(model)}>{model.current_price ? copy.priceHistory : copy.addPrice}</AButton></div></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
          {models.length === 0 && <Empty>{copy.noModels}</Empty>}
        </CardContent>
      </Card>
      {dialog && <ModelDialog copy={copy} model={dialog.model} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); onChanged(); }} onFailure={onFailure} />}
      {priceFor && <PriceDialog copy={copy} locale={locale} model={priceFor} onClose={() => setPriceFor(null)} onSaved={() => { setPriceFor(null); onChanged(); }} onFailure={onFailure} />}
    </>
  );
}

function ModelDialog({ copy, model, onClose, onSaved, onFailure }: {
  copy: Messages["admin"]; model: AdminModel | null; onClose: () => void; onSaved: () => void; onFailure: (failure: unknown) => void;
}) {
  const [label, setLabel] = useState(model?.label ?? "");
  const [max, setMax] = useState(String(model?.max_output_tokens ?? 8000));
  const [sort, setSort] = useState(String(model?.sort_order ?? 0));
  const [enabled, setEnabled] = useState(model?.enabled ?? true);
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    setSaving(true);
    try {
      if (model) await cloudAdmin.updateModel(model.id, { label, max_output_tokens: Number(max), sort_order: Number(sort), enabled });
      else await cloudAdmin.createModel({ label, max_output_tokens: Number(max), sort_order: Number(sort), enabled });
      onSaved();
    } catch (failure) { onFailure(failure); } finally { setSaving(false); }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent><DialogHeader><DialogTitle>{model ? copy.modelEdit : copy.addModel}</DialogTitle><DialogDescription>{model ? copy.modelEditDesc : copy.modelCreateDesc}</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          <Field label={copy.label}><AInput value={label} onChange={(event) => setLabel(event.target.value)} /></Field>
          <Field label={copy.maxOutput}><AInput value={max} onChange={(event) => setMax(event.target.value)} /></Field>
          <Field label={copy.sort}><AInput value={sort} onChange={(event) => setSort(event.target.value)} /></Field>
          <div className="flex items-center justify-between gap-4 py-1">
            <span className="text-sm font-medium">{copy.enabled}</span>
            <Switch checked={enabled} onCheckedChange={setEnabled} aria-label={copy.enabled} />
          </div>
        </div>
        <DialogFooter><DialogClose asChild><AButton variant="ghost">{copy.cancel}</AButton></DialogClose><AButton onClick={() => void submit()} loading={saving}>{copy.save}</AButton></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PriceDialog({ copy, locale, model, onClose, onSaved, onFailure }: {
  copy: Messages["admin"]; locale: Locale; model: AdminModel; onClose: () => void; onSaved: () => void; onFailure: (failure: unknown) => void;
}) {
  const queryClient = useQueryClient();
  const prices = useAdminPrices(model.id);
  const [input, setInput] = useState("0");
  const [output, setOutput] = useState("0");
  const [from, setFrom] = useState("");
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    setSaving(true);
    try {
      await cloudAdmin.addPrice(model.id, Number(input), Number(output), from || undefined);
      await queryClient.invalidateQueries({ queryKey: queryKeys.adminPrices(model.id) });
      onSaved();
    }
    catch (failure) { onFailure(failure); } finally { setSaving(false); }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="w-[min(40rem,calc(100vw-2rem))]"><DialogHeader><DialogTitle>{copy.priceHistory}</DialogTitle><DialogDescription>{model.display_label}</DialogDescription></DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            {prices.isPending ? (
              <output className="m-0 block text-sm text-muted-foreground">{copy.loading}</output>
            ) : prices.data?.length ? (
              <Table><TableHeader><TableRow><TableHead>{copy.effectiveAt}</TableHead><TableHead>{copy.inputPer1k}</TableHead><TableHead>{copy.outputPer1k}</TableHead></TableRow></TableHeader>
                <TableBody>{prices.data.map((price) => <TableRow key={price.effective_from}><TableCell>{new Date(price.effective_from).toLocaleString(locale === "zh" ? "zh-CN" : "en")}</TableCell><TableCell>{price.input_per_1k}</TableCell><TableCell>{price.output_per_1k}</TableCell></TableRow>)}</TableBody>
              </Table>
            ) : (
              <p className="m-0 text-sm text-muted-foreground">{copy.noPriceHistory}</p>
            )}
          </div>
          <div className="grid gap-3 border-t border-border pt-4">
            <strong className="text-sm">{copy.addPrice}</strong>
            <Field label={copy.inputPer1k}><AInput value={input} onChange={(event) => setInput(event.target.value)} /></Field>
            <Field label={copy.outputPer1k}><AInput value={output} onChange={(event) => setOutput(event.target.value)} /></Field>
            <Field label={copy.effectiveFrom}><AInput value={from} onChange={(event) => setFrom(event.target.value)} /></Field>
          </div>
        </div>
        <DialogFooter><DialogClose asChild><AButton variant="ghost">{copy.cancel}</AButton></DialogClose><AButton onClick={() => void submit()} loading={saving}>{copy.addPrice}</AButton></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProvidersPanel({ copy, providers, onChanged, onFailure }: {
  copy: Messages["admin"]; providers: AdminProvider[]; onChanged: () => void; onFailure: (failure: unknown) => void;
}) {
  const [dialog, setDialog] = useState<{ provider: AdminProvider | null } | null>(null);
  return (
    <>
      <Card className="bg-card/60 ring-border">
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle>{copy.tabProviders}</CardTitle><AButton onClick={() => setDialog({ provider: null })}>{copy.addProvider}</AButton></CardHeader>
        <CardContent>
          <Table><TableHeader><TableRow><TableHead>{copy.providerName}</TableHead><TableHead>{copy.baseUrl}</TableHead><TableHead>{copy.apiKey}</TableHead><TableHead>{copy.enabled}</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{providers.map((provider) => (
              <TableRow key={provider.id}>
                <TableCell><strong className="block">{provider.name}</strong><span className="text-xs text-muted-foreground">{protocolLabel(provider.protocol, copy)}</span></TableCell>
                <TableCell className="max-w-72 truncate">{provider.base_url}</TableCell>
                <TableCell>{provider.has_api_key ? copy.hasKey : "—"}</TableCell>
                <TableCell><ProviderEnabledSwitch copy={copy} provider={provider} onChanged={onChanged} onFailure={onFailure} /></TableCell>
                <TableCell className="text-right"><AButton size="sm" variant="outline" onClick={() => setDialog({ provider })}>{copy.edit}</AButton></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
          {providers.length === 0 && <Empty>{copy.noProviders}</Empty>}
        </CardContent>
      </Card>
      {dialog && <ProviderDialog copy={copy} provider={dialog.provider} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); onChanged(); }} onFailure={onFailure} />}
    </>
  );
}

function ProviderDialog({ copy, provider, onClose, onSaved, onFailure }: {
  copy: Messages["admin"]; provider: AdminProvider | null; onClose: () => void; onSaved: () => void; onFailure: (failure: unknown) => void;
}) {
  const [name, setName] = useState(provider?.name ?? "");
  const [base, setBase] = useState(provider?.base_url ?? "");
  const [key, setKey] = useState("");
  const [note, setNote] = useState(provider?.note ?? "");
  const [enabled, setEnabled] = useState(provider?.enabled ?? true);
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    setSaving(true);
    try {
      if (provider) await cloudAdmin.updateProvider(provider.id, { name, note, enabled, api_key: key });
      else await cloudAdmin.createProvider({ name, base_url: base, api_key: key, note });
      onSaved();
    } catch (failure) { onFailure(failure); } finally { setSaving(false); }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent><DialogHeader><DialogTitle>{provider ? copy.providerEdit : copy.addProvider}</DialogTitle><DialogDescription>{provider?.base_url ?? copy.providerCreateDesc}</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          <Field label={copy.providerName}><AInput value={name} onChange={(event) => setName(event.target.value)} /></Field>
          {!provider && <Field label={copy.baseUrl}><AInput value={base} onChange={(event) => setBase(event.target.value)} /></Field>}
          <Field label={copy.apiKey}><AInput type="password" value={key} onChange={(event) => setKey(event.target.value)} /></Field>
          <p className="m-0 text-xs text-muted-foreground">{copy.apiKeyHint}</p>
          <Field label={copy.note}><AInput value={note} onChange={(event) => setNote(event.target.value)} /></Field>
          <div className="flex items-center justify-between gap-4 py-1">
            <span className="text-sm font-medium">{copy.enabled}</span>
            <Switch checked={enabled} onCheckedChange={setEnabled} aria-label={copy.enabled} />
          </div>
        </div>
        <DialogFooter><DialogClose asChild><AButton variant="ghost">{copy.cancel}</AButton></DialogClose><AButton onClick={() => void submit()} loading={saving}>{copy.save}</AButton></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProviderEnabledSwitch({ copy, provider, onChanged, onFailure }: {
  copy: Messages["admin"]; provider: AdminProvider; onChanged: () => void; onFailure: (failure: unknown) => void;
}) {
  const [busy, setBusy] = useState(false);
  const toggle = async (enabled: boolean) => {
    setBusy(true);
    try {
      await cloudAdmin.updateProvider(provider.id, { name: provider.name, note: provider.note, enabled, api_key: "" });
      onChanged();
    } catch (failure) {
      onFailure(failure);
    } finally {
      setBusy(false);
    }
  };
  return <Switch checked={provider.enabled} disabled={busy} onCheckedChange={(enabled) => void toggle(enabled)} aria-label={`${copy.enabled}: ${provider.name}`} />;
}

function ChannelsPanel({ copy, models, providers, channels, onChanged, onFailure }: {
  copy: Messages["admin"]; models: AdminModel[]; providers: AdminProvider[]; channels: AdminChannel[]; onChanged: () => void; onFailure: (failure: unknown) => void;
}) {
  const [dialog, setDialog] = useState<{ channel: AdminChannel | null } | null>(null);
  const [tests, setTests] = useState<Record<string, AdminChannelTest>>({});
  const [testing, setTesting] = useState("");
  const test = async (channel: AdminChannel) => {
    setTesting(channel.id);
    try {
      const result = (await cloudAdmin.testChannel(channel.id)).result;
      setTests((current) => ({ ...current, [channel.id]: result }));
    } catch (failure) {
      onFailure(failure);
    } finally {
      setTesting("");
    }
  };
  return (
    <>
      <Card className="bg-card/60 ring-border">
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle>{copy.tabChannels}</CardTitle><AButton onClick={() => setDialog({ channel: null })}>{copy.addChannel}</AButton></CardHeader>
        <CardContent>
          <Table><TableHeader><TableRow><TableHead>{copy.label}</TableHead><TableHead>{copy.provider}</TableHead><TableHead>{copy.priority}</TableHead><TableHead>{copy.apiKey}</TableHead><TableHead>{copy.enabled}</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{channels.map((channel) => (
              <TableRow key={channel.id}>
                <TableCell><strong className="block">{channel.model_label}</strong><span className="text-xs text-muted-foreground">{channel.upstream_model}</span></TableCell>
                <TableCell><strong className="block">{channel.provider_name}</strong><span className="block max-w-72 truncate text-xs text-muted-foreground">{channel.base_url}</span></TableCell>
                <TableCell>{channel.priority}</TableCell>
                <TableCell>{channel.has_api_key ? copy.hasKey : "—"}</TableCell>
                <TableCell><ChannelEnabledSwitch copy={copy} channel={channel} onChanged={onChanged} onFailure={onFailure} /></TableCell>
                <TableCell className="text-right"><div className="flex justify-end gap-1"><AButton size="sm" variant="ghost" onClick={() => void test(channel)} loading={testing === channel.id} disabled={Boolean(testing)}>{testing === channel.id ? copy.testing : copy.testChannel}</AButton><AButton size="sm" variant="outline" onClick={() => setDialog({ channel })}>{copy.edit}</AButton></div>{tests[channel.id] && <span className={tests[channel.id].ok ? "text-xs text-success" : "text-xs text-destructive"}>{tests[channel.id].ok ? copy.testOk : copy.testFailed} · {tests[channel.id].status}{tests[channel.id].detail ? <span className="block max-w-72 truncate" title={tests[channel.id].detail}> · {tests[channel.id].detail}</span> : null}</span>}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
          {channels.length === 0 && <Empty>{copy.noChannels}</Empty>}
        </CardContent>
      </Card>
      {dialog && <ChannelDialog copy={copy} models={models} providers={providers} channel={dialog.channel} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); onChanged(); }} onFailure={onFailure} />}
    </>
  );
}

function ChannelDialog({ copy, models, providers, channel, onClose, onSaved, onFailure }: {
  copy: Messages["admin"]; models: AdminModel[]; providers: AdminProvider[]; channel: AdminChannel | null; onClose: () => void; onSaved: () => void; onFailure: (failure: unknown) => void;
}) {
  const [model, setModel] = useState(channel?.model_id ?? models[0]?.id ?? "");
  const [provider, setProvider] = useState(channel?.provider_id ?? providers[0]?.id ?? "");
  const [upstream, setUpstream] = useState(channel?.upstream_model ?? "");
  const [priority, setPriority] = useState(String(channel?.priority ?? 0));
  const [note, setNote] = useState(channel?.note ?? "");
  const [enabled, setEnabled] = useState(channel?.enabled ?? true);
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    setSaving(true);
    try {
      if (channel) await cloudAdmin.updateChannel(channel.id, { upstream_model: upstream, priority: Number(priority), note, enabled });
      else await cloudAdmin.createChannel({ model_id: model, provider_id: provider, upstream_model: upstream, priority: Number(priority), note });
      onSaved();
    } catch (failure) { onFailure(failure); } finally { setSaving(false); }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent><DialogHeader><DialogTitle>{channel ? copy.channelEdit : copy.addChannel}</DialogTitle><DialogDescription>{copy.channelProviderHint}</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          {!channel && <Field label={copy.models}><Select value={model} onValueChange={setModel} disabled={models.length === 0}><ASelectTrigger className="w-full"><SelectValue placeholder={models.length === 0 ? copy.noModelsYet : copy.chooseModel} /></ASelectTrigger><SelectContent>{models.map((one) => <SelectItem key={one.id} value={one.id}>{one.display_label}</SelectItem>)}</SelectContent></Select></Field>}
          {!channel && <Field label={copy.provider}><Select value={provider} onValueChange={setProvider} disabled={providers.length === 0}><ASelectTrigger className="w-full"><SelectValue placeholder={providers.length === 0 ? copy.noProvidersYet : copy.chooseProvider} /></ASelectTrigger><SelectContent>{providers.map((one) => <SelectItem key={one.id} value={one.id}>{one.name}</SelectItem>)}</SelectContent></Select></Field>}
          {!channel && models.length === 0 && <p className="m-0 text-xs text-destructive">{copy.noModelForChannel}</p>}
          {!channel && providers.length === 0 && <p className="m-0 text-xs text-destructive">{copy.noProviderForChannel}</p>}
          <Field label={copy.upstreamModel}><AInput value={upstream} onChange={(event) => setUpstream(event.target.value)} /></Field>
          <Field label={copy.priority}><AInput value={priority} onChange={(event) => setPriority(event.target.value)} /></Field>
          <Field label={copy.note}><AInput value={note} onChange={(event) => setNote(event.target.value)} /></Field>
          <div className="flex items-center justify-between gap-4 py-1">
            <span className="text-sm font-medium">{copy.enabled}</span>
            <Switch checked={enabled} onCheckedChange={setEnabled} aria-label={copy.enabled} />
          </div>
        </div>
        <DialogFooter><DialogClose asChild><AButton variant="ghost">{copy.cancel}</AButton></DialogClose><AButton onClick={() => void submit()} loading={saving} disabled={!channel && (providers.length === 0 || models.length === 0)}>{copy.save}</AButton></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ChannelEnabledSwitch({ copy, channel, onChanged, onFailure }: {
  copy: Messages["admin"]; channel: AdminChannel; onChanged: () => void; onFailure: (failure: unknown) => void;
}) {
  const [busy, setBusy] = useState(false);
  const toggle = async (enabled: boolean) => {
    setBusy(true);
    try {
      await cloudAdmin.updateChannel(channel.id, {
        upstream_model: channel.upstream_model,
        priority: channel.priority,
        note: channel.note,
        enabled,
      });
      onChanged();
    } catch (failure) {
      onFailure(failure);
    } finally {
      setBusy(false);
    }
  };
  return <Switch checked={channel.enabled} disabled={busy} onCheckedChange={(enabled) => void toggle(enabled)} aria-label={`${copy.enabled}: ${channel.model_label}`} />;
}

function PlansPanel({ copy, plans, onChanged, onFailure }: {
  copy: Messages["admin"]; plans: AdminPlan[]; onChanged: () => void; onFailure: (failure: unknown) => void;
}) {
  const [dialog, setDialog] = useState<{ plan: AdminPlan | null } | null>(null);
  return (
    <>
      <Card className="bg-card/60 ring-border">
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle>{copy.tabPlans}</CardTitle><AButton onClick={() => setDialog({ plan: null })}>{copy.addPlan}</AButton></CardHeader>
        <CardContent>
          <Table><TableHeader><TableRow><TableHead>{copy.planCode}</TableHead><TableHead>{copy.monthlyCredits}</TableHead><TableHead>{copy.priceCents}</TableHead><TableHead>{copy.onSale}</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{plans.map((plan) => <TableRow key={plan.slug}><TableCell><strong className="block">{plan.slug}</strong><span className="text-xs text-muted-foreground">{plan.name}</span></TableCell><TableCell>{plan.monthly_credits} · {periodLabel(plan.period, copy)}</TableCell><TableCell>{money(plan.price_cents)}</TableCell><TableCell><PlanOnSaleSwitch copy={copy} plan={plan} onChanged={onChanged} onFailure={onFailure} /></TableCell><TableCell className="text-right"><AButton size="sm" variant="outline" onClick={() => setDialog({ plan })}>{copy.edit}</AButton></TableCell></TableRow>)}</TableBody>
          </Table>
          {plans.length === 0 && <Empty>{copy.noPlans}</Empty>}
        </CardContent>
      </Card>
      {dialog && <PlanDialog copy={copy} plan={dialog.plan} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); onChanged(); }} onFailure={onFailure} />}
    </>
  );
}

function PlanDialog({ copy, plan, onClose, onSaved, onFailure }: {
  copy: Messages["admin"]; plan: AdminPlan | null; onClose: () => void; onSaved: () => void; onFailure: (failure: unknown) => void;
}) {
  const [slug, setSlug] = useState(plan?.slug ?? "");
  const [name, setName] = useState(plan?.name ?? "");
  const [period, setPeriod] = useState<AdminPlan["period"]>(plan?.period ?? "month");
  const [credits, setCredits] = useState(String(plan?.monthly_credits ?? 1000));
  const [ttl, setTtl] = useState(String(plan?.credit_ttl_days ?? 60));
  const [price, setPrice] = useState(plan?.price_cents ? String(plan.price_cents) : "");
  const [onSale, setOnSale] = useState(plan?.on_sale ?? false);
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    setSaving(true);
    try {
      const payload = { name, period, monthly_credits: Number(credits), credit_ttl_days: Number(ttl), on_sale: onSale, price_cents: price ? Number(price) : null };
      if (plan) await cloudAdmin.updatePlan(plan.slug, payload);
      else await cloudAdmin.createPlan({ ...payload, slug });
      onSaved();
    } catch (failure) { onFailure(failure); } finally { setSaving(false); }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent><DialogHeader><DialogTitle>{plan ? copy.planEdit : copy.addPlan}</DialogTitle><DialogDescription>{plan ? plan.slug : copy.planCreateDesc}</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          {!plan && <Field label={copy.planCode}><AInput value={slug} placeholder="pro" onChange={(event) => setSlug(event.target.value)} /></Field>}
          {!plan && <p className="m-0 -mt-2 text-xs text-muted-foreground">{copy.planCodeHint}</p>}
          <Field label={copy.label}><AInput value={name} onChange={(event) => setName(event.target.value)} /></Field>
          <Field label={copy.period}><Select value={period} onValueChange={(value) => setPeriod(value as AdminPlan["period"])}><ASelectTrigger className="w-full"><SelectValue /></ASelectTrigger><SelectContent><SelectItem value="month">{copy.month}</SelectItem><SelectItem value="quarter">{copy.quarter}</SelectItem><SelectItem value="year">{copy.year}</SelectItem></SelectContent></Select></Field>
          <Field label={copy.monthlyCredits}><AInput value={credits} onChange={(event) => setCredits(event.target.value)} /></Field>
          <Field label={copy.ttlDays}><AInput value={ttl} onChange={(event) => setTtl(event.target.value)} /></Field>
          <Field label={copy.priceCents}><AInput value={price} onChange={(event) => setPrice(event.target.value)} /></Field>
          <div className="flex items-center justify-between gap-4 py-1">
            <span className="text-sm font-medium">{copy.onSale}</span>
            <Switch checked={onSale} onCheckedChange={setOnSale} aria-label={copy.onSale} />
          </div>
        </div>
        <DialogFooter><DialogClose asChild><AButton variant="ghost">{copy.cancel}</AButton></DialogClose><AButton onClick={() => void submit()} loading={saving}>{copy.save}</AButton></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PlanOnSaleSwitch({ copy, plan, onChanged, onFailure }: {
  copy: Messages["admin"]; plan: AdminPlan; onChanged: () => void; onFailure: (failure: unknown) => void;
}) {
  const [busy, setBusy] = useState(false);
  const toggle = async (onSale: boolean) => {
    setBusy(true);
    try {
      await cloudAdmin.updatePlan(plan.slug, {
        name: plan.name,
        period: plan.period,
        monthly_credits: plan.monthly_credits,
        credit_ttl_days: plan.credit_ttl_days,
        on_sale: onSale,
        price_cents: plan.price_cents,
      });
      onChanged();
    } catch (failure) {
      onFailure(failure);
    } finally {
      setBusy(false);
    }
  };
  return <Switch checked={plan.on_sale} disabled={busy} onCheckedChange={(onSale) => void toggle(onSale)} aria-label={`${copy.onSale}: ${plan.name}`} />;
}

function OperationsPanel({ copy, locale, orders, usage }: { copy: Messages["admin"]; locale: Locale; orders: AdminOrder[]; usage: AdminUsage | null }) {
  return (
    <div className="grid gap-4">
      {usage && <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[[copy.usageCalls, usage.totals.calls], [copy.usageCharged, usage.totals.charged], [copy.usageInput, usage.totals.input_tokens], [copy.usageOutput, usage.totals.output_tokens]].map(([label, value]) => <Card key={String(label)} className="bg-card/60 ring-border"><CardHeader><CardDescription>{label}</CardDescription><CardTitle className="text-2xl">{value}</CardTitle></CardHeader></Card>)}</div>}
      {usage && <div className="grid gap-4 lg:grid-cols-2"><UsageTable copy={copy} title={copy.usageByDay} rows={usage.by_day.map((r) => ({ key: r.date, label: r.date, calls: r.calls, charged: r.charged }))} /><UsageTable copy={copy} title={copy.usageByModel} rows={usage.by_model.map((r) => ({ key: r.model_id, label: r.label, calls: r.calls, charged: r.charged }))} /></div>}
      <Card className="bg-card/60 ring-border"><CardHeader><CardTitle>{copy.orders}</CardTitle></CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>{copy.orderUser}</TableHead><TableHead>{copy.plan}</TableHead><TableHead>{copy.amount}</TableHead><TableHead>{copy.status}</TableHead><TableHead>{copy.channel}</TableHead><TableHead>{copy.createdAt}</TableHead></TableRow></TableHeader><TableBody>{orders.map((order) => <TableRow key={order.id}><TableCell>{order.user?.email || order.user?.handle || "—"}</TableCell><TableCell>{order.plan?.name || "—"}</TableCell><TableCell>{money(order.amount_cents)}</TableCell><TableCell>{orderStatusLabel(order.status, copy)}</TableCell><TableCell>{orderChannelLabel(order.channel, copy)}</TableCell><TableCell>{date(order.created_at, locale)}</TableCell></TableRow>)}</TableBody></Table>{orders.length === 0 && <Empty>{copy.noOrders}</Empty>}</CardContent></Card>
    </div>
  );
}

function UsageTable({ copy, title, rows }: { copy: Messages["admin"]; title: string; rows: { key: string; label: string; calls: number; charged: number }[] }) {
  return <Card className="bg-card/60 ring-border"><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>{copy.models}</TableHead><TableHead>{copy.usageCalls}</TableHead><TableHead>{copy.usageCharged}</TableHead></TableRow></TableHeader><TableBody>{rows.map((row) => <TableRow key={row.key}><TableCell>{row.label}</TableCell><TableCell>{row.calls}</TableCell><TableCell>{row.charged}</TableCell></TableRow>)}</TableBody></Table>{rows.length === 0 && <Empty>{copy.noUsage}</Empty>}</CardContent></Card>;
}

function AuditPanel({ copy, locale, audit }: { copy: Messages["admin"]; locale: Locale; audit: AdminAudit[] }) {
  return <Card className="bg-card/60 ring-border"><CardHeader><CardTitle>{copy.tabAudit}</CardTitle></CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>{copy.auditTime}</TableHead><TableHead>{copy.auditActor}</TableHead><TableHead>{copy.auditAction}</TableHead><TableHead>{copy.auditTarget}</TableHead></TableRow></TableHeader><TableBody>{audit.map((event) => <TableRow key={event.id}><TableCell>{date(event.created_at, locale)}</TableCell><TableCell>{event.actor_email}</TableCell><TableCell>{auditActionLabel(event.action, copy)}</TableCell><TableCell>{auditTargetLabel(event.target_type, copy)}:{event.target_id}</TableCell></TableRow>)}</TableBody></Table>{audit.length === 0 && <Empty>{copy.noAudit}</Empty>}</CardContent></Card>;
}
