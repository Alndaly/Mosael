import React from "react";
import { Clock, Info, LayoutGrid, List, Pencil, Search, Trash2 } from "lucide-react";

import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { BulkCheckbox, type useBulkSelection } from "@/components/app/bulkSelection";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { cn } from "@/lib/utils";

type PricingRule = components["schemas"]["ProviderPricingRuleOut"];

/**
 * 成本规则的浏览:**按模型成组**,可筛、可搜,卡片 / 列表两种看法。
 *
 * 此前是一条规则一行 —— 一个对话模型就是输入、输出、缓存三四行,预填一次几百行,整页只能
 * 往下翻,找某个模型全靠眼睛。而用户心里的单位是「这个模型怎么收钱」,不是「这一条规则」。
 * 所以同一连接、同一模型、同一能力的几条规则收成一组:一张卡片(或一行)把它的各项价格
 * 一起列出来,编辑 / 删除仍落在单条价格上。
 */
export type RuleGroup = {
  key: string;
  profileId: string | null;
  provider: string;
  model: string;
  capability: string;
  rules: PricingRule[];
};

export type RuleFilters = { query: string; profile: string; capability: string; source: string; currency: string };
export const EMPTY_FILTERS: RuleFilters = { query: "", profile: "", capability: "", source: "", currency: "" };
/** 筛选里「不挂连接的通用规则」那一项。空串已经表示「不筛」,所以要另一个值。 */
export const NO_PROFILE = "__none__";

export function groupRules(rules: PricingRule[], unitOrder: readonly string[]): RuleGroup[] {
  const groups = new Map<string, RuleGroup>();
  for (const rule of rules) {
    const key = [rule.provider_profile_id ?? "", rule.provider, rule.model, rule.capability].join("\u0000");
    let group = groups.get(key);
    if (!group) {
      group = { key, profileId: rule.provider_profile_id ?? null, provider: rule.provider, model: rule.model, capability: rule.capability, rules: [] };
      groups.set(key, group);
    }
    group.rules.push(rule);
  }
  const rank = (unit: string) => {
    const index = unitOrder.indexOf(unit);
    return index < 0 ? unitOrder.length : index;
  };
  for (const group of groups.values()) group.rules.sort((a, b) => rank(a.billing_unit) - rank(b.billing_unit));
  return [...groups.values()];
}

export function filterGroups(groups: RuleGroup[], filters: RuleFilters, profileName: (group: RuleGroup) => string): RuleGroup[] {
  const needle = filters.query.trim().toLowerCase();
  return groups.filter((group) => {
    if (filters.profile === NO_PROFILE ? group.profileId !== null : filters.profile && group.profileId !== filters.profile) return false;
    if (filters.capability && group.capability !== filters.capability) return false;
    if (filters.source && !group.rules.some((rule) => rule.source === filters.source)) return false;
    if (filters.currency && !group.rules.some((rule) => rule.currency === filters.currency)) return false;
    if (!needle) return true;
    const haystack = [group.model, group.provider, profileName(group), ...group.rules.map((rule) => rule.notes ?? "")].join("\n").toLowerCase();
    return haystack.includes(needle);
  });
}

type Labels = {
  profileName: (group: RuleGroup) => string;
  capabilityLabel: (capability: string) => string;
  unitLabel: (unit: string) => string;
  amount: (rule: PricingRule) => string;
  schedule: (rule: PricingRule) => string;
};

/** 顶上那一行:搜索、四个筛选、计数、视图切换。筛选项只列**实际出现过**的值 —— 列一堆选了必然为空的选项是噪音。 */
export function PricingRuleFilters({
  groups,
  filters,
  onChange,
  display,
  onDisplay,
  shown,
  labels,
}: {
  groups: RuleGroup[];
  filters: RuleFilters;
  onChange: (next: RuleFilters) => void;
  display: "grid" | "list";
  onDisplay: (next: "grid" | "list") => void;
  shown: number;
  labels: Labels;
}) {
  const t = useI18n();
  const distinct = <T,>(values: T[]) => [...new Set(values)];
  const profiles = distinct(groups.map((group) => group.profileId));
  const set = (patch: Partial<RuleFilters>) => onChange({ ...filters, ...patch });
  const filtered = JSON.stringify(filters) !== JSON.stringify(EMPTY_FILTERS);
  const ruleCount = groups.reduce((sum, group) => sum + group.rules.length, 0);
  // **和素材库那一行同一套刻度**:标准高度的输入框和下拉(border-border bg-control),视图切换是
  // 标准尺寸的描边按钮。此前这里用了 h-8 + 小一号的字,和系统里别的筛选栏、设置表单比矮一截。
  const picker = "w-auto min-w-36 max-w-52 border-border bg-control";
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            className="border-border bg-control pl-9"
            value={filters.query}
            placeholder={t("pricingSearch")}
            aria-label={t("pricingSearch")}
            onChange={(event) => set({ query: event.target.value })}
          />
        </div>
        <OptionPicker
          className={picker}
          ariaLabel={t("pricingProviderProfile")}
          value={filters.profile || "all"}
          onChange={(value) => set({ profile: value === "all" ? "" : value })}
          options={[
            { value: "all", label: t("pricingFilterAllProviders") },
            ...profiles.map((id) => {
              const sample = groups.find((group) => group.profileId === id)!;
              return { value: id ?? NO_PROFILE, label: id ? labels.profileName(sample) : t("pricingAnyProvider") };
            }),
          ]}
        />
        <OptionPicker
          className={picker}
          ariaLabel={t("pricingCapability")}
          value={filters.capability || "all"}
          onChange={(value) => set({ capability: value === "all" ? "" : value })}
          options={[
            { value: "all", label: t("pricingFilterAllCapabilities") },
            ...distinct(groups.map((group) => group.capability)).map((capability) => ({ value: capability, label: labels.capabilityLabel(capability) })),
          ]}
        />
        <OptionPicker
          className={picker}
          ariaLabel={t("pricingSourceLabel")}
          value={filters.source || "all"}
          onChange={(value) => set({ source: value === "all" ? "" : value })}
          options={[
            { value: "all", label: t("pricingFilterAllSources") },
            ...distinct(groups.flatMap((group) => group.rules.map((rule) => rule.source))).map((source) => ({ value: source, label: sourceLabel(t, source) })),
          ]}
        />
        <OptionPicker
          className={picker}
          ariaLabel={t("pricingCurrency")}
          value={filters.currency || "all"}
          onChange={(value) => set({ currency: value === "all" ? "" : value })}
          options={[
            { value: "all", label: t("pricingFilterAllCurrencies") },
            ...distinct(groups.flatMap((group) => group.rules.map((rule) => rule.currency))).map((currency) => ({ value: currency, label: currency })),
          ]}
        />
        <div className="ml-auto flex items-center gap-1" role="group" aria-label={t("pricingViewLabel")}>
          <Button
            variant="outline"
            className={cn("px-3", display === "grid" && "border-primary/40 bg-accent text-primary")}
            aria-label={t("studioGridView")}
            title={t("studioGridView")}
            aria-pressed={display === "grid"}
            onClick={() => onDisplay("grid")}
          >
            <LayoutGrid />
          </Button>
          <Button
            variant="outline"
            className={cn("px-3", display === "list" && "border-primary/40 bg-accent text-primary")}
            aria-label={t("studioListView")}
            title={t("studioListView")}
            aria-pressed={display === "list"}
            onClick={() => onDisplay("list")}
          >
            <List />
          </Button>
        </div>
      </div>
      <div className="flex items-center gap-2 text-ui-sm text-muted-foreground">
        <span>
          {filtered
            ? t("pricingCountFiltered").replace("{shown}", String(shown)).replace("{models}", String(groups.length))
            : t("pricingCount").replace("{models}", String(groups.length)).replace("{rules}", String(ruleCount))}
        </span>
        {filtered && (
          <button type="button" className="text-primary hover:underline" onClick={() => onChange(EMPTY_FILTERS)}>
            {t("pricingClearFilters")}
          </button>
        )}
      </div>
    </div>
  );
}

export function sourceLabel(t: ReturnType<typeof useI18n>, source: string): string {
  if (source === "catalog") return t("pricingSource_catalog");
  if (source === "reference") return t("pricingSource_reference");
  return t("pricingSource_manual");
}

/** 一组的若干条价格。每一条单独可改、可删 —— 组只是看法,规则仍是一条一条存的。 */
function PriceLines({ group, labels, onEdit, onDelete, dense }: {
  group: RuleGroup;
  labels: Labels;
  onEdit: (rule: PricingRule) => void;
  onDelete: (rule: PricingRule) => void;
  dense?: boolean;
}) {
  const t = useI18n();
  return (
    <ul className={cn("m-0 grid list-none p-0", dense ? "gap-0.5" : "gap-1")}>
      {group.rules.map((rule) => (
        <li key={rule.id} className="group/price grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-2 rounded-md px-1.5 py-1 hover:bg-secondary/60">
          <span className="min-w-0 truncate text-ui-xs text-muted-foreground">{labels.unitLabel(rule.billing_unit)}</span>
          <span className="whitespace-nowrap text-ui-sm font-medium tabular-nums">{labels.amount(rule)}</span>
          {/* 动作悬停 / 键盘聚焦时才出现,触屏上常驻 —— 一张卡四条价格各顶两个图标就成了一片按钮。 */}
          <span className="flex items-center opacity-0 transition-opacity group-hover/price:opacity-100 focus-within:opacity-100 [@media(hover:none)]:opacity-100">
            <Button size="icon-xs" variant="ghost" aria-label={`${t("pricingRuleEdit")}: ${labels.unitLabel(rule.billing_unit)}`} title={t("pricingRuleEdit")} onClick={() => onEdit(rule)}>
              <Pencil />
            </Button>
            <Button size="icon-xs" variant="ghost" aria-label={`${t("delete")}: ${labels.unitLabel(rule.billing_unit)}`} title={t("delete")} onClick={() => onDelete(rule)}>
              <Trash2 />
            </Button>
          </span>
          {rule.time_prices?.length ? (
            <small className="col-span-3 text-ui-2xs text-muted-foreground tabular-nums">{labels.schedule(rule)}</small>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function SourceBadges({ group, align = "end" }: { group: RuleGroup; align?: "start" | "end" }) {
  const t = useI18n();
  const sources = [...new Set(group.rules.map((rule) => rule.source))];
  return (
    <span className={cn("flex shrink-0 flex-wrap gap-1", align === "end" ? "justify-end" : "justify-start")}>
      {sources.map((source) => (
        <em
          key={source}
          className={cn(
            "rounded-full px-1.5 text-ui-2xs not-italic leading-5",
            source === "manual" ? "bg-secondary text-muted-foreground" : "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary",
          )}
        >
          {sourceLabel(t, source)}
        </em>
      ))}
    </span>
  );
}

/** 备注里常带着出处链接,整段折成一两行;悬停看全文。 */
function Notes({ group }: { group: RuleGroup }) {
  const notes = [...new Set(group.rules.map((rule) => rule.notes).filter(Boolean))];
  if (!notes.length) return null;
  const text = notes.join("\n");
  return (
    <p className="m-0 line-clamp-2 break-words text-ui-2xs leading-[1.5] text-muted-foreground" title={text}>
      {notes.join(" · ")}
    </p>
  );
}

export function PricingRuleGroups({
  groups,
  display,
  bulk,
  labels,
  onEdit,
  onDelete,
  onDeleteGroup,
}: {
  groups: RuleGroup[];
  display: "grid" | "list";
  bulk: ReturnType<typeof useBulkSelection<RuleGroup>>;
  labels: Labels;
  onEdit: (rule: PricingRule) => void;
  onDelete: (rule: PricingRule) => void;
  onDeleteGroup: (group: RuleGroup) => void;
}) {
  const t = useI18n();
  const title = (group: RuleGroup) => group.model || t("pricingAnyModel");
  const subtitle = (group: RuleGroup) => `${labels.capabilityLabel(group.capability)} · ${labels.profileName(group)}`;
  const deleteGroupButton = (group: RuleGroup) => (
    <Button size="icon-xs" variant="ghost" aria-label={`${t("pricingDeleteGroup")}: ${title(group)}`} title={t("pricingDeleteGroup")} onClick={() => onDeleteGroup(group)}>
      <Trash2 />
    </Button>
  );

  if (display === "list") {
    // **列表是一张紧凑的表**:一个模型一行,价格压成一排小块(点一块就改那一条),备注收进一个
    // 提示图标。此前列表模式是把卡片摊平 —— 单位和金额隔着半屏、出处链接占两三行、删除键孤零零
    // 挂在最右,一行有卡片三行那么高,既不比卡片看得多,也不比卡片好扫。
    return (
      <div className="grid divide-y divide-divider">
        {groups.map((group) => {
          const notes = [...new Set(group.rules.map((rule) => rule.notes).filter(Boolean))].join("\n");
          return (
            <div
              key={group.key}
              className={cn(
                "grid items-center gap-x-4 gap-y-2 px-1 py-2.5",
                bulk.active ? "grid-cols-[auto_minmax(10rem,15rem)_minmax(0,1fr)_auto]" : "grid-cols-[minmax(10rem,15rem)_minmax(0,1fr)_auto]",
                bulk.isSelected(group.key) && "rounded-md bg-[color-mix(in_srgb,var(--primary)_7%,transparent)]",
              )}
            >
              {bulk.active && <BulkCheckbox checked={bulk.isSelected(group.key)} onToggle={(event) => bulk.toggle(group.key, event)} label={t("bulkSelectRow")} />}
              <div className="grid min-w-0 gap-0.5">
                <strong className="truncate text-ui-sm font-semibold" title={title(group)}>{title(group)}</strong>
                <small className="truncate text-ui-xs text-muted-foreground">{subtitle(group)}</small>
              </div>
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                {group.rules.map((rule) => (
                  <button
                    key={rule.id}
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded-md border border-border bg-control px-2 py-1 text-left transition-colors hover:border-primary/40 hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={`${t("pricingRuleEdit")}: ${labels.unitLabel(rule.billing_unit)}`}
                    title={rule.time_prices?.length ? labels.schedule(rule) : t("pricingRuleEdit")}
                    onClick={() => onEdit(rule)}
                  >
                    <span className="text-ui-xs text-muted-foreground">{labels.unitLabel(rule.billing_unit)}</span>
                    <span className="text-ui-sm font-medium tabular-nums">{labels.amount(rule)}</span>
                    {rule.time_prices?.length ? <Clock size={12} className="text-primary" aria-label={labels.schedule(rule)} /> : null}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-1">
                <SourceBadges group={group} />
                {notes ? (
                  <span className="grid size-7 place-items-center text-muted-foreground" title={notes} aria-label={notes} role="img">
                    <Info size={14} />
                  </span>
                ) : null}
                {deleteGroupButton(group)}
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,280px),1fr))] content-start gap-3">
      {groups.map((group) => (
        <article
          key={group.key}
          className={cn(
            "grid min-w-0 content-start gap-3 rounded-lg border border-border bg-panel p-4",
            bulk.isSelected(group.key) && "border-primary/50 bg-[color-mix(in_srgb,var(--primary)_5%,var(--panel))]",
          )}
        >
          <header className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
            <div className="flex min-w-0 items-start gap-2">
              {bulk.active && <BulkCheckbox checked={bulk.isSelected(group.key)} onToggle={(event) => bulk.toggle(group.key, event)} label={t("bulkSelectRow")} />}
              <div className="grid min-w-0 gap-0.5">
                <strong className="truncate text-ui-md font-semibold" title={title(group)}>{title(group)}</strong>
                <small className="truncate text-ui-xs text-muted-foreground">{subtitle(group)}</small>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <SourceBadges group={group} />
              {deleteGroupButton(group)}
            </div>
          </header>
          <PriceLines group={group} labels={labels} onEdit={onEdit} onDelete={onDelete} />
          <Notes group={group} />
        </article>
      ))}
    </div>
  );
}
