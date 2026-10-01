import React from "react";
import { ArrowDown, ArrowUp, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { AddRow } from "@/components/ui/add-row";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Textarea } from "@/components/ui/textarea";
import { AssetListField } from "@/features/nodeForms/AssetListField";
import { JsonField } from "@/features/nodeForms/JsonField";
import { ListField } from "@/features/nodeForms/ListField";
import type { ConfigSpec } from "@/features/nodeForms/NodeConfigForm";

/**
 * 一串结构:插件入参里声明成数组、每一项是一块有名字的几格的那种(Manim 讲解视频的「讲解步骤」:每一步
 * 有标题、旁白、要点,再配公式 / 函数图 / 代码之一)。**一项一张卡**,卡里按每一项的声明摊开那几格
 * (后端 plugins.nodes 的 `_structure_fields`:`fields`),能加、能删、能上下挪,几项起几项止听声明的
 * `min_items` / `max_items`。此前这类字段是一个让人手写 `[{"title": …}]` 的 JSON 框。
 *
 * 每一格**只存文字**(和 ListField 一样):数、布尔由后端按 input_schema 转回来(plugins.inputs 的 _structure),
 * 这里不猜类型。空着的格子不存、整张卡都空着的不存 —— 刚加的那张空卡只活在本地,不变成一个交给插件的 `{}`。
 */

type Item = Record<string, unknown>;

function isPlainObject(value: unknown): value is Item {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parsedObject(text: string): unknown {
  if (!text.trim().startsWith("{")) return text;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/**
 * 存着的值 → 一张张卡。没填(没有值、空串、空列表)是零张;存的不是「一串对象」的(智能体写错了形状、
 * 一项是一段解不开的文字)回 null —— 调用方退回 JSON 框,原样摆出来,不在这里丢掉谁的内容。
 * 一项是一段 JSON 对象文字的(大模型交来的)解开,和运行时同一个认法。
 */
export function itemsFromValue(value: unknown): Item[] | null {
  if (value === undefined || value === null || value === "") return [];
  if (!Array.isArray(value)) return null;
  const items: Item[] = [];
  for (const one of value) {
    const parsed = typeof one === "string" ? parsedObject(one) : one;
    if (!isPlainObject(parsed)) return null;
    items.push(parsed);
  }
  return items;
}

function isBlank(value: unknown): boolean {
  if (value === undefined || value === null) return true;
  if (typeof value === "string") return !value.trim();
  if (Array.isArray(value)) return value.length === 0;
  if (isPlainObject(value)) return Object.keys(value).length === 0;
  return false;
}

/** 一块结构 → 存下去的样子:空着的格子去掉,里面的对象同样处理(删空了的对象也去掉)。 */
export function prunedItem(item: Item): Item {
  const out: Item = {};
  for (const [key, value] of Object.entries(item)) {
    const kept = isPlainObject(value) ? prunedItem(value) : value;
    if (!isBlank(kept)) out[key] = kept;
  }
  return out;
}

/** 卡 → 存下去的一串:整张都空着的卡不存。 */
export function itemsToValue(items: Item[]): Item[] {
  return items.map(prunedItem).filter((item) => Object.keys(item).length > 0);
}

/** 卡上那一行的预览:第一格文字(讲解步骤里就是这一步的标题),一眼认得出是哪一张。 */
function preview(item: Item, fields: Record<string, ConfigSpec>): string {
  const first = Object.entries(fields).find(([, spec]) => spec.type === "text");
  const text = first ? item[first[0]] : undefined;
  return typeof text === "string" ? text : "";
}

interface Row {
  id: number;
  item: Item;
}

export function ItemsField({
  value,
  fields,
  minItems = 0,
  maxItems,
  variables,
  onChange,
}: {
  value: unknown;
  /** 每一项有哪几格(后端按语言翻好了名字和说明)。 */
  fields: Record<string, ConfigSpec>;
  minItems?: number;
  maxItems?: number;
  /** 一串值的格子(要点、公式)里能挑的上游输出。 */
  variables: string[];
  onChange: (next: Item[]) => void;
}) {
  const t = useI18n();
  const nextId = React.useRef(0);
  const toRows = (items: Item[]): Row[] => {
    // 至少几项的,先摆出那几张空卡 —— 「讲解步骤」一张都没有时,人得先知道要点「加一项」才看得见要填什么。
    const padded = [...items, ...Array.from({ length: Math.max(0, minItems - items.length) }, () => ({}))];
    return padded.map((item) => ({ id: nextId.current++, item }));
  };
  // 本地保留卡:刚加的空卡在存下去的值里表示不出来(见 itemsToValue),只按值渲染的话它会当场消失。
  const [rows, setRows] = React.useState<Row[]>(() => toRows(itemsFromValue(value) ?? []));
  const emitted = React.useRef(JSON.stringify(itemsToValue(itemsFromValue(value) ?? [])));

  // 外面改了(撤销、智能体改图)才跟;自己发出去的那一版不跟,否则打字会被回流打断。
  React.useEffect(() => {
    const incoming = itemsFromValue(value) ?? [];
    const serialized = JSON.stringify(itemsToValue(incoming));
    if (serialized === emitted.current) return;
    emitted.current = serialized;
    setRows(toRows(incoming));
  }, [value]);

  const push = (next: Row[]) => {
    setRows(next);
    const list = itemsToValue(next.map((row) => row.item));
    emitted.current = JSON.stringify(list);
    onChange(list);
  };
  const move = (from: number, to: number) => {
    const next = [...rows];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    push(next);
  };
  const full = maxItems !== undefined && rows.length >= maxItems;

  return (
    <div className="grid min-w-0 gap-2" data-slot="items-field">
      {rows.map((row, index) => (
        <section
          key={row.id}
          className="grid min-w-0 gap-2 rounded-md border border-border bg-panel/40 p-2.5"
          aria-label={t("wfItemsNumber").replace("{n}", String(index + 1))}
        >
          <header className="flex min-w-0 items-center gap-1">
            <span className="shrink-0 text-ui-xs font-medium text-muted-foreground">
              {t("wfItemsNumber").replace("{n}", String(index + 1))}
            </span>
            <span className="min-w-0 flex-1 truncate text-ui-xs text-foreground">{preview(row.item, fields)}</span>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={t("wfItemsMoveUp")}
              disabled={index === 0}
              onClick={() => move(index, index - 1)}
            >
              <ArrowUp size={12} />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={t("wfItemsMoveDown")}
              disabled={index === rows.length - 1}
              onClick={() => move(index, index + 1)}
            >
              <ArrowDown size={12} />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={t("delete")}
              // 删到下限就不让删:「至少一步」的讲解,删光了只会在运行时报错
              disabled={rows.length <= minItems}
              onClick={() => push(rows.filter((_, i) => i !== index))}
            >
              <X size={12} />
            </Button>
          </header>
          <StructureFields
            fields={fields}
            value={row.item}
            variables={variables}
            onChange={(item) => push(rows.map((one, i) => (i === index ? { ...one, item } : one)))}
          />
        </section>
      ))}
      {full ? (
        <p className="m-0 text-ui-xs text-muted-foreground" role="note">
          {t("wfItemsFull").replace("{n}", String(maxItems))}
        </p>
      ) : (
        <AddRow dense label={t("wfMapAdd")} onClick={() => setRows([...rows, { id: nextId.current++, item: {} }])} />
      )}
    </div>
  );
}

/** 一块结构里的那几格。改一格只动那一格:声明之外的键(智能体写进来的)原样留着。 */
function StructureFields({
  fields,
  value,
  variables,
  onChange,
}: {
  fields: Record<string, ConfigSpec>;
  value: Item;
  variables: string[];
  onChange: (next: Item) => void;
}) {
  return (
    <>
      {Object.entries(fields).map(([key, spec]) => (
        <StructureField
          key={key}
          name={key}
          spec={spec}
          value={value[key]}
          variables={variables}
          onChange={(next) => onChange({ ...value, [key]: next })}
        />
      ))}
    </>
  );
}

function StructureField({
  name,
  spec,
  value,
  variables,
  onChange,
}: {
  name: string;
  spec: ConfigSpec;
  value: unknown;
  variables: string[];
  onChange: (next: unknown) => void;
}) {
  const t = useI18n();
  const label = (
    <span className="flex items-center gap-1 text-ui-xs font-medium text-foreground">
      {spec.label || name}
      {spec.required ? <em className="font-bold not-italic text-destructive">*</em> : null}
    </span>
  );
  const description = spec.description ? (
    <small className="text-ui-2xs leading-[1.5] text-muted-foreground">
      <InlineMarkdown text={spec.description} />
    </small>
  ) : null;
  const options = spec.options?.map((option) => ({ value: option, label: spec.option_labels?.[option] ?? option }));

  if (spec.type === "object" && spec.editor === "fields" && spec.fields) {
    return (
      <FieldGroup name={name} spec={spec} fields={spec.fields} value={value} variables={variables} onChange={onChange}>
        {description}
      </FieldGroup>
    );
  }

  let control: React.ReactNode;
  if (spec.editor === "json") {
    // 再往里说不清有哪几格的(没写 properties,或嵌得太深):一个 JSON 小框
    control = <JsonField value={value} empty={spec.type === "list" ? [] : {}} onChange={onChange} />;
  } else if (spec.type === "list" && spec.editor === "items" && spec.fields) {
    control = (
      <ItemsField
        value={value}
        fields={spec.fields}
        minItems={spec.min_items}
        maxItems={spec.max_items}
        variables={variables}
        onChange={onChange}
      />
    );
  } else if (spec.type === "list" && options) {
    control = <AssetListField value={value} options={options} addLabel={t("wfListPickMore")} onChange={onChange} />;
  } else if (spec.type === "list") {
    control = <ListField value={value} variables={variables} maxItems={spec.max_items} onChange={onChange} />;
  } else if (options) {
    control = (
      <OptionPicker
        value={String(value ?? "")}
        onChange={onChange}
        options={options}
        placeholder={spec.default ? String(spec.default) : t("wfPickOption")}
        size="sm"
      />
    );
  } else if (spec.multiline) {
    control = (
      <Textarea
        rows={3}
        className="resize-y px-2.5 py-1.5"
        value={String(value ?? "")}
        placeholder={spec.default ? String(spec.default) : ""}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  } else {
    control = (
      <Input
        type="text"
        size="sm"
        inputMode={spec.type === "number" ? "decimal" : undefined}
        value={String(value ?? "")}
        placeholder={spec.default ? String(spec.default) : ""}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  return (
    <div className="grid min-w-0 gap-1" data-field-key={name}>
      {label}
      {control}
      {description}
    </div>
  );
}

/** 再往里一层的对象(讲解步骤里的「函数图像」「代码」):收起来的一组,填过才一打开就展开 ——
 *  三样里一步只放一样,全摊开的话每张卡都是两三组用不上的空格子。展开与否是人点的,之后不跟着值变。 */
function FieldGroup({
  name,
  spec,
  fields,
  value,
  variables,
  onChange,
  children,
}: {
  name: string;
  spec: ConfigSpec;
  fields: Record<string, ConfigSpec>;
  value: unknown;
  variables: string[];
  onChange: (next: unknown) => void;
  /** 这一组的说明。 */
  children: React.ReactNode;
}) {
  const object = isPlainObject(value) ? value : {};
  const [open, setOpen] = React.useState(() => !isBlank(prunedItem(object)));
  return (
    <details
      className="min-w-0 rounded-md border border-divider px-2 py-1.5"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      data-field-key={name}
    >
      <summary className="cursor-pointer select-none text-ui-xs font-medium text-foreground">
        {spec.label || name}
        {spec.required ? <em className="font-bold not-italic text-destructive">*</em> : null}
      </summary>
      <div className="mt-2 grid min-w-0 gap-2">
        {children}
        <StructureFields fields={fields} value={object} variables={variables} onChange={onChange} />
      </div>
    </details>
  );
}
