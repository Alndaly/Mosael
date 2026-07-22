import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, ReceiptText, Trash2 } from "lucide-react";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ModalShell } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type PricingRule = components["schemas"]["ProviderPricingRuleOut"];

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

const CAPABILITY_KEYS = ["chat", "image", "video", "tts", "podcast", "embedding"] as const;
const BILLING_UNITS = [
  "request",
  "image",
  "video_second",
  "audio_second",
  "character",
  "token",
  "input_token",
  "output_token",
  "million_token",
  "million_input_token",
  "million_output_token",
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
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState<PricingRule | null>(null);
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
        <Button variant="outline" size="sm" onClick={openCreate}>
          <Plus size={13} /> {t("pricingRuleAdd")}
        </Button>
      }
    >
      <ModalShell
        open={adding || editing !== null}
        onOpenChange={(next) => !next && closeModal()}
        title={editing ? t("pricingRuleEdit") : t("pricingRuleAdd")}
      >
        <form
          className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-secondary [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none"
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
                {CAPABILITY_KEYS.map((capability) => (
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
                  model: current.model || profile?.default_model || "",
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
                    {profile.name} · {profile.default_model || profile.vendor}
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
          <div className="mt-1 flex justify-end gap-1.5">
            <Button type="button" variant="outline" size="sm" onClick={closeModal}>
              {t("cancel")}
            </Button>
            <Button type="submit" size="sm" disabled={!canSubmit || create.isPending || update.isPending}>
              {editing ? t("save") : t("pricingRuleAdd")}
            </Button>
          </div>
        </form>
      </ModalShell>

      <SettingsBlock>
        <div className="grid gap-1.5">
          {(rules.data ?? []).map((rule) => (
            <div className="grid grid-cols-[28px_minmax(0,1fr)_auto_auto] items-center gap-2 rounded-md border border-border bg-panel px-2 py-1.5" key={rule.id}>
              <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-foreground">
                <ReceiptText size={13} />
              </span>
              <div className="min-w-0 [&_small]:block [&_small]:truncate [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-[13px] [&_strong]:font-semibold">
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
                <Button variant="ghost" size="icon" onClick={() => remove.mutate(rule.id)} aria-label={t("delete")}>
                  <Trash2 size={13} />
                </Button>
              </div>
            </div>
          ))}
          {rules.data && rules.data.length === 0 && <p className="m-0 text-xs text-muted-foreground">{t("pricingRulesEmpty")}</p>}
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}
