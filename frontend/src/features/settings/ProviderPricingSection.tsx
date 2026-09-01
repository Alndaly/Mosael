import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, ReceiptText, Sparkles, Trash2 } from "lucide-react";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import type { MessageKey } from "@/app/messages";
import { EmptyState } from "@/components/layout/EmptyState";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { BulkActionBar, BulkCheckbox, BulkSelectTrigger, useBulkSelection } from "@/components/app/bulkSelection";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { SettingsBlock, SettingsGroup, SettingsList, SettingsListItem } from "@/features/settings/ui";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type PricingRule = components["schemas"]["ProviderPricingRuleOut"];
type PrefillResult = components["schemas"]["PricingPrefillOut"];

type PricingForm = {
  providerProfileId: string;
  capability: string;
  model: string;
  billingUnit: string;
  unitAmount: string;
  currency: string;
  notes: string;
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

function microsToAmount(value: number): string {
  const amount = value / 1_000_000;
  return Number.isInteger(amount) ? String(amount) : String(Number(amount.toFixed(6)));
}

function amountToMicros(value: string): number {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount < 0) return 0;
  return Math.round(amount * 1_000_000);
}

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
  };
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

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/settings/provider-pricing-rules/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
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

  /** 按目录预填:省掉几十上百个模型的手抄。只补缺失的,已填的一律不动(后端保证)。 */
  const [prefillOpen, setPrefillOpen] = React.useState(false);
  const [prefillResult, setPrefillResult] = React.useState<PrefillResult | null>(null);
  const prefill = useMutation({
    mutationFn: (profileId: string) =>
      api<PrefillResult>(`/api/settings/providers/${profileId}/pricing/prefill`, { method: "POST" }),
    onSuccess: (result) => {
      setPrefillResult(result);
      refresh();
    },
  });

  const profileLabel = (profileId: string | null | undefined, provider: string) => {
    const profile = (profiles.data ?? []).find((item) => item.id === profileId);
    if (profile) return profile.name;
    return provider || t("pricingAnyProvider");
  };
  const capabilityLabel = (capability: string) => t(CAPABILITY_LABELS[capability] ?? "capChat");
  const unitLabel = (unit: string) => t(UNIT_LABELS[unit] ?? "pricingUnit_request");
  const canSubmit = amountToMicros(form.unitAmount) >= 0 && form.capability && form.billingUnit && form.currency.trim();

  return (
    <SettingsGroup
      title={t("pricingRulesTitle")}
      description={t("pricingRulesDesc")}
      actions={
        <div className="flex items-center gap-1.5">
          <BulkSelectTrigger active={bulk.active} onEnter={bulk.enter} disabled={ruleList.length === 0} />
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setPrefillResult(null);
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
        footer={<Button type="button" variant="outline" size="sm" onClick={() => setPrefillOpen(false)}>{t("close")}</Button>}
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
                loading={prefill.isPending}
                onClick={() => prefill.mutate(profile.id)}
              >
                {profile.name}
              </Button>
            ))}
          </div>
          {prefillResult && (
            <p className="m-0 text-ui-xs leading-[1.5] text-foreground">
              {(prefillResult.created > 0 ? t("pricingPrefillDone") : t("pricingPrefillNone"))
                .replace("{created}", String(prefillResult.created))
                .replace("{priced}", String(prefillResult.models_with_price))
                .replace("{seen}", String(prefillResult.models_seen))}
            </p>
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
          className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit) return;
            if (editing) update.mutate();
            else create.mutate();
          }}
        >
          <label className="grid gap-1.5 text-xs font-semibold text-foreground">
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
          <label className="grid gap-1.5 text-xs font-semibold text-foreground">
            <span>{t("pricingProviderProfile")}</span>
            <Select
              value={form.providerProfileId}
              onValueChange={(value) => {
                const profile = (profiles.data ?? []).find((item) => item.id === value);
                setForm((current) => ({
                  ...current,
                  providerProfileId: value,
                  model: current.model,
                }));
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY_PROFILE}>{t("pricingAnyProvider")}</SelectItem>
                {visibleProfiles.map((profile) => (
                  <SelectItem key={profile.id} value={profile.id}>
                    {profile.name} · {profile.vendor}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label className="grid gap-1.5 text-xs font-semibold text-foreground">
            <span>{t("pricingModel")}</span>
            <Input
              value={form.model}
              placeholder={t("pricingModelPlaceholder")}
              onChange={(event) => setForm((current) => ({ ...current, model: event.target.value }))}
            />
          </label>
          <div className="grid grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_96px] gap-2">
            <label className="grid gap-1.5 text-xs font-semibold text-foreground">
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
            <label className="grid gap-1.5 text-xs font-semibold text-foreground">
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
            <label className="grid gap-1.5 text-xs font-semibold text-foreground">
              <span>{t("pricingCurrency")}</span>
              <Input
                value={form.currency}
                maxLength={8}
                onChange={(event) => setForm((current) => ({ ...current, currency: event.target.value.toUpperCase() }))}
              />
            </label>
          </div>
          <label className="grid gap-1.5 text-xs font-semibold text-foreground">
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
        open={bulkDeleting}
        title={t("bulkDeleteConfirm").replace("{n}", String(bulk.count))}
        body={t("bulkDeleteConfirmBody").replace("{n}", String(bulk.count))}
        onCancel={() => setBulkDeleting(false)}
        onConfirm={() => removeMany.mutate(bulk.selectedIds)}
      />

      <SettingsBlock>
        <div className="grid gap-1.5">
          <BulkActionBar active={bulk.active} count={bulk.count} allSelected={bulk.allSelected} onToggleAll={bulk.toggleAll} onExit={bulk.exit}>
            <Button variant="outline" size="sm" loading={removeMany.isPending} onClick={() => setBulkDeleting(true)}>
              <Trash2 size={12} /> {t("bulkDelete")}
            </Button>
          </BulkActionBar>
          <SettingsList>
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
                  {rule.notes ? ` · ${rule.notes}` : ""}
                </small>
              </div>
              <span className="whitespace-nowrap text-xs text-muted-foreground">{formatRuleAmount(rule, unitLabel(rule.billing_unit))}</span>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" onClick={() => openEdit(rule)} aria-label={t("pricingRuleEdit")}>
                  <Pencil size={13} />
                </Button>
                <Button variant="ghost" size="icon" loading={remove.isPending && remove.variables === rule.id} onClick={() => remove.mutate(rule.id)} aria-label={t("delete")}>
                  <Trash2 size={13} />
                </Button>
              </div>
              </SettingsListItem>
            ))}
          </SettingsList>
          {rules.data && ruleList.length === 0 && (
            <EmptyState size="compact" icon={<ReceiptText size={15} />} title={t("pricingRulesEmpty")} />
          )}
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}
