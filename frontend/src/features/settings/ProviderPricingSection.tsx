import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, ReceiptText, Sparkles, Trash2 } from "lucide-react";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog, DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { BulkActionBar, BulkCheckbox, BulkSelectTrigger, useBulkSelection } from "@/components/app/bulkSelection";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { OptionPicker } from "@/components/ui/option-picker";
import { Textarea } from "@/components/ui/textarea";
import { SettingsEmpty, SettingsGroup, SettingsListBlock, SettingsListItem } from "@/components/settings/settings-layout";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

import {
  TimePricesEditor,
  amountToMicros,
  draftsFromApi,
  draftsToApi,
  localTimeZone,
  microsToAmount,
  useScheduleSummary,
  type WindowDraft,
} from "./PricingTimePrices";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type PricingRule = components["schemas"]["ProviderPricingRuleOut"];
type PrefillResult = components["schemas"]["PricingPrefillOut"];
type PrefillOutcome = { profileId: string; result: PrefillResult; error?: undefined } | { profileId: string; error: string; result?: undefined };

/** 仍未定价的模型最多列这么多个,其余折成「等 N 个」—— 一个中转挂几百个模型时,整串列出来没法读。 */
const UNPRICED_PREVIEW = 8;

type PricingForm = {
  providerProfileId: string;
  capability: string;
  model: string;
  billingUnit: string;
  unitAmount: string;
  currency: string;
  notes: string;
  /** 分时段价格(空 = 全天按单价计)。 */
  timeWindows: WindowDraft[];
  timeZone: string;
};

const ANY_PROFILE = "__any_profile__";
const DEFAULT_FORM: PricingForm = {
  providerProfileId: ANY_PROFILE,
  capability: "chat",
  model: "",
  billingUnit: "token",
  unitAmount: "",
  currency: "USD",
  notes: "",
  timeWindows: [],
  timeZone: "",
};

/** 能力清单**从后端预设取并集**,不在这里手抄第六遍。手抄的代价刚兑现过:模型设置弹窗里那份
 *  漏了 embedding,于是它在列表行上有标签、在弹窗里连格子都没有。 */
function useAllCapabilities(): string[] {
  const presets = useQuery({
    queryKey: ["provider-vendors"],
    queryFn: () => api<components["schemas"]["VendorPresetOut"][]>("/api/settings/provider-vendors"),
    staleTime: 300_000,
  });
  return React.useMemo(() => {
    const union: string[] = [];
    for (const preset of presets.data ?? []) {
      for (const id of preset.capability_ids ?? []) if (!union.includes(id)) union.push(id);
    }
    return union;
  }, [presets.data]);
}
const BILLING_UNITS = [
  "request",
  "image",
  "video",
  "video_second",
  "audio_second",
  "character",
  "token",
  "input_token",
  "output_token",
  // 缓存读/写是独立的桶(供应商的 prompt_tokens 含缓存,而适配器上报前已减掉),单价也完全
  // 不同 —— 缓存读约为输入价一成,缓存写约 1.25 倍。不给它们单独的单位就只能少算。
  "cache_read_token",
  "cache_write_token",
  "million_token",
  "million_input_token",
  "million_output_token",
  "million_cache_read_token",
  "million_cache_write_token",
] as const;
const CAPABILITY_LABELS: Record<string, MessageKey> = {
  chat: "capChat",
  image: "capImage",
  video: "capVideo",
  tts: "capTts",
  podcast: "capPodcast",
  embedding: "capEmbedding",
};
const UNIT_LABELS: Record<string, MessageKey> = {
  request: "pricingUnit_request",
  image: "pricingUnit_image",
  video: "pricingUnit_video",
  video_second: "pricingUnit_video_second",
  audio_second: "pricingUnit_audio_second",
  character: "pricingUnit_character",
  token: "pricingUnit_token",
  input_token: "pricingUnit_input_token",
  output_token: "pricingUnit_output_token",
  million_token: "pricingUnit_million_token",
  million_input_token: "pricingUnit_million_input_token",
  million_output_token: "pricingUnit_million_output_token",
  cache_read_token: "pricingUnit_cache_read_token",
  cache_write_token: "pricingUnit_cache_write_token",
  million_cache_read_token: "pricingUnit_million_cache_read_token",
  million_cache_write_token: "pricingUnit_million_cache_write_token",
};

function formatRuleAmount(rule: PricingRule, unitLabel: string): string {
  return `${microsToAmount(rule.unit_amount_micros)} ${rule.currency} / ${unitLabel}`;
}

function formFromRule(rule: PricingRule): PricingForm {
  return {
    providerProfileId: rule.provider_profile_id || ANY_PROFILE,
    capability: rule.capability,
    model: rule.model || "",
    billingUnit: rule.billing_unit,
    unitAmount: microsToAmount(rule.unit_amount_micros),
    currency: rule.currency || "USD",
    notes: rule.notes || "",
    timeWindows: draftsFromApi(rule.time_prices),
    timeZone: rule.time_zone || "",
  };
}

/** 一家的预填结果:建了几条、各从哪来,以及**还剩哪些模型没价** —— 那才是用户接下来要做的事。 */
function PrefillSummary({ result }: { result: PrefillResult }) {
  const t = useI18n();
  const unpriced = result.unpriced_models;
  const shown = unpriced.slice(0, UNPRICED_PREVIEW).join(", ") + (unpriced.length > UNPRICED_PREVIEW ? " …" : "");
  return (
    <>
      {(result.created > 0 ? t("pricingPrefillDone") : t("pricingPrefillNone"))
        .replace("{created}", String(result.created))
        .replace("{catalog}", String(result.created_from_catalog))
        .replace("{reference}", String(result.created_from_reference))
        .replace("{priced}", String(result.models_with_price))
        .replace("{seen}", String(result.models_seen))}
      {result.created_with_time_prices > 0 && (
        <span className="block">{t("pricingPrefillTimed").replace("{n}", String(result.created_with_time_prices))}</span>
      )}
      {unpriced.length > 0 ? (
        <span className="block text-muted-foreground">
          {t("pricingPrefillUnpriced").replace("{count}", String(unpriced.length)).replace("{models}", shown)}
        </span>
      ) : result.models_seen > 0 ? (
        <span className="block text-muted-foreground">{t("pricingPrefillAllPriced")}</span>
      ) : null}
    </>
  );
}

export function ProviderPricingSection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const pricingFormId = React.useId();
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState<PricingRule | null>(null);
  const allCapabilities = useAllCapabilities();
  const [adding, setAdding] = React.useState(false);
  const [form, setForm] = React.useState<PricingForm>(DEFAULT_FORM);

  const profiles = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
  });
  const rules = useQuery({
    queryKey: ["provider-pricing-rules", workspace.id],
    queryFn: () => api<PricingRule[]>(`/api/settings/provider-pricing-rules?workspace_id=${encodeURIComponent(workspace.id)}`),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["provider-pricing-rules", workspace.id] });
    void qc.invalidateQueries({ queryKey: ["workspace-summary", workspace.id] });
  };

  const closeModal = () => {
    setAdding(false);
    setEditing(null);
    setForm(DEFAULT_FORM);
  };

  const openCreate = () => {
    setEditing(null);
    setForm(DEFAULT_FORM);
    setAdding(true);
  };

  const openEdit = (rule: PricingRule) => {
    setAdding(false);
    setEditing(rule);
    setForm(formFromRule(rule));
  };

  const selectedProfile = (profiles.data ?? []).find((profile) => profile.id === form.providerProfileId);
  const visibleProfiles = React.useMemo(() => {
    return (profiles.data ?? []).filter((profile) => (profile.capability_ids ?? []).includes(form.capability));
  }, [form.capability, profiles.data]);

  React.useEffect(() => {
    if (form.providerProfileId === ANY_PROFILE) return;
    if (visibleProfiles.some((profile) => profile.id === form.providerProfileId)) return;
    setForm((current) => ({ ...current, providerProfileId: ANY_PROFILE }));
  }, [form.providerProfileId, visibleProfiles]);

  const payload = () => ({
    workspace_id: workspace.id,
    provider_profile_id: form.providerProfileId === ANY_PROFILE ? null : form.providerProfileId,
    provider: selectedProfile?.vendor ?? "",
    capability: form.capability,
    model: form.model.trim(),
    billing_unit: form.billingUnit,
    unit_amount_micros: amountToMicros(form.unitAmount),
    currency: form.currency.trim().toUpperCase() || "USD",
    source: "manual",
    notes: form.notes.trim(),
    time_prices: draftsToApi(form.timeWindows),
    time_zone: form.timeWindows.length > 0 ? form.timeZone : "",
  });

  const create = useMutation({
    mutationFn: () =>
      api<PricingRule>("/api/settings/provider-pricing-rules", {
        method: "POST",
        body: JSON.stringify(payload()),
      }),
    onSuccess: () => {
      closeModal();
      refresh();
    },
  });

  const update = useMutation({
    mutationFn: () =>
      api<PricingRule>(`/api/settings/provider-pricing-rules/${editing?.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload()),
      }),
    onSuccess: () => {
      closeModal();
      refresh();
    },
  });

  // 删一条也要确认:批量删有确认框,单条却一点就没,而且没有撤销。
  const [deleting, setDeleting] = React.useState<PricingRule | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/settings/provider-pricing-rules/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleting(null);
      refresh();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  /* 批量选择:「按目录预填」一次能生成几十条规则,发现填错了逐条删要点几十次。
     用户的动作本来就是"把这一批去掉",界面得给得出这个动作。 */
  const ruleList = rules.data ?? [];
  const bulk = useBulkSelection(ruleList, (rule) => rule.id);
  const [bulkDeleting, setBulkDeleting] = React.useState(false);
  const removeMany = useMutation({
    mutationFn: async (ids: string[]) => {
      // 逐条发但一次性回报结果:后端没有批量删接口,而为了一个设置页列表去加一个
      // 破坏性的批量端点不划算。失败的那几条要单独说出来,不能被"已删除 N 项"盖过去。
      const results = await Promise.allSettled(
        ids.map((id) => api(`/api/settings/provider-pricing-rules/${id}`, { method: "DELETE" })),
      );
      return { ok: results.filter((r) => r.status === "fulfilled").length, failed: results.filter((r) => r.status === "rejected").length };
    },
    onSuccess: ({ ok, failed }) => {
      bulk.clear();
      setBulkDeleting(false);
      refresh();
      if (failed) toast.error(t("bulkPartialFailed").replace("{ok}", String(ok)).replace("{failed}", String(failed)));
      else toast.success(t("bulkDeleteDone").replace("{n}", String(ok)));
    },
  });

  /** 预填价格:省掉几十上百个模型的手抄。目录报价优先,官方价目表补缺;只补缺失的,已填的一律不动(后端保证)。 */
  const [prefillOpen, setPrefillOpen] = React.useState(false);
  // 结果按连接各记一份、按跑的先后排:几个供应商挨个点下来(或「全部预填」一口气跑完),
  // 一句不带名字的「没有新建规则」说不清在说谁,后一家的结果也不该把前一家的冲掉。
  const [prefillResults, setPrefillResults] = React.useState<PrefillOutcome[]>([]);
  const [prefillingAll, setPrefillingAll] = React.useState(false);
  const recordPrefill = (outcome: PrefillOutcome) =>
    setPrefillResults((current) => [...current.filter((item) => item.profileId !== outcome.profileId), outcome]);
  const prefill = useMutation({
    mutationFn: (profileId: string) =>
      api<PrefillResult>(`/api/settings/providers/${profileId}/pricing/prefill`, { method: "POST" }),
    onSuccess: (result, profileId) => {
      recordPrefill({ profileId, result });
      refresh();
    },
    // 失败也记在那一家名下,不弹 toast:「全部预填」时一家没配密钥不该打断其余几家,
    // 也不该连弹一串提示。
    onError: (e: Error, profileId) => recordPrefill({ profileId, error: e.message }),
  });
  /** 一键全部:**挨个跑**,不并发 —— 每家都要现取一次目录,并发只会让慢的那家拖住所有人的超时;
   *  挨个跑还能让「正在跑哪一家」始终只有一行在转。 */
  const prefillAll = async () => {
    setPrefillingAll(true);
    setPrefillResults([]);
    try {
      for (const profile of profiles.data ?? []) {
        await prefill.mutateAsync(profile.id).catch(() => undefined);
      }
    } finally {
      setPrefillingAll(false);
    }
  };
  const prefillBusy = prefill.isPending || prefillingAll;

  const profileLabel = (profileId: string | null | undefined, provider: string) => {
    const profile = (profiles.data ?? []).find((item) => item.id === profileId);
    if (profile) return profile.name;
    return provider || t("pricingAnyProvider");
  };
  const scheduleSummary = useScheduleSummary();
  /** 加第一个时段时预选的时区:这家已有规则里用的那个(预填的 DeepSeek 规则是北京时间),否则本机时区。
   *  不在前端再抄一份「哪家用哪个时区」—— 价目表在后端,规则里已经带着。 */
  const vendorTimeZone = React.useMemo(() => {
    const vendor = selectedProfile?.vendor;
    const known = vendor ? ruleList.find((rule) => rule.provider === vendor && rule.time_zone) : undefined;
    return known?.time_zone || localTimeZone();
  }, [ruleList, selectedProfile?.vendor]);
  const capabilityLabel = (capability: string) => t(CAPABILITY_LABELS[capability] ?? "capChat");
  const unitLabel = (unit: string) => t(UNIT_LABELS[unit] ?? "pricingUnit_request");
  const canSubmit = amountToMicros(form.unitAmount) >= 0 && form.capability && form.billingUnit && form.currency.trim();

  return (
    <SettingsGroup
      title={t("pricingRulesTitle")}
      description={t("pricingRulesDesc")}
      contentClassName={rules.data && ruleList.length === 0 ? "min-h-0" : undefined}
      actions={
        <div className="flex items-center gap-1.5">
          <BulkSelectTrigger active={bulk.active} onEnter={bulk.enter} disabled={ruleList.length === 0} />
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setPrefillResults([]);
              setPrefillOpen(true);
            }}
            title={t("pricingPrefillHint")}
          >
            <Sparkles size={13} /> {t("pricingPrefill")}
          </Button>
          <Button variant="outline" size="sm" onClick={openCreate}>
            <Plus size={13} /> {t("pricingRuleAdd")}
          </Button>
        </div>
      }
    >
      <ModalShell
        open={prefillOpen}
        onOpenChange={setPrefillOpen}
        title={t("pricingPrefill")}
        footer={
          <>
            <Button type="button" variant="outline" size="sm" onClick={() => setPrefillOpen(false)}>{t("close")}</Button>
            <Button
              type="button"
              size="sm"
              loading={prefillingAll}
              disabled={prefillBusy || (profiles.data ?? []).length === 0}
              onClick={() => void prefillAll()}
            >
              <Sparkles size={13} /> {t("pricingPrefillAll")}
            </Button>
          </>
        }
      >
        <div className="grid gap-2.5">
          <p className="m-0 text-ui-xs leading-[1.5] text-muted-foreground">{t("pricingPrefillHint")}</p>
          <div className="grid gap-1.5">
            {(profiles.data ?? []).map((profile) => (
              <Button
                key={profile.id}
                type="button"
                variant="outline"
                size="sm"
                className="justify-start"
                // **只转点的那一行。** 此前所有行共用一个 isPending,点一家,整列一起转圈变灰,
                // 看起来像是全部在跑、又像是全坏了。其余行在请求期间只是按不动。
                loading={prefill.isPending && prefill.variables === profile.id}
                disabled={prefillBusy && prefill.variables !== profile.id}
                onClick={() => prefill.mutate(profile.id)}
              >
                {profile.name}
              </Button>
            ))}
          </div>
          {prefillResults.length > 0 && (
            <ul className="m-0 grid list-none gap-1.5 p-0">
              {prefillResults.map((outcome) => (
                <li key={outcome.profileId} className="text-ui-xs leading-[1.5] text-foreground">
                  <strong className="font-medium">
                    {t("pricingPrefillResultFor").replace("{name}", (profiles.data ?? []).find((p) => p.id === outcome.profileId)?.name ?? "")}
                  </strong>
                  {outcome.error !== undefined ? (
                    <span className="text-destructive">{outcome.error}</span>
                  ) : (
                    <PrefillSummary result={outcome.result} />
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </ModalShell>
      <ModalShell
        open={adding || editing !== null}
        onOpenChange={(next) => !next && closeModal()}
        title={editing ? t("pricingRuleEdit") : t("pricingRuleAdd")}
        footer={
          <>
            <Button type="button" variant="outline" size="sm" onClick={closeModal}>{t("cancel")}</Button>
            <Button type="submit" form={pricingFormId} size="sm" disabled={!canSubmit || create.isPending || update.isPending}>
              {editing ? t("save") : t("pricingRuleAdd")}
            </Button>
          </>
        }
      >
        <form
          id={pricingFormId}
          // 字段一律用 DIALOG_FIELD:此前是整个 <label> 带 font-semibold,里面的下拉、输入框、备注
          // 全都继承成粗体 —— 该加粗的只有字段标题那一行。
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit) return;
            if (editing) update.mutate();
            else create.mutate();
          }}
        >
          <label className={DIALOG_FIELD}>
            <span>{t("pricingCapability")}</span>
            <Select value={form.capability} onValueChange={(value) => setForm((current) => ({ ...current, capability: value }))}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {allCapabilities.map((capability) => (
                  <SelectItem key={capability} value={capability}>
                    {capabilityLabel(capability)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className={DIALOG_FIELD}>
            <span>{t("pricingProviderProfile")}</span>
            <OptionPicker
              value={form.providerProfileId}
              onChange={(value) =>
                setForm((current) => ({ ...current, providerProfileId: value, model: current.model }))
              }
              options={[
                { value: ANY_PROFILE, label: t("pricingAnyProvider") },
                ...visibleProfiles.map((profile) => ({
                  value: profile.id,
                  label: `${profile.name} · ${profile.vendor}`,
                  keywords: [profile.vendor],
                })),
              ]}
            />
          </label>
          <label className={DIALOG_FIELD}>
            <span>{t("pricingModel")}</span>
            <Input
              value={form.model}
              placeholder={t("pricingModelPlaceholder")}
              onChange={(event) => setForm((current) => ({ ...current, model: event.target.value }))}
            />
          </label>
          <div className="grid grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_96px] gap-2">
            <label className={DIALOG_FIELD}>
              <span>{t("pricingBillingUnit")}</span>
              <Select value={form.billingUnit} onValueChange={(value) => setForm((current) => ({ ...current, billingUnit: value }))}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BILLING_UNITS.map((unit) => (
                    <SelectItem key={unit} value={unit}>
                      {unitLabel(unit)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className={DIALOG_FIELD}>
              <span>{t("pricingUnitAmount")}</span>
              <Input
                type="number"
                min="0"
                step="0.000001"
                value={form.unitAmount}
                placeholder="0.000000"
                onChange={(event) => setForm((current) => ({ ...current, unitAmount: event.target.value }))}
              />
            </label>
            <label className={DIALOG_FIELD}>
              <span>{t("pricingCurrency")}</span>
              <Input
                value={form.currency}
                maxLength={8}
                onChange={(event) => setForm((current) => ({ ...current, currency: event.target.value.toUpperCase() }))}
              />
            </label>
          </div>
          <TimePricesEditor
            windows={form.timeWindows}
            timeZone={form.timeZone}
            defaultTimeZone={vendorTimeZone}
            baseAmount={form.unitAmount}
            onChange={({ windows, timeZone }) => setForm((current) => ({ ...current, timeWindows: windows, timeZone }))}
          />
          <label className={DIALOG_FIELD}>
            <span>{t("pricingNotes")}</span>
            <Textarea
              rows={3}
              value={form.notes}
              placeholder={t("pricingNotesPlaceholder")}
              onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
            />
          </label>
        </form>
      </ModalShell>

      <ConfirmDialog
        open={deleting !== null}
        title={t("pricingRuleDeleteTitle")}
        body={deleting ? `${capabilityLabel(deleting.capability)} · ${profileLabel(deleting.provider_profile_id, deleting.provider)} · ${deleting.model || t("pricingAnyModel")} · ${formatRuleAmount(deleting, unitLabel(deleting.billing_unit))}` : undefined}
        confirmLabel={t("delete")}
        onCancel={() => setDeleting(null)}
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
      <ConfirmDialog
        open={bulkDeleting}
        title={t("bulkDeleteConfirm").replace("{n}", String(bulk.count))}
        body={t("bulkDeleteConfirmBody").replace("{n}", String(bulk.count))}
        onCancel={() => setBulkDeleting(false)}
        pending={removeMany.isPending}
        onConfirm={() => removeMany.mutate(bulk.selectedIds)}
      />

      {rules.data && ruleList.length === 0 ? (
        <SettingsEmpty icon={<ReceiptText size={20} />} title={t("pricingRulesEmpty")} />
      ) : (
        <SettingsListBlock
          toolbar={bulk.active ? (
            <BulkActionBar active={bulk.active} count={bulk.count} allSelected={bulk.allSelected} onToggleAll={bulk.toggleAll} onExit={bulk.exit}>
              <Button variant="outline" size="sm" loading={removeMany.isPending} onClick={() => setBulkDeleting(true)}>
                <Trash2 size={12} /> {t("bulkDelete")}
              </Button>
            </BulkActionBar>
          ) : undefined}
        >
          {ruleList.map((rule) => (
            <SettingsListItem
              className={cn(
                "grid items-center gap-2",
                bulk.active ? "grid-cols-[auto_28px_minmax(0,1fr)_auto_auto]" : "grid-cols-[28px_minmax(0,1fr)_auto_auto]",
                bulk.isSelected(rule.id) && "rounded-md bg-[color-mix(in_srgb,var(--primary)_7%,transparent)]",
              )}
              key={rule.id}
            >
              {bulk.active && (
                <BulkCheckbox
                  checked={bulk.isSelected(rule.id)}
                  onToggle={(event) => bulk.toggle(rule.id, event)}
                  label={t("bulkSelectRow")}
                />
              )}
              <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-foreground">
                <ReceiptText size={13} />
              </span>
              <div className="min-w-0 [&_small]:block [&_small]:truncate [&_small]:text-ui-xs [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-ui-md [&_strong]:font-semibold">
                <strong>
                  {capabilityLabel(rule.capability)} · {profileLabel(rule.provider_profile_id, rule.provider)}
                </strong>
                <small>
                  {rule.model || t("pricingAnyModel")} · {formatRuleAmount(rule, unitLabel(rule.billing_unit))}
                  {rule.time_prices?.length ? ` · ${scheduleSummary(rule.time_prices, rule.time_zone ?? "")}` : ""}
                  {rule.notes ? ` · ${rule.notes}` : ""}
                </small>
              </div>
              <span className="whitespace-nowrap text-xs text-muted-foreground">{formatRuleAmount(rule, unitLabel(rule.billing_unit))}</span>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" onClick={() => openEdit(rule)} aria-label={t("pricingRuleEdit")}>
                  <Pencil size={13} />
                </Button>
                <Button variant="ghost" size="icon" onClick={() => setDeleting(rule)} aria-label={t("delete")}>
                  <Trash2 size={13} />
                </Button>
              </div>
            </SettingsListItem>
          ))}
        </SettingsListBlock>
      )}
    </SettingsGroup>
  );
}
