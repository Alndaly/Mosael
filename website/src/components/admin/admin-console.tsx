"use client";

import { useEffect, useState } from "react";

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
import { LocaleSwitch } from "@/components/locale-switch";
import { ThemeToggle } from "@/components/theme-toggle";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Activity, Boxes, Cable, CreditCard, LayoutDashboard, Menu, ScrollText, Users } from "lucide-react";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { cn } from "@/lib/utils";
import {
  CloudApiError,
  cloudAdmin,
  type AdminAudit,
  type AdminChannel,
  type AdminChannelTest,
  type AdminModel,
  type AdminOrder,
  type AdminOverview,
  type AdminPlan,
  type AdminUsage,
  type AdminUser,
  type CloudUser,
} from "@/lib/cloud";

function failureText(error: unknown, copy: Messages["admin"], locale: Locale): string {
  return error instanceof CloudApiError ? error.text(locale) : copy.error;
}

function date(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : "—";
}

function money(cents: number | null): string {
  return cents === null ? "—" : `¥${(cents / 100).toFixed(2)}`;
}

/** 管理台采用 shadcn 的标准密度（36px），不继承官网营销页的 48px 大字段。 */
function AButton({ className, ...props }: React.ComponentProps<typeof Button>) {
  return <Button {...props} className={cn("h-9 rounded-md px-3 text-sm", className)} />;
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

export function AdminConsole({ locale, copy, viewer }: { locale: Locale; copy: Messages["admin"]; viewer: CloudUser }) {
  const [tab, setTab] = useState("overview");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [models, setModels] = useState<AdminModel[]>([]);
  const [channels, setChannels] = useState<AdminChannel[]>([]);
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [usage, setUsage] = useState<AdminUsage | null>(null);
  const [audit, setAudit] = useState<AdminAudit[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const [o, u, m, c, p, ord, use, a] = await Promise.all([
        cloudAdmin.overview(),
        cloudAdmin.users(),
        cloudAdmin.models(),
        cloudAdmin.channels(),
        cloudAdmin.plans(),
        cloudAdmin.orders(),
        cloudAdmin.usage(),
        cloudAdmin.audit(),
      ]);
      setOverview(o);
      setUsers(u.users);
      setModels(m.models);
      setChannels(c.channels);
      setPlans(p.plans);
      setOrders(ord.orders);
      setUsage(use);
      setAudit(a.events);
    } catch (failure) {
      setError(failureText(failure, copy, locale));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // 首屏一次;动作完成后各自刷新。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <SidebarProvider>
      <AdminSidebar tab={tab} onSelect={setTab} copy={copy} locale={locale} viewer={viewer} />
      <SidebarInset>
        <div className="mx-auto max-w-[100rem] px-4 py-8 sm:px-6 lg:px-10">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex items-start gap-3">
              <SidebarTrigger aria-label={copy.title} className="mt-1"><Menu className="size-4" /></SidebarTrigger>
              <div>
                <p className="m-0 text-xs font-semibold tracking-[0.18em] text-muted-foreground uppercase">MosaelCloud / Control</p>
                <h1 className="mt-2 mb-0 font-display text-4xl font-semibold tracking-[-0.04em]">{copy.title}</h1>
                <p className="mt-2 mb-0 max-w-2xl text-sm leading-6 text-muted-foreground">{copy.lede}</p>
              </div>
            </div>
            <AButton variant="outline" onClick={() => void refresh()} disabled={loading}>{loading ? copy.loading : copy.refresh}</AButton>
          </div>

          {error && <div className="mt-5 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">{error}</div>}

          <div className="mt-8">
            {tab === "overview" && (overview ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {[
                  [copy.users, overview.users],
                  [copy.admins, overview.admins],
                  [copy.subscriptions, overview.subscriptions],
                  [copy.models, overview.models],
                  [copy.channels, overview.channels],
                  [copy.orders, overview.orders],
                ].map(([label, value]) => (
                  <Card key={String(label)} className="bg-card/60 ring-border">
                    <CardHeader><CardDescription>{label}</CardDescription><CardTitle className="text-3xl">{value}</CardTitle></CardHeader>
                  </Card>
                ))}
              </div>
            ) : <Empty>{loading ? copy.loading : copy.noUsers}</Empty>)}
            {tab === "users" && <UsersPanel copy={copy} users={users} plans={plans} onChanged={() => void refresh()} onFailure={(e) => setError(failureText(e, copy, locale))} />}
            {tab === "models" && <ModelsPanel copy={copy} models={models} onChanged={() => void refresh()} onFailure={(e) => setError(failureText(e, copy, locale))} />}
            {tab === "channels" && <ChannelsPanel copy={copy} models={models} channels={channels} onChanged={() => void refresh()} onFailure={(e) => setError(failureText(e, copy, locale))} />}
            {tab === "plans" && <PlansPanel copy={copy} plans={plans} onChanged={() => void refresh()} onFailure={(e) => setError(failureText(e, copy, locale))} />}
            {tab === "operations" && <OperationsPanel copy={copy} orders={orders} usage={usage} />}
            {tab === "audit" && <AuditPanel copy={copy} audit={audit} />}
          </div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}

function AdminSidebar({ tab, onSelect, copy, locale, viewer }: { tab: string; onSelect: (tab: string) => void; copy: Messages["admin"]; locale: Locale; viewer: CloudUser }) {
  const name = viewer.display_name?.trim() || viewer.handle?.trim() || viewer.email?.trim() || viewer.phone || "Admin";
  const initial = Array.from(name)[0]?.toUpperCase() ?? "A";
  const items = [
    { id: "overview", label: copy.tabOverview, icon: LayoutDashboard },
    { id: "users", label: copy.tabUsers, icon: Users },
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
            <span className="text-[11px] text-muted-foreground">Admin console</span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
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
          <Badge variant="secondary">{viewer.role || "admin"}</Badge>
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

function UsersPanel({ copy, users, plans, onChanged, onFailure }: {
  copy: Messages["admin"];
  users: AdminUser[];
  plans: AdminPlan[];
  onChanged: () => void;
  onFailure: (failure: unknown) => void;
}) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<AdminUser[] | null>(null);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const search = async () => {
    try {
      setFound((await cloudAdmin.users(query)).users);
    } catch (failure) {
      onFailure(failure);
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
            <AButton variant="outline" onClick={() => void search()}>{copy.search}</AButton>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>{copy.users}</TableHead><TableHead>{copy.role}</TableHead><TableHead>{copy.credits}</TableHead><TableHead>{copy.plan}</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {visible.map((user) => (
                <TableRow key={user.id}>
                  <TableCell><strong className="block font-medium">{user.display_name || user.handle || user.email || user.phone}</strong><span className="text-xs text-muted-foreground">{user.email || user.phone}</span></TableCell>
                  <TableCell><Badge variant={user.role === "admin" ? "default" : "secondary"}>{user.role}</Badge>{user.official && <Badge variant="outline" className="ml-1">{copy.official}</Badge>}</TableCell>
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

function UserDialog({ copy, user, plans, onClose, onUser, onFailure }: {
  copy: Messages["admin"];
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
          <DialogDescription>{current.email || current.phone || current.id} · {current.role} · {copy.credits} {current.credits}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-5">
          <div className="flex flex-wrap gap-2">
            <AButton variant="outline" onClick={() => void role()} disabled={Boolean(busy)}>{current.role === "admin" ? copy.removeAdmin : copy.makeAdmin}</AButton>
            <AButton variant="outline" onClick={() => void reset()} disabled={Boolean(busy)}>{copy.resetPassword}</AButton>
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
              <span className="text-xs text-muted-foreground">{current.subscription ? `${current.subscription.name} · ${date(current.subscription.ends_at)}` : copy.noPlan}</span>
            </div>
            <div className="flex gap-2">
              <Select value={plan} onValueChange={setPlan}><ASelectTrigger className="min-w-0 flex-1"><SelectValue /></ASelectTrigger><SelectContent>{plans.map((one) => <SelectItem key={one.slug} value={one.slug}>{one.name}</SelectItem>)}</SelectContent></Select>
              <AButton variant="outline" onClick={() => void subscribe()} disabled={!plan || Boolean(busy)}>{copy.subscribe}</AButton>
            </div>
          </div>
          <div className="grid gap-3 border-t border-border pt-4">
            <strong className="text-sm">{copy.giftCredits}</strong>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={copy.credits}><AInput value={credits} onChange={(event) => setCredits(event.target.value)} /></Field>
              <Field label={copy.days}><AInput value={days} onChange={(event) => setDays(event.target.value)} /></Field>
              <Field label={copy.note}><AInput value={note} onChange={(event) => setNote(event.target.value)} /></Field>
            </div>
            <AButton className="w-full" variant="outline" onClick={() => void gift()} disabled={Boolean(busy)}>{copy.grant}</AButton>
          </div>
          {current.credit_batches?.length ? <div className="grid gap-1 border-t border-border pt-4 text-xs text-muted-foreground">{current.credit_batches.map((batch, index) => <p key={`${batch.expires_at}-${index}`} className="m-0">{batch.remaining} · {batch.source} · {date(batch.expires_at)}</p>)}</div> : null}
          <div className="grid gap-1 border-t border-border pt-4">
            <strong className="text-sm">{copy.orders}</strong>
            {current.orders?.length ? current.orders.map((order) => <p key={order.id} className="m-0 py-1 text-xs text-muted-foreground">{order.plan?.name || "—"} · {order.status} · {money(order.amount_cents)} · {date(order.created_at)}</p>) : <p className="m-0 py-2 text-xs text-muted-foreground">{copy.noOrders}</p>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ModelsPanel({ copy, models, onChanged, onFailure }: {
  copy: Messages["admin"]; models: AdminModel[]; onChanged: () => void; onFailure: (failure: unknown) => void;
}) {
  const [dialog, setDialog] = useState<{ model: AdminModel | null } | null>(null);
  const [priceFor, setPriceFor] = useState<AdminModel | null>(null);
  return (
    <>
      <Card className="bg-card/60 ring-border">
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle>{copy.tabModels}</CardTitle><AButton onClick={() => setDialog({ model: null })}>{copy.addModel}</AButton></CardHeader>
        <CardContent>
          <Table><TableHeader><TableRow><TableHead>{copy.id}</TableHead><TableHead>{copy.currentPrice}</TableHead><TableHead>{copy.channelsCount}</TableHead><TableHead>{copy.listed}</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{models.map((model) => (
              <TableRow key={model.id}>
                <TableCell><strong className="block">{model.id}</strong><span className="text-xs text-muted-foreground">{model.label}</span></TableCell>
                <TableCell>{model.current_price ? `${model.current_price.input_per_1k} / ${model.current_price.output_per_1k}` : copy.noPrice}</TableCell>
                <TableCell>{model.active_channel_count}/{model.channel_count}</TableCell>
                <TableCell><Badge variant={model.listed ? "default" : "secondary"}>{model.listed ? copy.listed : model.not_listed_reasons.join(", ")}</Badge></TableCell>
                <TableCell className="text-right"><div className="flex justify-end gap-1"><AButton size="sm" variant="outline" onClick={() => setDialog({ model })}>{copy.edit}</AButton><AButton size="sm" variant="ghost" onClick={() => setPriceFor(model)}>{copy.addPrice}</AButton></div></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
          {models.length === 0 && <Empty>{copy.noModels}</Empty>}
        </CardContent>
      </Card>
      {dialog && <ModelDialog copy={copy} model={dialog.model} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); onChanged(); }} onFailure={onFailure} />}
      {priceFor && <PriceDialog copy={copy} model={priceFor} onClose={() => setPriceFor(null)} onSaved={() => { setPriceFor(null); onChanged(); }} onFailure={onFailure} />}
    </>
  );
}

function ModelDialog({ copy, model, onClose, onSaved, onFailure }: {
  copy: Messages["admin"]; model: AdminModel | null; onClose: () => void; onSaved: () => void; onFailure: (failure: unknown) => void;
}) {
  const [id, setId] = useState(model?.id ?? "");
  const [label, setLabel] = useState(model?.label ?? "");
  const [max, setMax] = useState(String(model?.max_output_tokens ?? 8000));
  const [sort, setSort] = useState(String(model?.sort_order ?? 0));
  const [enabled, setEnabled] = useState(model?.enabled ?? true);
  const submit = async () => {
    try {
      if (model) await cloudAdmin.updateModel(model.id, { label, max_output_tokens: Number(max), sort_order: Number(sort), enabled });
      else await cloudAdmin.createModel({ id, label, max_output_tokens: Number(max), sort_order: Number(sort), enabled });
      onSaved();
    } catch (failure) { onFailure(failure); }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent><DialogHeader><DialogTitle>{model ? copy.modelEdit : copy.addModel}</DialogTitle><DialogDescription>{model?.id ?? copy.id}</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          {!model && <Field label={copy.id}><AInput value={id} onChange={(event) => setId(event.target.value)} /></Field>}
          <Field label={copy.label}><AInput value={label} onChange={(event) => setLabel(event.target.value)} /></Field>
          <Field label={copy.maxOutput}><AInput value={max} onChange={(event) => setMax(event.target.value)} /></Field>
          <Field label={copy.sort}><AInput value={sort} onChange={(event) => setSort(event.target.value)} /></Field>
          <AButton type="button" variant={enabled ? "default" : "outline"} onClick={() => setEnabled(!enabled)} aria-pressed={enabled}>{copy.enabled}</AButton>
        </div>
        <DialogFooter><DialogClose asChild><AButton variant="ghost">{copy.cancel}</AButton></DialogClose><AButton onClick={() => void submit()}>{copy.save}</AButton></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PriceDialog({ copy, model, onClose, onSaved, onFailure }: {
  copy: Messages["admin"]; model: AdminModel; onClose: () => void; onSaved: () => void; onFailure: (failure: unknown) => void;
}) {
  const [input, setInput] = useState("0");
  const [output, setOutput] = useState("0");
  const [from, setFrom] = useState("");
  const submit = async () => {
    try { await cloudAdmin.addPrice(model.id, Number(input), Number(output), from || undefined); onSaved(); }
    catch (failure) { onFailure(failure); }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent><DialogHeader><DialogTitle>{copy.addPrice}</DialogTitle><DialogDescription>{model.id}</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          <Field label={copy.inputPer1k}><AInput value={input} onChange={(event) => setInput(event.target.value)} /></Field>
          <Field label={copy.outputPer1k}><AInput value={output} onChange={(event) => setOutput(event.target.value)} /></Field>
          <Field label={copy.effectiveFrom}><AInput value={from} onChange={(event) => setFrom(event.target.value)} /></Field>
        </div>
        <DialogFooter><DialogClose asChild><AButton variant="ghost">{copy.cancel}</AButton></DialogClose><AButton onClick={() => void submit()}>{copy.addPrice}</AButton></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ChannelsPanel({ copy, models, channels, onChanged, onFailure }: {
  copy: Messages["admin"]; models: AdminModel[]; channels: AdminChannel[]; onChanged: () => void; onFailure: (failure: unknown) => void;
}) {
  const [dialog, setDialog] = useState<{ channel: AdminChannel | null } | null>(null);
  const [tests, setTests] = useState<Record<string, AdminChannelTest>>({});
  const test = async (channel: AdminChannel) => {
    try {
      const result = (await cloudAdmin.testChannel(channel.id)).result;
      setTests((current) => ({ ...current, [channel.id]: result }));
    } catch (failure) {
      onFailure(failure);
    }
  };
  return (
    <>
      <Card className="bg-card/60 ring-border">
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle>{copy.tabChannels}</CardTitle><AButton onClick={() => setDialog({ channel: null })}>{copy.addChannel}</AButton></CardHeader>
        <CardContent>
          <Table><TableHeader><TableRow><TableHead>{copy.id}</TableHead><TableHead>{copy.baseUrl}</TableHead><TableHead>{copy.priority}</TableHead><TableHead>{copy.apiKey}</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{channels.map((channel) => (
              <TableRow key={channel.id}>
                <TableCell><strong className="block">{channel.model_id}</strong><span className="text-xs text-muted-foreground">{channel.upstream_model}</span></TableCell>
                <TableCell className="max-w-72 truncate">{channel.base_url}</TableCell>
                <TableCell>{channel.priority} · <Badge variant={channel.enabled ? "default" : "secondary"}>{channel.enabled ? "on" : "off"}</Badge></TableCell>
                <TableCell>{channel.has_api_key ? copy.hasKey : "—"}</TableCell>
                <TableCell className="text-right"><div className="flex justify-end gap-1"><AButton size="sm" variant="ghost" onClick={() => void test(channel)}>{copy.testChannel}</AButton><AButton size="sm" variant="outline" onClick={() => setDialog({ channel })}>{copy.edit}</AButton></div>{tests[channel.id] && <span className={tests[channel.id].ok ? "text-xs text-success" : "text-xs text-destructive"}>{tests[channel.id].ok ? copy.testOk : copy.testFailed} · {tests[channel.id].status}</span>}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
          {channels.length === 0 && <Empty>{copy.noChannels}</Empty>}
        </CardContent>
      </Card>
      {dialog && <ChannelDialog copy={copy} models={models} channel={dialog.channel} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); onChanged(); }} onFailure={onFailure} />}
    </>
  );
}

function ChannelDialog({ copy, models, channel, onClose, onSaved, onFailure }: {
  copy: Messages["admin"]; models: AdminModel[]; channel: AdminChannel | null; onClose: () => void; onSaved: () => void; onFailure: (failure: unknown) => void;
}) {
  const [model, setModel] = useState(channel?.model_id ?? models[0]?.id ?? "");
  const [base, setBase] = useState(channel?.base_url ?? "");
  const [upstream, setUpstream] = useState(channel?.upstream_model ?? "");
  const [key, setKey] = useState("");
  const [priority, setPriority] = useState(String(channel?.priority ?? 0));
  const [note, setNote] = useState(channel?.note ?? "");
  const [enabled, setEnabled] = useState(channel?.enabled ?? true);
  const submit = async () => {
    try {
      if (channel) await cloudAdmin.updateChannel(channel.id, { upstream_model: upstream, priority: Number(priority), note, enabled, api_key: key });
      else await cloudAdmin.createChannel({ model_id: model, base_url: base, upstream_model: upstream, api_key: key, priority: Number(priority), note });
      onSaved();
    } catch (failure) { onFailure(failure); }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent><DialogHeader><DialogTitle>{channel ? copy.channelEdit : copy.addChannel}</DialogTitle><DialogDescription>{channel?.base_url ?? copy.baseUrlReadOnly}</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          {!channel && <Field label={copy.models}><Select value={model} onValueChange={setModel}><ASelectTrigger className="w-full"><SelectValue /></ASelectTrigger><SelectContent>{models.map((one) => <SelectItem key={one.id} value={one.id}>{one.id}</SelectItem>)}</SelectContent></Select></Field>}
          {!channel && <Field label={copy.baseUrl}><AInput value={base} onChange={(event) => setBase(event.target.value)} /></Field>}
          <Field label={copy.upstreamModel}><AInput value={upstream} onChange={(event) => setUpstream(event.target.value)} /></Field>
          <Field label={copy.apiKey}><AInput type="password" value={key} onChange={(event) => setKey(event.target.value)} /></Field>
          <p className="m-0 text-xs text-muted-foreground">{copy.replaceKeyHint}</p>
          <Field label={copy.priority}><AInput value={priority} onChange={(event) => setPriority(event.target.value)} /></Field>
          <Field label={copy.note}><AInput value={note} onChange={(event) => setNote(event.target.value)} /></Field>
          <AButton type="button" variant={enabled ? "default" : "outline"} onClick={() => setEnabled(!enabled)} aria-pressed={enabled}>{copy.enabled}</AButton>
        </div>
        <DialogFooter><DialogClose asChild><AButton variant="ghost">{copy.cancel}</AButton></DialogClose><AButton onClick={() => void submit()}>{copy.save}</AButton></DialogFooter>
      </DialogContent>
    </Dialog>
  );
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
          <Table><TableHeader><TableRow><TableHead>{copy.slug}</TableHead><TableHead>{copy.monthlyCredits}</TableHead><TableHead>{copy.priceCents}</TableHead><TableHead>{copy.onSale}</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{plans.map((plan) => <TableRow key={plan.slug}><TableCell><strong className="block">{plan.slug}</strong><span className="text-xs text-muted-foreground">{plan.name}</span></TableCell><TableCell>{plan.monthly_credits} · {plan.period}</TableCell><TableCell>{money(plan.price_cents)}</TableCell><TableCell><Badge variant={plan.on_sale ? "default" : "secondary"}>{plan.on_sale ? "on" : "off"}</Badge></TableCell><TableCell className="text-right"><AButton size="sm" variant="outline" onClick={() => setDialog({ plan })}>{copy.edit}</AButton></TableCell></TableRow>)}</TableBody>
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
  const submit = async () => {
    try {
      const payload = { name, period, monthly_credits: Number(credits), credit_ttl_days: Number(ttl), on_sale: onSale, price_cents: price ? Number(price) : null };
      if (plan) await cloudAdmin.updatePlan(plan.slug, payload);
      else await cloudAdmin.createPlan({ ...payload, slug });
      onSaved();
    } catch (failure) { onFailure(failure); }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent><DialogHeader><DialogTitle>{plan ? copy.planEdit : copy.addPlan}</DialogTitle><DialogDescription>{plan?.slug ?? copy.slug}</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          {!plan && <Field label={copy.slug}><AInput value={slug} onChange={(event) => setSlug(event.target.value)} /></Field>}
          <Field label={copy.label}><AInput value={name} onChange={(event) => setName(event.target.value)} /></Field>
          <Field label={copy.period}><Select value={period} onValueChange={(value) => setPeriod(value as AdminPlan["period"])}><ASelectTrigger className="w-full"><SelectValue /></ASelectTrigger><SelectContent><SelectItem value="month">{copy.month}</SelectItem><SelectItem value="quarter">{copy.quarter}</SelectItem><SelectItem value="year">{copy.year}</SelectItem></SelectContent></Select></Field>
          <Field label={copy.monthlyCredits}><AInput value={credits} onChange={(event) => setCredits(event.target.value)} /></Field>
          <Field label={copy.ttlDays}><AInput value={ttl} onChange={(event) => setTtl(event.target.value)} /></Field>
          <Field label={copy.priceCents}><AInput value={price} onChange={(event) => setPrice(event.target.value)} /></Field>
          <AButton type="button" variant={onSale ? "default" : "outline"} onClick={() => setOnSale(!onSale)} aria-pressed={onSale}>{copy.onSale}</AButton>
        </div>
        <DialogFooter><DialogClose asChild><AButton variant="ghost">{copy.cancel}</AButton></DialogClose><AButton onClick={() => void submit()}>{copy.save}</AButton></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function OperationsPanel({ copy, orders, usage }: { copy: Messages["admin"]; orders: AdminOrder[]; usage: AdminUsage | null }) {
  return (
    <div className="grid gap-4">
      {usage && <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[[copy.usageCalls, usage.totals.calls], [copy.usageCharged, usage.totals.charged], [copy.usageInput, usage.totals.input_tokens], [copy.usageOutput, usage.totals.output_tokens]].map(([label, value]) => <Card key={String(label)} className="bg-card/60 ring-border"><CardHeader><CardDescription>{label}</CardDescription><CardTitle className="text-2xl">{value}</CardTitle></CardHeader></Card>)}</div>}
      {usage && <div className="grid gap-4 lg:grid-cols-2"><UsageTable copy={copy} title={copy.usageByDay} rows={usage.by_day.map((r) => ({ key: r.date, label: r.date, calls: r.calls, charged: r.charged }))} /><UsageTable copy={copy} title={copy.usageByModel} rows={usage.by_model.map((r) => ({ key: r.model_id, label: r.model_id, calls: r.calls, charged: r.charged }))} /></div>}
      <Card className="bg-card/60 ring-border"><CardHeader><CardTitle>{copy.orders}</CardTitle></CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>{copy.orderUser}</TableHead><TableHead>{copy.plan}</TableHead><TableHead>{copy.amount}</TableHead><TableHead>{copy.status}</TableHead><TableHead>{copy.channel}</TableHead><TableHead>{copy.createdAt}</TableHead></TableRow></TableHeader><TableBody>{orders.map((order) => <TableRow key={order.id}><TableCell>{order.user?.email || order.user?.handle || "—"}</TableCell><TableCell>{order.plan?.name || "—"}</TableCell><TableCell>{money(order.amount_cents)}</TableCell><TableCell>{order.status}</TableCell><TableCell>{order.channel}</TableCell><TableCell>{date(order.created_at)}</TableCell></TableRow>)}</TableBody></Table>{orders.length === 0 && <Empty>{copy.noOrders}</Empty>}</CardContent></Card>
    </div>
  );
}

function UsageTable({ copy, title, rows }: { copy: Messages["admin"]; title: string; rows: { key: string; label: string; calls: number; charged: number }[] }) {
  return <Card className="bg-card/60 ring-border"><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>{copy.id}</TableHead><TableHead>{copy.usageCalls}</TableHead><TableHead>{copy.usageCharged}</TableHead></TableRow></TableHeader><TableBody>{rows.map((row) => <TableRow key={row.key}><TableCell>{row.label}</TableCell><TableCell>{row.calls}</TableCell><TableCell>{row.charged}</TableCell></TableRow>)}</TableBody></Table>{rows.length === 0 && <Empty>{copy.noUsage}</Empty>}</CardContent></Card>;
}

function AuditPanel({ copy, audit }: { copy: Messages["admin"]; audit: AdminAudit[] }) {
  return <Card className="bg-card/60 ring-border"><CardHeader><CardTitle>{copy.tabAudit}</CardTitle></CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>{copy.auditTime}</TableHead><TableHead>{copy.auditActor}</TableHead><TableHead>{copy.auditAction}</TableHead><TableHead>{copy.auditTarget}</TableHead></TableRow></TableHeader><TableBody>{audit.map((event) => <TableRow key={event.id}><TableCell>{date(event.created_at)}</TableCell><TableCell>{event.actor_email}</TableCell><TableCell className="font-mono text-xs">{event.action}</TableCell><TableCell>{event.target_type}:{event.target_id}</TableCell></TableRow>)}</TableBody></Table>{audit.length === 0 && <Empty>{copy.noAudit}</Empty>}</CardContent></Card>;
}
