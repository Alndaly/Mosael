import React from "react";
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ArrowDown, ArrowUp, Check, GripVertical, ListPlus, SlidersHorizontal, Sparkles, TriangleAlert, X } from "lucide-react";

import type { WorkflowApp, WorkflowAppOutput, WorkflowFillable } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { KindIcon, techText, valueText, visualOf } from "@/features/plugins/appForm/fieldFacts";
import {
  CHOICE_KINDS,
  GRAPH_KINDS,
  addRecommended,
  dropInvalid,
  fixableChoices,
  itemsByKey,
  keepValidChoices,
  moveItem,
  moveItemTo,
  recommendedItems,
  removeItem,
  updateItem,
  type FormDraft,
  type AppItemDraft,
} from "@/features/plugins/workflowAppForm";
import { cn } from "@/lib/utils";

type Patch = Partial<Pick<AppItemDraft, "label" | "main" | "choices">>;

/** 拖动起手要挪多远(px):点一下手柄、点设置不会被当成拖。 */
const DRAG_DISTANCE = 4;

/**
 * 「表单」:正在搭的那张表。每一项是一张紧凑的卡片 —— 拖动手柄(指针拖;聚焦后按 ↑ ↓ 挪)、种类图标、名字(就地改)、现在的值,
 * 右边「设置」(收窄可选值、当主提示词、上下挪、拿掉)和「拿掉」。失效的项标着原因,能修的给一键修(只留还在的可选值),修不了的
 * 一键去掉。空着时给「按推荐先挑一版」。「结果取自」不在这里:它按工作流记,在表单那一排上面(见 ResultsSection)。
 */
export function FormBuilder({
  data,
  draft,
  onChange,
}: {
  data: WorkflowApp;
  draft: FormDraft;
  onChange: (next: FormDraft) => void;
}) {
  const t = useI18n();
  const found = React.useMemo(() => itemsByKey(data), [data]);
  const [said, setSaid] = React.useState("");
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: DRAG_DISTANCE } }));
  const invalid = draft.items.filter((one) => one.problem).length;

  const nameOf = (key: string) => {
    const one = draft.items.find((entry) => entry.key === key);
    return one?.label || found.get(key)?.title || key;
  };
  const announceMove = (next: FormDraft, key: string) => {
    const index = next.items.findIndex((one) => one.key === key);
    setSaid(t("workflowAppMoved").replace("{name}", nameOf(key)).replace("{n}", String(index + 1)));
  };
  //: 键盘挪的时候焦点留在手柄上:React 提交时把挪动前聚焦的那个元素再聚焦回来,接着按 ↑ ↓ 还能挪
  const move = (key: string, delta: -1 | 1) => {
    const next = moveItem(draft, key, delta);
    if (next === draft) return;
    announceMove(next, key);
    onChange(next);
  };
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const next = moveItemTo(draft, String(active.id), draft.items.findIndex((one) => one.key === over.id));
    if (next === draft) return;
    announceMove(next, String(active.id));
    onChange(next);
  };

  return (
    <section aria-label={t("workflowAppForm")} className="grid min-w-0 content-start gap-3" data-app-zone="form">
      <h4 className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
        {t("workflowAppForm")}
        <span className="text-ui-xs font-normal tabular-nums text-muted-foreground">{draft.items.length}</span>
      </h4>
      {invalid > 0 && (
        <div role="alert" className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-warning/40 bg-panel p-2.5 text-ui-sm">
          <TriangleAlert size={14} aria-hidden className="shrink-0 text-warning" />
          <span className="min-w-0 flex-1 basis-48">{t("workflowAppInvalidNotice").replace("{n}", String(invalid))}</span>
          <Button variant="outline" size="sm" onClick={() => onChange(dropInvalid(draft))}>
            {t("workflowAppDropInvalid").replace("{n}", String(invalid))}
          </Button>
        </div>
      )}
      {draft.items.length === 0 ? (
        <EmptyForm data={data} onRecommend={() => onChange(addRecommended(draft, data))} />
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={onDragEnd}
          //: 拖动库自带的读屏说明是英文、讲的是它的键盘拖法;这里键盘用 ↑ ↓,挪完自己念(见 said)
          accessibility={{ announcements: SILENT, screenReaderInstructions: { draggable: "" } }}
        >
          <SortableContext items={draft.items.map((one) => one.key)} strategy={verticalListSortingStrategy}>
            <ol aria-label={t("workflowAppChosen")} className="m-0 grid list-none gap-2 p-0">
              {draft.items.map((one, index) => (
                <FieldCard
                  key={one.key}
                  one={one}
                  item={found.get(one.key)}
                  first={index === 0}
                  last={index === draft.items.length - 1}
                  onPatch={(patch) => onChange(updateItem(draft, one.key, patch))}
                  onMove={(delta) => move(one.key, delta)}
                  onRemove={() => onChange(removeItem(draft, one.key))}
                  onFix={(options) => onChange(keepValidChoices(draft, one.key, options))}
                />
              ))}
            </ol>
          </SortableContext>
        </DndContext>
      )}
      <p role="status" aria-live="polite" data-app-announce="" className="sr-only">{said}</p>
    </section>
  );
}

const SILENT = {
  onDragStart: () => undefined,
  onDragOver: () => undefined,
  onDragEnd: () => undefined,
  onDragCancel: () => undefined,
};

/** 空着的表单:不是一块死框 —— 说清楚怎么加,给「按推荐先挑一版」并写明会挑哪几项;一项都不挑也是一种选择。 */
function EmptyForm({ data, onRecommend }: { data: WorkflowApp; onRecommend: () => void }) {
  const t = useI18n();
  const picks = recommendedItems(data);
  return (
    <div data-app-empty="" className="grid justify-items-center gap-3 rounded-xl border border-dashed border-border-strong px-5 py-8 text-center">
      <span className="grid size-10 place-items-center rounded-full bg-secondary text-muted-foreground">
        <ListPlus size={18} aria-hidden />
      </span>
      <div className="grid gap-1">
        <h5 className="m-0 text-ui-sm font-semibold text-foreground">{t("workflowAppEmptyTitle")}</h5>
        <p className="m-0 max-w-sm text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppEmptyBody")}</p>
      </div>
      <Hint disabledReason={picks.length === 0 ? t("workflowAppRecommendNothing") : undefined}>
        <Button disabled={picks.length === 0} onClick={onRecommend}>
          <Sparkles size={14} aria-hidden />
          {t("workflowAppRecommend")}
        </Button>
      </Hint>
      {picks.length > 0 && (
        <p className="m-0 max-w-sm text-ui-2xs leading-relaxed text-muted-foreground">
          {t("workflowAppRecommendWhat").replace("{what}", picks.map((one) => one.title).join(t("listSeparator")))}
        </p>
      )}
      <p className="m-0 max-w-sm text-ui-2xs leading-relaxed text-muted-foreground">{t("workflowAppEmptyNote")}</p>
    </div>
  );
}

/** 表单上的一张卡片。 */
function FieldCard({
  one,
  item,
  first,
  last,
  onPatch,
  onMove,
  onRemove,
  onFix,
}: {
  one: AppItemDraft;
  item: WorkflowFillable | undefined;
  first: boolean;
  last: boolean;
  onPatch: (patch: Patch) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
  onFix: (options: string[]) => void;
}) {
  const t = useI18n();
  const { listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: one.key });
  const name = item?.title || one.key;
  const shown = one.label || name;
  //: 图级的项、主提示词用宿主自己的控件,名字跟着宿主走,不能改
  const hostControl = Boolean(item && (GRAPH_KINDS.has(item.kind) || (item.kind === "text" && one.main)));
  const declared = item && CHOICE_KINDS.has(item.kind) ? (item.spec as { enum?: unknown } | null)?.enum : undefined;
  const options = Array.isArray(declared) ? declared.map(String) : [];
  const fixable = fixableChoices(one, item);
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-app-item={one.key}
      className={cn(
        "grid min-w-0 gap-1.5 rounded-lg border bg-panel p-2",
        one.problem ? "border-warning/50" : "border-border",
        isDragging && "relative z-10 shadow-lg",
      )}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <IconButton
          ref={setActivatorNodeRef}
          {...listeners}
          data-drag-handle={one.key}
          label={t("workflowAppDrag").replace("{name}", shown)}
          className="shrink-0 cursor-grab touch-none text-muted-foreground active:cursor-grabbing"
          onKeyDown={(event) => {
            if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
            event.preventDefault();
            onMove(event.key === "ArrowUp" ? -1 : 1);
          }}
        >
          <GripVertical />
        </IconButton>
        <KindIcon visual={visualOf(item, one.main)} />
        {hostControl || !item ? (
          <Hint label={hostControl ? t("workflowAppHostControlHint") : undefined}>
            <span className="min-w-0 flex-1 border border-transparent px-2.5 text-ui-sm font-medium text-foreground">
              <Truncate>{shown}</Truncate>
            </span>
          </Hint>
        ) : (
          <Input
            size="sm"
            className="min-w-0 flex-1 border-transparent bg-transparent font-medium hover:border-field-border focus-visible:border-primary"
            value={one.label}
            maxLength={120}
            placeholder={name}
            aria-label={t("workflowAppLabel").replace("{name}", name)}
            onChange={(event) => onPatch({ label: event.target.value })}
          />
        )}
        {item && !one.problem && (
          <FieldSettings one={one} item={item} name={shown} options={options} first={first} last={last}
                         onPatch={onPatch} onMove={onMove} onRemove={onRemove} />
        )}
        <IconButton label={t("workflowAppRemove").replace("{name}", shown)} className="shrink-0 text-muted-foreground" onClick={onRemove}>
          <X />
        </IconButton>
      </div>
      {item && !one.problem && (
        <div className="flex min-w-0 flex-wrap items-center gap-1.5 pl-[83px] text-ui-2xs text-muted-foreground">
          {one.main && item.kind === "text" && (
            <CatalogBadge tone="primary">{t(item.role === "negative" ? "workflowAppMainNegativeShort" : "workflowAppMainShort")}</CatalogBadge>
          )}
          {one.choices && one.choices.length > 0 && (
            <CatalogBadge tone="muted">
              {t("workflowAppChoices").replace("{n}", String(one.choices.length)).replace("{total}", String(options.length))}
            </CatalogBadge>
          )}
          <Truncate className="min-w-0 flex-1 basis-24">{valueText(item, t)}</Truncate>
        </div>
      )}
      {one.problem && (
        <div className="grid gap-2 pl-[83px]">
          <p role="note" className="m-0 flex items-start gap-1.5 text-ui-xs leading-relaxed text-warning">
            <TriangleAlert size={12} aria-hidden className="mt-0.5 shrink-0" />
            <span className="min-w-0 break-words">{t("workflowAppInvalidWhy").replace("{why}", one.problem)}</span>
          </p>
          <div className="flex flex-wrap gap-2">
            {fixable && (
              <Button variant="outline" size="sm" onClick={() => onFix(fixable)}>{t("workflowAppFixChoices")}</Button>
            )}
            <Button variant="ghost" size="sm" onClick={onRemove}>{t("workflowAppRemoveShort")}</Button>
          </div>
        </div>
      )}
    </li>
  );
}

/** 一项的设置:名字的来历(节点、类名、ComfyUI 的说明)、当不当主提示词、收窄可选值、上下挪、拿掉。 */
function FieldSettings({
  one,
  item,
  name,
  options,
  first,
  last,
  onPatch,
  onMove,
  onRemove,
}: {
  one: AppItemDraft;
  item: WorkflowFillable;
  name: string;
  options: string[];
  first: boolean;
  last: boolean;
  onPatch: (patch: Patch) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}) {
  const t = useI18n();
  const tech = techText(item, t);
  const negative = item.role === "negative";
  const hostControl = GRAPH_KINDS.has(item.kind) || (item.kind === "text" && one.main);
  return (
    <Popover modal>
      <PopoverTrigger asChild>
        <IconButton label={t("workflowAppSettings").replace("{name}", name)} className="shrink-0 text-muted-foreground">
          <SlidersHorizontal />
        </IconButton>
      </PopoverTrigger>
      <PopoverContent align="end" className="grid w-80 gap-3 p-3" aria-label={t("workflowAppSettings").replace("{name}", name)}>
        <div className="grid gap-0.5">
          <span className="text-ui-sm font-semibold text-foreground"><Truncate>{name}</Truncate></span>
          {tech && <span className="break-all text-ui-2xs text-muted-foreground">{tech}</span>}
          {item.hint && <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{item.hint}</p>}
          {hostControl && <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppHostControlHint")}</p>}
        </div>
        {item.kind === "text" && (
          <label className="flex items-start justify-between gap-3">
            <span className="grid gap-0.5">
              <span className="text-ui-sm text-foreground">{t(negative ? "workflowAppMainNegative" : "workflowAppMain")}</span>
              <span className="text-ui-2xs leading-relaxed text-muted-foreground">
                {t(negative ? "workflowAppMainNegativeHint" : "workflowAppMainHint")}
              </span>
            </span>
            <Switch checked={one.main} onCheckedChange={(next) => onPatch({ main: next })}
                    aria-label={`${t(negative ? "workflowAppMainNegative" : "workflowAppMain")}: ${name}`} />
          </label>
        )}
        {options.length > 0 && <ChoiceList name={name} options={options} value={one.choices} onChange={(choices) => onPatch({ choices })} />}
        <div className="flex flex-wrap gap-2 border-t border-divider pt-3">
          <Button variant="outline" size="sm" disabled={first} onClick={() => onMove(-1)}>
            <ArrowUp size={13} aria-hidden />
            {t("workflowAppMoveUp")}
          </Button>
          <Button variant="outline" size="sm" disabled={last} onClick={() => onMove(1)}>
            <ArrowDown size={13} aria-hidden />
            {t("workflowAppMoveDown")}
          </Button>
          <Button variant="ghost" size="sm" className="ml-auto text-destructive hover:text-destructive" onClick={onRemove}>
            {t("workflowAppRemoveShort")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** 收窄可选值:勾上的才许挑;一个都不勾 = 不收窄。几百个模型文件时先搜(一屏最多列 200 个)。 */
function ChoiceList({ name, options, value, onChange }: {
  name: string;
  options: string[];
  value: string[] | null;
  onChange: (next: string[] | null) => void;
}) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const picked = new Set(value ?? []);
  const needle = query.trim().toLowerCase();
  const matched = options.filter((one) => !needle || one.toLowerCase().includes(needle));
  const shown = matched.slice(0, 200);
  const toggle = (option: string) => {
    const next = options.filter((one) => (one === option ? !picked.has(one) : picked.has(one)));
    onChange(next.length > 0 ? next : null);
  };
  return (
    <div className="grid gap-1.5">
      <div className="flex min-w-0 items-center gap-2">
        <span className="grid min-w-0 flex-1">
          <span className="text-ui-sm text-foreground">
            {value ? t("workflowAppChoicesTitle") : t("workflowAppChoicesAll").replace("{total}", String(options.length))}
          </span>
          <span className="text-ui-2xs text-muted-foreground">{t("workflowAppChoicesHint")}</span>
        </span>
        {value && <Button variant="ghost" size="xs" onClick={() => onChange(null)}>{t("workflowAppChoicesClear")}</Button>}
      </div>
      {options.length > 12 && (
        <Input size="xs" value={query} placeholder={t("workflowAppSearch")}
               aria-label={t("workflowAppChoicesSearch").replace("{name}", name)} onChange={(event) => setQuery(event.target.value)} />
      )}
      <ul aria-label={t("workflowAppChoicesTitle")} className="m-0 grid max-h-52 list-none gap-0.5 overflow-y-auto p-0">
        {shown.map((option) => (
          <li key={option}>
            <label className="flex min-w-0 cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-ui-xs text-foreground hover:bg-secondary">
              <Checkbox checked={picked.has(option)} onCheckedChange={() => toggle(option)} aria-label={option} />
              <Truncate className="min-w-0 flex-1">{option}</Truncate>
            </label>
          </li>
        ))}
      </ul>
      {matched.length > shown.length && (
        <span className="text-ui-2xs text-muted-foreground">
          {t("workflowAppChoicesMore").replace("{n}", String(matched.length - shown.length))}
        </span>
      )}
    </div>
  );
}

/** 输出节点叫什么:给人看的节点名加节点号(几个都叫「保存图像」时分得清)。 */
function outputName(output: WorkflowAppOutput): string {
  const name = output.label || output.title || output.class_type || "";
  return output.node ? `${name} #${output.node}` : name;
}

/**
 * 「结果取自」:这张工作流有几个出图的节点时,标哪几个出的图才算结果(插件记在那个节点上,ADR 0038 §5)。说的是节点,不是某一张图:
 * 「只要这个节点的图」;标了的写「结果取自这个节点」,能撤销。**按工作流记,不按表单**(ADR 0045 §7):完整工作流和每张表单
 * 都按它,所以摆在表单那一排上面单独一块。只有一个出图的节点时不出。
 */
export function ResultsSection({ outputs, results, onToggle }: {
  outputs: WorkflowAppOutput[];
  results: string[];
  onToggle: (node: string) => void;
}) {
  const t = useI18n();
  if (outputs.length < 2) return null;
  return (
    <section aria-label={t("workflowAppResults")} data-app-results="" className="grid min-w-0 gap-2">
      <h4 className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
        {t("workflowAppResults")}
        {results.length > 0 && <span className="text-ui-xs font-normal tabular-nums text-muted-foreground">{results.length}</span>}
      </h4>
      <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppResultsHint")}</p>
      <ul aria-label={t("workflowAppResults")} className="m-0 grid list-none gap-1.5 p-0">
        {outputs.map((output) => {
          const node = output.node ?? "";
          const name = outputName(output);
          const marked = results.includes(node);
          return (
            <li key={node} data-result-node={node}
                className={cn("flex min-w-0 items-center gap-2 rounded-lg border px-2 py-1.5",
                  marked ? "border-primary/50 bg-accent/40" : "border-border")}>
              <KindIcon visual={output.media === "video" || output.media === "audio" ? output.media : "image"} />
              <span className="grid min-w-0 flex-1">
                <Truncate className="text-ui-sm text-foreground">{name}</Truncate>
                {marked && (
                  <span className="inline-flex items-center gap-1 text-ui-2xs font-medium text-primary">
                    <Check size={12} aria-hidden />
                    {t("workflowAppResultsChosen")}
                  </span>
                )}
              </span>
              {marked ? (
                <Button variant="ghost" size="sm" aria-label={t("workflowAppResultsUndoLabel").replace("{name}", name)}
                        onClick={() => onToggle(node)}>
                  {t("workflowAppResultsUndo")}
                </Button>
              ) : (
                <Button variant="outline" size="sm" aria-label={t("workflowAppResultsMarkLabel").replace("{name}", name)}
                        onClick={() => onToggle(node)}>
                  {t("workflowAppResultsMark")}
                </Button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
