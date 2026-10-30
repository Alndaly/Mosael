"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import {
  CloudApiError,
  cloudAdmin,
  type AdminChannel,
  type AdminModel,
  type AdminOverview,
  type AdminPlan,
  type AdminUser,
} from "@/lib/cloud";

type Tab = "overview" | "users" | "models" | "channels" | "plans";

function failureText(error: unknown, copy: Messages["admin"], locale: Locale): string {
  return error instanceof CloudApiError ? error.text(locale) : copy.error;
}

function date(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : "—";
}

function money(cents: number | null): string {
  return cents === null ? "—" : `¥${(cents / 100).toFixed(2)}`;
}

const card = "rounded-2xl border border-border bg-card p-5";
const field = "grid min-w-0 gap-1.5 text-[13px] text-muted-foreground";

export function AdminConsole({ locale, copy }: { locale: Locale; copy: Messages["admin"] }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [models, setModels] = useState<AdminModel[]>([]);
  const [channels, setChannels] = useState<AdminChannel[]>([]);
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const [nextOverview, nextUsers, nextModels, nextChannels, nextPlans] = await Promise.all([
        cloudAdmin.overview(),
        cloudAdmin.users(query),
        cloudAdmin.models(),
        cloudAdmin.channels(),
        cloudAdmin.plans(),
      ]);
      setOverview(nextOverview);
      setUsers(nextUsers.users);
      setModels(nextModels.models);
      setChannels(nextChannels.channels);
      setPlans(nextPlans.plans);
    } catch (failure) {
      setError(failureText(failure, copy, locale));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // 首屏一次;后续动作各自刷新。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const search = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const result = await cloudAdmin.users(query);
      setUsers(result.users);
    } catch (failure) {
      setError(failureText(failure, copy, locale));
    }
  };

  const selectUser = async (id: string) => {
    try {
      setSelected((await cloudAdmin.user(id)).user);
    } catch (failure) {
      setError(failureText(failure, copy, locale));
    }
  };

  return (
    <section className="bg-paper">
      <div className="mx-auto max-w-[88rem] px-5 py-12 sm:px-8">
        <h1 className="m-0 font-display text-4xl font-bold tracking-[-0.035em]">{copy.title}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{copy.lede}</p>
        <nav className="mt-6 flex flex-wrap gap-2 border-b border-border pb-3">
          {(
            [
              ["overview", copy.tabOverview],
              ["users", copy.tabUsers],
              ["models", copy.tabModels],
              ["channels", copy.tabChannels],
              ["plans", copy.tabPlans],
            ] as const
          ).map(([value, label]) => (
            <Button key={value} variant={tab === value ? "default" : "ghost"} onClick={() => setTab(value)}>
              {label}
            </Button>
          ))}
          <Button variant="outline" className="ml-auto" onClick={() => void refresh()} disabled={loading}>
            {loading ? copy.loading : copy.refresh}
          </Button>
        </nav>
        {error && <p className="mt-4 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">{error}</p>}
        {loading && !overview ? (
          <p className="mt-8 text-sm text-muted-foreground">{copy.loading}</p>
        ) : tab === "overview" && overview ? (
          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {(
              [
                [copy.users, overview.users],
                [copy.admins, overview.admins],
                [copy.subscriptions, overview.subscriptions],
                [copy.models, overview.models],
                [copy.channels, overview.channels],
                [copy.orders, overview.orders],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className={card}>
                <p className="m-0 text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
                <p className="mt-2 font-display text-3xl font-semibold">{value}</p>
              </div>
            ))}
          </div>
        ) : tab === "users" ? (
          <UsersPanel
            copy={copy}
            users={users}
            plans={plans}
            selected={selected}
            query={query}
            onQuery={setQuery}
            onSearch={search}
            onSelect={selectUser}
            onChanged={(next) => {
              setSelected(next);
              void refresh();
            }}
            onFailure={(failure) => setError(failureText(failure, copy, locale))}
          />
        ) : tab === "models" ? (
          <ModelsPanel
            copy={copy}
            models={models}
            onChanged={() => void refresh()}
            onFailure={(failure) => setError(failureText(failure, copy, locale))}
          />
        ) : tab === "channels" ? (
          <ChannelsPanel
            copy={copy}
            models={models}
            channels={channels}
            onChanged={() => void refresh()}
            onFailure={(failure) => setError(failureText(failure, copy, locale))}
          />
        ) : (
          <PlansPanel
            copy={copy}
            plans={plans}
            onChanged={() => void refresh()}
            onFailure={(failure) => setError(failureText(failure, copy, locale))}
          />
        )}
      </div>
    </section>
  );
}

function UsersPanel({
  copy,
  users,
  plans,
  selected,
  query,
  onQuery,
  onSearch,
  onSelect,
  onChanged,
  onFailure,
}: {
  copy: Messages["admin"];
  users: AdminUser[];
  plans: AdminPlan[];
  selected: AdminUser | null;
  query: string;
  onQuery: (value: string) => void;
  onSearch: (event: FormEvent) => void;
  onSelect: (id: string) => void;
  onChanged: (user: AdminUser) => void;
  onFailure: (failure: unknown) => void;
}) {
  const [credits, setCredits] = useState("100");
  const [days, setDays] = useState("30");
  const [note, setNote] = useState("");
  const [plan, setPlan] = useState(plans[0]?.slug ?? "");
  const [busy, setBusy] = useState("");

  const role = async () => {
    if (!selected) return;
    setBusy("role");
    try {
      onChanged((await cloudAdmin.setRole(selected.id, selected.role === "admin" ? "member" : "admin")).user);
    } catch (failure) {
      onFailure(failure);
    } finally {
      setBusy("");
    }
  };
  const gift = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    setBusy("gift");
    try {
      onChanged((await cloudAdmin.gift(selected.id, Number(credits), Number(days), note)).user);
    } catch (failure) {
      onFailure(failure);
    } finally {
      setBusy("");
    }
  };
  const subscribe = async () => {
    if (!selected || !plan) return;
    setBusy("subscribe");
    try {
      onChanged((await cloudAdmin.subscribe(selected.id, plan)).user);
    } catch (failure) {
      onFailure(failure);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
      <div className={card}>
        <form className="flex gap-2" onSubmit={onSearch}>
          <Input value={query} onChange={(event) => onQuery(event.target.value)} placeholder={copy.searchUsers} />
          <Button type="submit" variant="outline">{copy.search}</Button>
        </form>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-[13px]">
            <thead className="text-xs text-muted-foreground">
              <tr><th className="pb-2">{copy.users}</th><th className="pb-2">{copy.role}</th><th className="pb-2">{copy.credits}</th><th className="pb-2">{copy.plan}</th></tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="cursor-pointer border-t border-border hover:bg-secondary/40" onClick={() => onSelect(user.id)}>
                  <td className="py-3">
                    <strong className="block font-medium">{user.display_name || user.handle || user.email || user.phone}</strong>
                    <small className="text-muted-foreground">{user.email || user.phone || user.id}</small>
                  </td>
                  <td className="py-3">{user.role}{user.official ? ` · ${copy.official}` : ""}</td>
                  <td className="py-3">{user.credits}</td>
                  <td className="py-3">{user.subscription?.name || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {users.length === 0 && <p className="mt-4 text-sm text-muted-foreground">{copy.noUsers}</p>}
        </div>
      </div>
      <div className={card}>
        {!selected ? (
          <p className="m-0 text-sm text-muted-foreground">{copy.selectUser}</p>
        ) : (
          <div className="grid gap-4">
            <div>
              <p className="m-0 font-semibold">{selected.display_name || selected.handle || selected.email || selected.phone}</p>
              <p className="mt-1 text-xs text-muted-foreground">{selected.email || selected.phone || selected.id}</p>
              <p className="mt-2 text-xs text-muted-foreground">
                {selected.role} · {copy.credits} {selected.credits} · {selected.mfa_enabled ? copy.mfaOn : copy.passwordSet}
              </p>
            </div>
            <Button variant="outline" onClick={() => void role()} disabled={Boolean(busy)}>
              {selected.role === "admin" ? copy.removeAdmin : copy.makeAdmin}
            </Button>
            <p className="m-0 text-sm">
              {copy.plan}: {selected.subscription ? `${selected.subscription.name} (${date(selected.subscription.ends_at)})` : copy.noPlan}
            </p>
            <div className="flex flex-wrap gap-2">
              <Select value={plan} onValueChange={setPlan}>
                <SelectTrigger className="h-10"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {plans.map((one) => <SelectItem key={one.slug} value={one.slug}>{one.name}</SelectItem>)}
                </SelectContent>
              </Select>
              <Button variant="outline" onClick={() => void subscribe()} disabled={!plan || Boolean(busy)}>{copy.subscribe}</Button>
            </div>
            <form className="grid gap-3" onSubmit={gift}>
              <strong className="text-sm">{copy.giftCredits}</strong>
              <Label className={field}>{copy.credits}<Input value={credits} onChange={(event) => setCredits(event.target.value)} /></Label>
              <Label className={field}>{copy.days}<Input value={days} onChange={(event) => setDays(event.target.value)} /></Label>
              <Label className={field}>{copy.note}<Input value={note} onChange={(event) => setNote(event.target.value)} /></Label>
              <Button type="submit" disabled={Boolean(busy)}>{copy.grant}</Button>
            </form>
            {selected.credit_batches && (
              <div className="text-xs text-muted-foreground">
                {selected.credit_batches.map((batch, index) => (
                  <p key={`${batch.expires_at}-${index}`} className="m-0">{batch.remaining} · {batch.source} · {date(batch.expires_at)}</p>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ModelsPanel({
  copy,
  models,
  onChanged,
  onFailure,
}: {
  copy: Messages["admin"];
  models: AdminModel[];
  onChanged: () => void;
  onFailure: (failure: unknown) => void;
}) {
  const [form, setForm] = useState({ id: "", label: "", max: "8000", sort: "0", enabled: true });
  const [selected, setSelected] = useState<AdminModel | null>(null);
  const [price, setPrice] = useState({ input: "0", output: "0", from: "" });
  const [prices, setPrices] = useState<{ input_per_1k: number; output_per_1k: number; effective_from: string }[]>([]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await cloudAdmin.createModel({
        id: form.id.trim(),
        label: form.label.trim(),
        max_output_tokens: Number(form.max),
        sort_order: Number(form.sort),
        enabled: form.enabled,
      });
      setForm({ id: "", label: "", max: "8000", sort: "0", enabled: true });
      onChanged();
    } catch (failure) {
      onFailure(failure);
    }
  };
  const open = async (model: AdminModel) => {
    setSelected(model);
    try {
      setPrices((await cloudAdmin.prices(model.id)).prices);
    } catch (failure) {
      onFailure(failure);
    }
  };
  const addPrice = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    try {
      await cloudAdmin.addPrice(selected.id, Number(price.input), Number(price.output), price.from || undefined);
      setPrice({ input: "0", output: "0", from: "" });
      setPrices((await cloudAdmin.prices(selected.id)).prices);
      onChanged();
    } catch (failure) {
      onFailure(failure);
    }
  };

  return (
    <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.8fr)]">
      <div className={card}>
        <h2 className="m-0 text-lg font-semibold">{copy.tabModels}</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-[13px]">
            <thead className="text-xs text-muted-foreground">
              <tr><th className="pb-2">{copy.id}</th><th className="pb-2">{copy.currentPrice}</th><th className="pb-2">{copy.channelsCount}</th><th className="pb-2">{copy.listed}</th></tr>
            </thead>
            <tbody>
              {models.map((model) => (
                <tr key={model.id} className="cursor-pointer border-t border-border hover:bg-secondary/40" onClick={() => void open(model)}>
                  <td className="py-3"><strong className="block font-medium">{model.id}</strong><small className="text-muted-foreground">{model.label}</small></td>
                  <td className="py-3">{model.current_price ? `${model.current_price.input_per_1k} / ${model.current_price.output_per_1k}` : copy.noPrice}</td>
                  <td className="py-3">{model.active_channel_count}/{model.channel_count}</td>
                  <td className="py-3">{model.listed ? copy.listed : model.not_listed_reasons.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className={card}>
        <h2 className="m-0 text-lg font-semibold">{copy.addModel}</h2>
        <form className="mt-3 grid gap-3" onSubmit={create}>
          <Label className={field}>{copy.id}<Input value={form.id} onChange={(event) => setForm({ ...form, id: event.target.value })} /></Label>
          <Label className={field}>{copy.label}<Input value={form.label} onChange={(event) => setForm({ ...form, label: event.target.value })} /></Label>
          <Label className={field}>{copy.maxOutput}<Input value={form.max} onChange={(event) => setForm({ ...form, max: event.target.value })} /></Label>
          <Label className={field}>{copy.sort}<Input value={form.sort} onChange={(event) => setForm({ ...form, sort: event.target.value })} /></Label>
          <Button type="submit">{copy.create}</Button>
        </form>
        {selected && (
          <form className="mt-6 grid gap-3 border-t border-border pt-4" onSubmit={addPrice}>
            <strong className="text-sm">{selected.id} · {copy.addPrice}</strong>
            <Label className={field}>{copy.inputPer1k}<Input value={price.input} onChange={(event) => setPrice({ ...price, input: event.target.value })} /></Label>
            <Label className={field}>{copy.outputPer1k}<Input value={price.output} onChange={(event) => setPrice({ ...price, output: event.target.value })} /></Label>
            <Label className={field}>{copy.effectiveFrom}<Input value={price.from} onChange={(event) => setPrice({ ...price, from: event.target.value })} /></Label>
            <Button type="submit">{copy.addPrice}</Button>
            {prices.map((one) => <p key={one.effective_from} className="m-0 text-xs text-muted-foreground">{one.input_per_1k} / {one.output_per_1k} · {date(one.effective_from)}</p>)}
          </form>
        )}
      </div>
    </div>
  );
}

function ChannelsPanel({
  copy,
  models,
  channels,
  onChanged,
  onFailure,
}: {
  copy: Messages["admin"];
  models: AdminModel[];
  channels: AdminChannel[];
  onChanged: () => void;
  onFailure: (failure: unknown) => void;
}) {
  const [form, setForm] = useState({ model: "", base: "", upstream: "", key: "", priority: "0", note: "" });
  const modelId = form.model || models[0]?.id || "";
  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await cloudAdmin.createChannel({
        model_id: modelId,
        base_url: form.base.trim(),
        upstream_model: form.upstream.trim(),
        api_key: form.key,
        priority: Number(form.priority),
        note: form.note,
      });
      setForm({ ...form, base: "", upstream: "", key: "", note: "" });
      onChanged();
    } catch (failure) {
      onFailure(failure);
    }
  };
  return (
    <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
      <div className={card}>
        <h2 className="m-0 text-lg font-semibold">{copy.tabChannels}</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-[13px]">
            <thead className="text-xs text-muted-foreground">
              <tr><th className="pb-2">{copy.id}</th><th className="pb-2">{copy.baseUrl}</th><th className="pb-2">{copy.priority}</th><th className="pb-2">{copy.apiKey}</th></tr>
            </thead>
            <tbody>
              {channels.map((channel) => (
                <tr key={channel.id} className="border-t border-border">
                  <td className="py-3"><strong className="block font-medium">{channel.model_id}</strong><small className="text-muted-foreground">{channel.upstream_model}</small></td>
                  <td className="py-3">{channel.base_url}</td>
                  <td className="py-3">{channel.priority} · {channel.enabled ? "on" : "off"}</td>
                  <td className="py-3">{channel.has_api_key ? copy.hasKey : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className={card}>
        <h2 className="m-0 text-lg font-semibold">{copy.addChannel}</h2>
        <form className="mt-3 grid gap-3" onSubmit={create}>
          <Label className={field}>{copy.models}<Select value={modelId} onValueChange={(value) => setForm({ ...form, model: value })}>
            <SelectTrigger className="h-10"><SelectValue /></SelectTrigger>
            <SelectContent>
              {models.map((one) => <SelectItem key={one.id} value={one.id}>{one.id}</SelectItem>)}
            </SelectContent>
          </Select></Label>
          <Label className={field}>{copy.baseUrl}<Input value={form.base} onChange={(event) => setForm({ ...form, base: event.target.value })} /></Label>
          <Label className={field}>{copy.upstreamModel}<Input value={form.upstream} onChange={(event) => setForm({ ...form, upstream: event.target.value })} /></Label>
          <Label className={field}>{copy.apiKey}<Input type="password" value={form.key} onChange={(event) => setForm({ ...form, key: event.target.value })} /></Label>
          <Label className={field}>{copy.priority}<Input value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value })} /></Label>
          <p className="m-0 text-xs text-muted-foreground">{copy.apiKeyHint}</p>
          <Button type="submit">{copy.create}</Button>
        </form>
      </div>
    </div>
  );
}

function PlansPanel({
  copy,
  plans,
  onChanged,
  onFailure,
}: {
  copy: Messages["admin"];
  plans: AdminPlan[];
  onChanged: () => void;
  onFailure: (failure: unknown) => void;
}) {
  const [form, setForm] = useState({ slug: "", name: "", period: "month", credits: "1000", ttl: "60", price: "" });
  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await cloudAdmin.createPlan({
        slug: form.slug,
        name: form.name,
        period: form.period as AdminPlan["period"],
        monthly_credits: Number(form.credits),
        credit_ttl_days: Number(form.ttl),
        on_sale: Boolean(form.price),
        price_cents: form.price ? Number(form.price) : null,
      });
      setForm({ slug: "", name: "", period: "month", credits: "1000", ttl: "60", price: "" });
      onChanged();
    } catch (failure) {
      onFailure(failure);
    }
  };
  return (
    <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
      <div className={card}>
        <h2 className="m-0 text-lg font-semibold">{copy.tabPlans}</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-[13px]">
            <thead className="text-xs text-muted-foreground">
              <tr><th className="pb-2">{copy.slug}</th><th className="pb-2">{copy.monthlyCredits}</th><th className="pb-2">{copy.priceCents}</th><th className="pb-2">{copy.onSale}</th></tr>
            </thead>
            <tbody>
              {plans.map((plan) => (
                <tr key={plan.slug} className="border-t border-border">
                  <td className="py-3"><strong className="block font-medium">{plan.slug}</strong><small className="text-muted-foreground">{plan.name}</small></td>
                  <td className="py-3">{plan.monthly_credits} · {plan.period}</td>
                  <td className="py-3">{money(plan.price_cents)}</td>
                  <td className="py-3">{plan.on_sale ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className={card}>
        <h2 className="m-0 text-lg font-semibold">{copy.addPlan}</h2>
        <form className="mt-3 grid gap-3" onSubmit={create}>
          <Label className={field}>{copy.slug}<Input value={form.slug} onChange={(event) => setForm({ ...form, slug: event.target.value })} /></Label>
          <Label className={field}>{copy.label}<Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Label>
          <Label className={field}>{copy.period}<Select value={form.period} onValueChange={(value) => setForm({ ...form, period: value })}>
            <SelectTrigger className="h-10"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="month">{copy.month}</SelectItem>
              <SelectItem value="quarter">{copy.quarter}</SelectItem>
              <SelectItem value="year">{copy.year}</SelectItem>
            </SelectContent>
          </Select></Label>
          <Label className={field}>{copy.monthlyCredits}<Input value={form.credits} onChange={(event) => setForm({ ...form, credits: event.target.value })} /></Label>
          <Label className={field}>{copy.ttlDays}<Input value={form.ttl} onChange={(event) => setForm({ ...form, ttl: event.target.value })} /></Label>
          <Label className={field}>{copy.priceCents}<Input value={form.price} onChange={(event) => setForm({ ...form, price: event.target.value })} /></Label>
          <Button type="submit">{copy.create}</Button>
        </form>
      </div>
    </div>
  );
}
