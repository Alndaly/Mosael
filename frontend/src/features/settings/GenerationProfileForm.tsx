/**
 * 自定义参数组的**语义化表单** —— 不写 JSON。
 *
 * 结构由后端 `/api/generation/capability-profile-schema` 驱动(34 个字段的键/形状/分组,
 * 见 backend domain/generation/custom_profiles.py):加一个字段只改后端一处,这个表单自动
 * 长出对应控件。这里**只有形状渲染器,没有字段知识** —— 字段知识抄过来一份,就会在加字段时
 * 悄悄漏掉,而那正是这个仓库一直在消灭的那种沉默。
 *
 * 渐进披露:可调参数先勾,可选值与默认值跟着勾出来的参数出现;上限与高级字段经「添加字段」
 * 按需请出来 —— 三十几个控件一次铺开,比 JSON 好不了多少。
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

type Schema = components["schemas"]["CapabilityProfileSchemaOut"];
type Descriptor = Record<string, unknown>;

const LIST_FOR_DEFAULT: Record<string, string> = {
  default_size: "sizes",
  default_resolution: "resolutions",
  default_aspect_ratio: "aspect_ratios",
};

/** 声明可调参数 → 它的可选值清单字段。只勾了参数、清单却空着,界面照样没有旋钮。 */
const LIST_FOR_PARAMETER: Record<string, string> = {
  size: "sizes",
  resolution: "resolutions",
  aspect_ratio: "aspect_ratios",
  duration_seconds: "duration_seconds",
};

function useSchema() {
  return useQuery({
    queryKey: ["capability-profile-schema"],
    queryFn: () => api<Schema>("/api/generation/capability-profile-schema"),
    staleTime: 10 * 60_000,
  });
}

/** 一串值的碎屑编辑器:回车添加,× 移除。numeric 时只收正整数。 */
function Chips({
  values,
  onChange,
  numeric,
  ariaLabel,
}: {
  values: Array<string | number>;
  onChange: (next: Array<string | number>) => void;
  numeric?: boolean;
  ariaLabel: string;
}) {
  const [text, setText] = React.useState("");
  const commit = () => {
    const raw = text.trim();
    if (!raw) return;
    if (numeric) {
      const value = Number(raw);
      if (!Number.isInteger(value) || value <= 0) return;
      if (!values.includes(value)) onChange([...values, value]);
    } else if (!values.includes(raw)) {
      onChange([...values, raw]);
    }
    setText("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1 rounded-md border border-border bg-panel px-2 py-1.5">
      {values.map((value) => (
        <span key={String(value)} className="flex items-center gap-0.5 rounded bg-secondary px-1.5 py-px text-ui-xs text-foreground">
          {String(value)}
          <button
            type="button"
            aria-label={`${ariaLabel} ${value}`}
            className="cursor-pointer text-muted-foreground hover:text-foreground"
            onClick={() => onChange(values.filter((one) => one !== value))}
          >
            <X size={11} />
          </button>
        </span>
      ))}
      <input
        value={text}
        aria-label={ariaLabel}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
        onBlur={commit}
        className="min-w-16 flex-1 border-0 bg-transparent p-0 text-ui-xs text-foreground outline-none"
      />
    </div>
  );
}

/** 「名字 → 一串值」或「名字 → 一个数」的行式编辑器(source_limits / parameter_choices 那几种)。 */
function MapRows({
  entries,
  onChange,
  names,
  valueKind,
  addLabel,
  ariaLabel,
}: {
  entries: Array<[string, unknown]>;
  onChange: (next: Array<[string, unknown]>) => void;
  /** 名字一列的候选(素材角色、已勾参数…)。可手输,候选只是少打字。 */
  names: string[];
  valueKind: "number" | "chips" | "int_chips";
  addLabel: string;
  ariaLabel: string;
}) {
  const setEntry = (index: number, entry: [string, unknown]) =>
    onChange(entries.map((one, i) => (i === index ? entry : one)));
  return (
    <div className="grid gap-1.5">
      {entries.map(([name, value], index) => (
        <div key={index} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-1.5">
          <div className="grid gap-1">
            <input
              value={name}
              list={`${ariaLabel}-names`}
              aria-label={ariaLabel}
              placeholder={ariaLabel}
              onChange={(event) => setEntry(index, [event.target.value, value])}
              className="h-7 w-full rounded-md border border-border bg-panel px-2 text-ui-xs text-foreground outline-none focus:border-primary"
            />
            {valueKind === "number" ? (
              <Input
                type="number"
                min={1}
                value={typeof value === "number" ? value : ""}
                aria-label={`${ariaLabel} ${name}`}
                onChange={(event) => setEntry(index, [name, Number(event.target.value) || 0])}
                className="h-7 bg-panel text-ui-xs"
              />
            ) : (
              <Chips
                values={Array.isArray(value) ? (value as Array<string | number>) : []}
                numeric={valueKind === "int_chips"}
                ariaLabel={`${ariaLabel} ${name}`}
                onChange={(next) => setEntry(index, [name, next])}
              />
            )}
          </div>
          <Button variant="ghost" size="icon-xs" aria-label={`${ariaLabel} ×`} onClick={() => onChange(entries.filter((_, i) => i !== index))}>
            <X size={12} />
          </Button>
        </div>
      ))}
      <datalist id={`${ariaLabel}-names`}>
        {names.map((one) => (
          <option key={one} value={one} />
        ))}
      </datalist>
      <Button variant="ghost" size="sm" className="justify-self-start text-muted-foreground" onClick={() => onChange([...entries, ["", valueKind === "number" ? 1 : []]])}>
        <Plus size={12} /> {addLabel}
      </Button>
    </div>
  );
}

function Field({ label, children, onRemove }: { label: string; children: React.ReactNode; onRemove?: () => void }) {
  return (
    <div className="grid gap-1">
      <span className="flex items-center justify-between text-ui-xs font-medium text-muted-foreground">
        {label}
        {onRemove && (
          <button type="button" aria-label={`${label} ×`} className="cursor-pointer text-faint hover:text-foreground" onClick={onRemove}>
            <X size={11} />
          </button>
        )}
      </span>
      {children}
    </div>
  );
}

export function CapabilityProfileForm({
  value,
  onChange,
}: {
  value: Descriptor;
  onChange: (next: Descriptor) => void;
}) {
  const t = useI18n();
  const schema = useSchema();
  const fields = schema.data?.fields ?? [];
  const shapeOf = (key: string) => fields.find((field) => field.key === key)?.shape ?? "";
  /* 键名由后端 schema 驱动,翻译键跟着拼 —— t 的键是静态联合类型,这里必须断言一次:
     后端加字段时 messages.ts 的 genField_* 要同步加(缺了界面就露出原始键名,看得见)。 */
  const labelOf = (key: string) => t(`genField_${key}` as Parameters<typeof t>[0]);

  const parameters = (value.parameter_keys as string[] | undefined) ?? [];
  const set = (key: string, next: unknown) => onChange({ ...value, [key]: next });
  const unset = (key: string) => {
    const next = { ...value };
    delete next[key];
    onChange(next);
  };
  const toggleParameter = (parameter: string) =>
    set(
      "parameter_keys",
      parameters.includes(parameter)
        ? parameters.filter((one) => one !== parameter)
        : [...parameters, parameter],
    );

  /* 上限与高级组:还没设值的字段进「添加字段」菜单,设了的排出来可移除。 */
  const secondary = fields.filter((field) => field.group === "limits" || field.group === "advanced");
  const activeSecondary = secondary.filter((field) => value[field.key] !== undefined);
  const idleSecondary = secondary.filter((field) => value[field.key] === undefined);

  const renderGeneric = (key: string) => {
    const shape = shapeOf(key);
    const current = value[key];
    if (shape === "str_list" || shape === "int_list") {
      return (
        <Chips
          values={Array.isArray(current) ? (current as Array<string | number>) : []}
          numeric={shape === "int_list"}
          ariaLabel={labelOf(key)}
          onChange={(next) => (next.length ? set(key, next) : unset(key))}
        />
      );
    }
    if (shape === "positive_int" || shape === "int") {
      return (
        <Input
          type="number"
          min={1}
          value={typeof current === "number" ? current : ""}
          aria-label={labelOf(key)}
          onChange={(event) => set(key, Number(event.target.value) || undefined)}
          className="h-8 bg-panel text-ui-sm"
        />
      );
    }
    if (shape === "bool") {
      return <Switch checked={current === true} aria-label={labelOf(key)} onCheckedChange={(next) => set(key, next)} />;
    }
    if (shape === "str") {
      return (
        <Input
          value={typeof current === "string" ? current : ""}
          aria-label={labelOf(key)}
          onChange={(event) => set(key, event.target.value)}
          className="h-8 bg-panel text-ui-sm"
        />
      );
    }
    if (shape === "str_to_int" || shape === "str_to_str_list" || shape === "str_to_int_list" || shape === "str_list_list") {
      const isMap = shape !== "str_list_list";
      const entries = isMap
        ? Object.entries((current as Record<string, unknown> | undefined) ?? {})
        : ((current as unknown[] | undefined) ?? []).map((group) => ["", group] as [string, unknown]);
      const names =
        key === "parameter_choices" ? parameters
        : key === "duration_by_resolution" ? ((value.resolutions as string[] | undefined) ?? [])
        : (schema.data?.source_roles ?? []);
      const commit = (next: Array<[string, unknown]>) => {
        if (isMap) {
          const obj = Object.fromEntries(next.filter(([name]) => name.trim()));
          Object.keys(obj).length ? set(key, obj) : unset(key);
        } else {
          const groups = next.map(([, group]) => group).filter((group) => Array.isArray(group) && group.length);
          groups.length ? set(key, groups) : unset(key);
        }
      };
      return (
        <MapRows
          entries={entries}
          names={names}
          valueKind={shape === "str_to_int" ? "number" : shape === "str_to_int_list" ? "int_chips" : "chips"}
          addLabel={t("genFormAddRow")}
          ariaLabel={labelOf(key)}
          onChange={commit}
        />
      );
    }
    return null;
  };

  return (
    <div className="grid gap-4">
      {/* 可调参数:只勾这个端点真会接受的 —— 勾了它不收,请求发出去被供应商拒掉。 */}
      <Field label={t("genField_parameter_keys")}>
        <div className="flex flex-wrap gap-1">
          {(schema.data?.parameters ?? []).map((parameter) => (
            <button
              key={parameter}
              type="button"
              onClick={() => toggleParameter(parameter)}
              className={cn(
                "cursor-pointer rounded-md border px-1.5 py-0.5 text-ui-xs transition-colors",
                parameters.includes(parameter)
                  ? "border-primary bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-foreground"
                  : "border-border bg-panel text-muted-foreground hover:text-foreground",
              )}
            >
              {parameter}
            </button>
          ))}
        </div>
      </Field>

      {/* 可选值:跟着勾出来的参数出现。 */}
      {parameters.some((parameter) => LIST_FOR_PARAMETER[parameter]) && (
        <div className="grid gap-2.5 border-t border-border pt-3">
          <span className="text-ui-xs font-semibold text-foreground">{t("genGroup_choices")}</span>
          {parameters.map((parameter) => {
            const listKey = LIST_FOR_PARAMETER[parameter];
            if (!listKey) return null;
            return (
              <Field key={listKey} label={labelOf(listKey)}>
                <Chips
                  values={(value[listKey] as Array<string | number> | undefined) ?? []}
                  numeric={listKey === "duration_seconds"}
                  ariaLabel={labelOf(listKey)}
                  onChange={(next) => (next.length ? set(listKey, next) : unset(listKey))}
                />
              </Field>
            );
          })}
          <Field label={labelOf("parameter_choices")}>{renderGeneric("parameter_choices")}</Field>
        </div>
      )}

      {/* 默认值:清单型给下拉(只能选清单里的,选不回来的值不存在),其余给输入。 */}
      {Object.entries(LIST_FOR_DEFAULT).some(([, listKey]) => Array.isArray(value[listKey]) && (value[listKey] as unknown[]).length > 0) && (
        <div className="grid gap-2.5 border-t border-border pt-3">
          <span className="text-ui-xs font-semibold text-foreground">{t("genGroup_defaults")}</span>
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(LIST_FOR_DEFAULT).map(([defaultKey, listKey]) => {
              const options = (value[listKey] as string[] | undefined) ?? [];
              if (options.length === 0) return null;
              return (
                <Field key={defaultKey} label={labelOf(defaultKey)}>
                  <OptionPicker
                    ariaLabel={labelOf(defaultKey)}
                    value={typeof value[defaultKey] === "string" ? (value[defaultKey] as string) : options[0]}
                    onChange={(next) => set(defaultKey, next)}
                    options={options.map((one) => ({ value: one, label: one }))}
                  />
                </Field>
              );
            })}
            {parameters.includes("duration_seconds") && (
              <Field label={labelOf("default_duration_seconds")}>{renderGeneric("default_duration_seconds")}</Field>
            )}
            {(["generate_audio", "prompt_extend"] as const)
              .filter((parameter) => parameters.includes(parameter))
              .map((parameter) => (
                <Field key={parameter} label={labelOf(`default_${parameter}`)}>
                  {renderGeneric(`default_${parameter}`)}
                </Field>
              ))}
          </div>
        </div>
      )}

      {/* 上限与高级:按需请出来,不一次铺开。 */}
      {(activeSecondary.length > 0 || idleSecondary.length > 0) && (
        <div className="grid gap-2.5 border-t border-border pt-3">
          <span className="text-ui-xs font-semibold text-foreground">{t("genGroup_limits")}</span>
          {activeSecondary.map((field) => (
            <Field key={field.key} label={labelOf(field.key)} onRemove={() => unset(field.key)}>
              {renderGeneric(field.key)}
            </Field>
          ))}
          {idleSecondary.length > 0 && (
            <OptionPicker
              ariaLabel={t("genFormAddField")}
              value=""
              onChange={(key) => {
                if (key) set(key, initialFor(shapeOf(key)));
              }}
              options={idleSecondary.map((field) => ({ value: field.key, label: labelOf(field.key) }))}
              contentClassName="max-w-[min(420px,calc(100vw-32px))]"
            />
          )}
        </div>
      )}
    </div>
  );
}

function initialFor(shape: string): unknown {
  if (shape === "str_list" || shape === "str_list_list") return [];
  if (shape === "int_list") return [];
  if (shape === "positive_int" || shape === "int") return 1;
  if (shape === "bool") return false;
  if (shape === "str") return "";
  return {};
}
