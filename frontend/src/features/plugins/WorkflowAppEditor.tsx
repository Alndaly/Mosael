import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, CircleAlert, ListChecks, Search, TriangleAlert, X } from "lucide-react";

import {
  annotateWorkflow,
  getWorkflowApp,
  type GenerationOption,
  type PluginInstance,
  type WorkflowApp,
  type WorkflowFile,
  type WorkflowFillable,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { LibrarySection } from "@/components/app/LibraryBrowser";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { DeclaredParameterControl, PARAMETER_CONTROL_CLASS, ParameterField } from "@/components/generation/parameterPanel";
import { PageLoadError } from "@/components/layout/EmptyState";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Textarea } from "@/components/ui/textarea";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import {
  CHOICE_KINDS,
  GRAPH_KINDS,
  addItem,
  annotatePayload,
  dropInvalid,
  exposable,
  initialDraft,
  isStale,
  itemsByKey,
  moveItem,
  previewOption,
  removeItem,
  sameDraft,
  toggleResult,
  updateItem,
  type AppDraft,
  type AppItemDraft,
} from "@/features/plugins/workflowAppForm";
import {
  declaredParameters,
  promptMode,
  sizeOptions,
  sourceLabels,
  sourceLimit,
  supportsParameter,
} from "@/lib/generationCapabilities";
import { ROLE_COPY, SOURCE_ROLES, type SourceRole } from "@/lib/sourceFrames";
import { cn } from "@/lib/utils";

/**
 * 应用表单编辑器(ADR 0038 §2、§8 第一刀):工作流库详情里的「应用」。对应 RunningHub 的「AI 应用」——作者从一张工作流
 * **全部能填的项**里挑出要给别人填的几项、起名、排序、收窄可选值,标哪个输出节点是结果;AI 工作台、画板、工作流节点选这张
 * 工作流时都用这张表(它们不认识「应用」,读的还是同一个描述符,只是短了)。
 *
 * 左边是表单上的项(按顺序,能起名、上下挪、当主提示词、收窄可选值)、结果、其余能填的项;右边是预览 —— 按草稿拼一份和生成
 * 目录同形的描述符,交给生成面板同一组控件(parameterPanel)画出来,不另造一套。
 *
 * 存进**那张工作流自己的 JSON**(节点 `properties.mosael`、图上 `extra.mosael`):每次存都先确认,写明哪台服务器上的哪个
 * 文件、只改这几处标记;带着读到时的改动时间去,那台机器上在这之间存过(409 stale)就不写,说清楚、给「重新打开」。
 * 网页版也一样 —— 不依赖内嵌画布。
 */
export function WorkflowAppEditor({
  instance,
  flow,
  onClose,
  onSaved,
}: {
  instance: PluginInstance;
  flow: WorkflowFile;
  onClose: () => void;
  /** 存成了:工作流库、生成选项要重新问(宿主已经让这个连接的目录重拉过) */
  onSaved: () => void;
}) {
  const t = useI18n();
  const query = useQuery({
    queryKey: ["workflow-app", instance.id, flow.path],
    queryFn: () => getWorkflowApp(instance.id, flow.path),
    staleTime: 0,
  });
  const [draft, setDraft] = React.useState<AppDraft | null>(null);
  const [base, setBase] = React.useState<AppDraft | null>(null);
  const [asking, setAsking] = React.useState(false);
  const [failure, setFailure] = React.useState<{ stale: boolean; message: string } | null>(null);
  React.useEffect(() => {
    if (!query.data) return;
    const next = initialDraft(query.data);
    setDraft(next);
    setBase(next);
  }, [query.data]);

  const save = useMutation({
    mutationFn: (payload: Parameters<typeof annotateWorkflow>[1]) => annotateWorkflow(instance.id, payload),
    onSuccess: () => {
      setAsking(false);
      onSaved();
      onClose();
    },
    onError: (error) => {
      setAsking(false);
      setFailure({ stale: isStale(error), message: errorText(error) });
    },
  });

  const data = query.data;
  const dirty = Boolean(draft && base && !sameDraft(draft, base));
  const canSave = Boolean(data?.editable && draft && dirty && data.modified != null && !save.isPending);
  const footer = (
    <>
      <Button variant="ghost" disabled={save.isPending} onClick={onClose}>{t("cancel")}</Button>
      <Button disabled={!canSave} loading={save.isPending} onClick={() => setAsking(true)}>
        {t("workflowAppSave")}
      </Button>
    </>
  );

  let body: React.ReactNode;
  if (query.isPending) {
    body = <LoadingState label={t("workflowAppLoading")} className="h-auto py-12" />;
  } else if (query.isError || !data || !draft) {
    body = (
      <PageLoadError
        size="section"
        icon={<CircleAlert />}
        title={t("workflowAppLoadFailed")}
        error={query.error}
        onRetry={() => void query.refetch()}
        retrying={query.isFetching}
      />
    );
  } else {
    body = (
      <AppFormEditor
        instance={instance}
        data={data}
        draft={draft}
        onChange={(next) => {
          setFailure(null);
          setDraft(next);
        }}
      />
    );
  }

  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && !save.isPending && onClose()}
      title={t("workflowAppTitle").replace("{name}", flow.label)}
      className="w-[min(1180px,calc(100vw-32px))]"
      footer={footer}
    >
      <div className="grid gap-4">
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">
          {t("workflowAppWhere").replace("{server}", instance.name)}
        </p>
        {failure && (
          <div role="alert" className="flex min-w-0 items-start gap-2 rounded-lg border border-destructive/40 bg-panel p-3 text-ui-sm">
            <CircleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-destructive" />
            <span className="min-w-0 flex-1 break-words">
              {failure.stale ? t("workflowAppStale").replace("{name}", flow.label) : failure.message}
            </span>
            {failure.stale && (
              <Button variant="outline" size="sm" className="shrink-0" onClick={() => {
                setFailure(null);
                void query.refetch();
              }}>
                {t("workflowAppReload")}
              </Button>
            )}
          </div>
        )}
        {body}
      </div>
      {asking && data && draft && (
        <ConfirmDialog
          open
          title={t("workflowAppSaveTitle").replace("{server}", instance.name).replace("{path}", data.path)}
          body={draft.items.length > 0 ? t("workflowAppSaveBody") : t("workflowAppSaveRemoveBody")}
          confirmLabel={t("workflowAppSaveConfirm")}
          pending={save.isPending}
          onCancel={() => setAsking(false)}
          onConfirm={() => save.mutate(annotatePayload(data.path, data.modified ?? 0, draft))}
        />
      )}
    </ModalShell>
  );
}

type Translate = ReturnType<typeof useI18n>;

/** 「其余能填的项」按什么分组:文字、素材、模型、参数、图级的项。 */
const GROUPS = ["text", "media", "model", "params", "graph"] as const;
type Group = (typeof GROUPS)[number];

function groupOf(item: WorkflowFillable): Group {
  if (item.kind === "text" || item.kind === "media" || item.kind === "model") return item.kind;
  return GRAPH_KINDS.has(item.kind) ? "graph" : "params";
}

/** 这一项在哪个节点上(`采样 · steps`、`LoadImage #10`);图级的项没有节点。 */
function whereOf(item: WorkflowFillable | undefined): string {
  if (!item || !item.node) return "";
  return `${item.node_title || item.class_type} #${item.node} · ${item.input}`;
}

/**
 * 编辑器的正文:表单上的项、结果、其余能填的项,和预览。工作流库里的编辑器(弹窗,左右两栏)和工作台的「应用」面板(画布旁边
 * 那一列,`stacked`:上下排)共用 —— 工作台里改的是画布上的节点(见 comfy-workbench/canvasMarks)。
 */
export function AppFormEditor({
  instance,
  data,
  draft,
  onChange,
  stacked = false,
}: {
  instance: Pick<PluginInstance, "id">;
  data: WorkflowApp;
  draft: AppDraft;
  onChange: (next: AppDraft) => void;
  stacked?: boolean;
}) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const found = React.useMemo(() => itemsByKey(data), [data]);
  const chosen = new Set(draft.items.map((one) => one.key));
  const needle = query.trim().toLowerCase();
  const rest = (data.items ?? []).filter((item) => !chosen.has(item.key) && (!needle
    || `${item.title} ${item.key} ${item.node_title} ${item.class_type}`.toLowerCase().includes(needle)));
  const invalid = draft.items.filter((one) => one.problem).length;
  const outputs = data.outputs ?? [];
  const preview = React.useMemo(() => previewOption(data, draft, instance.id), [data, draft, instance.id]);

  return (
    <div className={cn("grid gap-5", !stacked && "lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)]")}>
      <div className="grid min-w-0 content-start gap-5">
        {data.app?.status === "unsupported" && (
          <Notice tone="warning">{t("workflowAppUnsupported").replace("{version}", data.app?.version || "?")}</Notice>
        )}
        {!data.editable && <Notice tone="warning">{t("workflowAppNotEditable")}</Notice>}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1.5 text-ui-sm text-muted-foreground">
            {t("workflowAppName")}
            <Input
              value={draft.title}
              maxLength={120}
              placeholder={t("workflowAppNamePlaceholder")}
              onChange={(event) => onChange({ ...draft, title: event.target.value })}
            />
          </label>
          <label className="grid gap-1.5 text-ui-sm text-muted-foreground">
            {t("workflowAppDescription")}
            <Input
              value={draft.description}
              maxLength={1000}
              placeholder={t("workflowAppDescriptionPlaceholder")}
              onChange={(event) => onChange({ ...draft, description: event.target.value })}
            />
          </label>
        </div>

        <LibrarySection
          title={t("workflowAppChosen")}
          count={draft.items.length}
          action={invalid > 0 ? (
            <Button variant="outline" size="sm" onClick={() => onChange(dropInvalid(draft))}>
              {t("workflowAppDropInvalid").replace("{n}", String(invalid))}
            </Button>
          ) : undefined}
        >
          {draft.items.length === 0 ? (
            <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{t("workflowAppChosenEmpty")}</p>
          ) : (
            <ol aria-label={t("workflowAppChosen")} className="m-0 grid list-none gap-2 p-0">
              {draft.items.map((one, index) => (
                <ChosenRow
                  key={one.key}
                  one={one}
                  item={found.get(one.key)}
                  first={index === 0}
                  last={index === draft.items.length - 1}
                  onChange={(patch) => onChange(updateItem(draft, one.key, patch))}
                  onMove={(delta) => onChange(moveItem(draft, one.key, delta))}
                  onRemove={() => onChange(removeItem(draft, one.key))}
                />
              ))}
            </ol>
          )}
        </LibrarySection>

        {outputs.length > 1 && (
          <LibrarySection title={t("workflowAppResults")} count={draft.results.length}>
            <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppResultsHint")}</p>
            <ul aria-label={t("workflowAppResults")} className="m-0 grid list-none gap-1 p-0">
              {outputs.map((output) => {
                const name = output.title && output.title !== output.class_type ? output.title : `${output.class_type} #${output.node}`;
                return (
                  <li key={output.node}>
                    <label className="flex min-w-0 cursor-pointer items-center gap-2 text-ui-sm text-foreground">
                      <Checkbox
                        checked={draft.results.includes(output.node ?? "")}
                        onCheckedChange={() => onChange(toggleResult(draft, output.node ?? ""))}
                        aria-label={t("workflowAppResultsMark").replace("{name}", name)}
                      />
                      <Truncate className="min-w-0 flex-1">{name}</Truncate>
                    </label>
                  </li>
                );
              })}
            </ul>
          </LibrarySection>
        )}

        <LibrarySection
          title={t("workflowAppAvailable")}
          count={(data.items ?? []).length - draft.items.filter((one) => found.has(one.key)).length}
        >
          <label className="relative">
            <Search size={14} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-9" value={query} placeholder={t("workflowAppSearch")} aria-label={t("workflowAppSearch")}
                   onChange={(event) => setQuery(event.target.value)} />
          </label>
          {GROUPS.map((group) => {
            const members = rest.filter((item) => groupOf(item) === group);
            if (members.length === 0) return null;
            return (
              <div key={group} className="grid gap-1.5">
                <h5 className="m-0 text-ui-xs font-semibold text-muted-foreground">{t(`workflowAppGroup_${group}`)}</h5>
                <ul aria-label={t(`workflowAppGroup_${group}`)} className="m-0 grid list-none gap-1 p-0">
                  {members.map((item) => (
                    <AvailableRow key={item.key} item={item} onAdd={() => onChange(addItem(draft, item))} />
                  ))}
                </ul>
              </div>
            );
          })}
        </LibrarySection>
      </div>

      <aside aria-label={t("workflowAppPreview")}
             className={cn("grid min-w-0 content-start gap-3", !stacked && "lg:sticky lg:top-0 lg:self-start")}>
        <div className="grid gap-0.5">
          <h4 className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
            <ListChecks size={14} aria-hidden />
            {t("workflowAppPreview")}
          </h4>
          <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppPreviewHint")}</p>
        </div>
        <div className="grid gap-3 rounded-xl border border-border bg-panel p-3">
          {draft.items.length === 0 ? (
            <p className="m-0 text-ui-sm text-muted-foreground">{t("workflowAppPreviewEmpty")}</p>
          ) : (
            <AppPreview option={preview} title={draft.title.trim() || data.path.replace(/\.json$/i, "")} note={draft.description} />
          )}
        </div>
      </aside>
    </div>
  );
}

function Notice({ tone, children }: { tone: "warning"; children: React.ReactNode }) {
  return (
    <div role="status" className={cn("flex min-w-0 items-start gap-2 rounded-lg border bg-panel p-3 text-ui-sm text-foreground",
      tone === "warning" && "border-warning/40")}>
      <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}

/** 「其余能填的项」里的一行:勾上就放进表单(排在最后)。子图里面的节点这一版不能放,灰着说为什么。 */
function AvailableRow({ item, onAdd }: { item: WorkflowFillable; onAdd: () => void }) {
  const t = useI18n();
  const allowed = exposable(item);
  const where = whereOf(item);
  return (
    <li>
      <Hint label={allowed ? where || undefined : t("workflowAppSubgraph")}>
        <label className={cn("flex min-w-0 items-center gap-2 rounded-md px-1.5 py-1 text-ui-sm text-foreground",
          allowed ? "cursor-pointer hover:bg-secondary" : "cursor-not-allowed opacity-55")}>
          <Checkbox checked={false} disabled={!allowed} onCheckedChange={() => allowed && onAdd()}
                    aria-label={t("workflowAppAdd").replace("{name}", item.title)} />
          <Truncate className="min-w-0 flex-1">{item.title}</Truncate>
          {!item.common && <CatalogBadge tone="muted">{t("workflowAppAdvanced")}</CatalogBadge>}
        </label>
      </Hint>
    </li>
  );
}

/** 表单上的一项:名字、上下挪、去掉;文字项能当主提示词,下拉 / 选模型文件的项能收窄可选值。对不上的项标着原因。 */
function ChosenRow({
  one,
  item,
  first,
  last,
  onChange,
  onMove,
  onRemove,
}: {
  one: AppItemDraft;
  item: WorkflowFillable | undefined;
  first: boolean;
  last: boolean;
  onChange: (patch: Partial<Pick<AppItemDraft, "label" | "main" | "choices">>) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}) {
  const t = useI18n();
  const [choosing, setChoosing] = React.useState(false);
  const name = item?.title || one.key;
  const hostControl = Boolean(item && (GRAPH_KINDS.has(item.kind) || (item.kind === "text" && one.main)));
  const declared = item && CHOICE_KINDS.has(item.kind) ? item.spec?.enum : undefined;
  const options = Array.isArray(declared) ? declared.map(String) : [];
  return (
    <li data-app-item={one.key} className={cn("grid min-w-0 gap-2 rounded-lg border bg-panel p-2.5",
      one.problem ? "border-warning/50" : "border-border")}>
      <div className="flex min-w-0 items-center gap-2">
        <span className="grid min-w-0 flex-1 gap-0.5">
          <Truncate className="text-ui-sm font-medium text-foreground">{one.label || name}</Truncate>
          <Truncate className="text-ui-xs text-muted-foreground">{whereOf(item) || name}</Truncate>
        </span>
        <IconButton size="sm" className="text-muted-foreground" disabled={first} label={t("workflowAppMoveUp").replace("{name}", one.label || name)}
                    onClick={() => onMove(-1)}>
          <ArrowUp size={13} />
        </IconButton>
        <IconButton size="sm" className="text-muted-foreground" disabled={last} label={t("workflowAppMoveDown").replace("{name}", one.label || name)}
                    onClick={() => onMove(1)}>
          <ArrowDown size={13} />
        </IconButton>
        <IconButton size="sm" className="text-muted-foreground" label={t("workflowAppRemove").replace("{name}", one.label || name)}
                    onClick={onRemove}>
          <X size={13} />
        </IconButton>
      </div>
      {one.problem && (
        <p role="note" className="m-0 flex items-start gap-1.5 text-ui-xs leading-relaxed text-warning">
          <TriangleAlert size={12} aria-hidden className="mt-0.5 shrink-0" />
          <span className="min-w-0 break-words">{t("workflowAppInvalidWhy").replace("{why}", one.problem)}</span>
        </p>
      )}
      {item && !one.problem && (
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
          {hostControl ? (
            <span className="text-ui-xs text-muted-foreground">{t("workflowAppHostControl")}</span>
          ) : (
            <Input
              size="xs"
              className="min-w-[180px] flex-1"
              value={one.label}
              maxLength={120}
              placeholder={t("workflowAppLabelPlaceholder").replace("{name}", name)}
              aria-label={t("workflowAppLabel").replace("{name}", name)}
              onChange={(event) => onChange({ label: event.target.value })}
            />
          )}
          {item.kind === "text" && (
            <Hint label={t("workflowAppMainHint")}>
              <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-ui-xs text-foreground">
                <Checkbox checked={one.main} onCheckedChange={(next) => onChange({ main: next === true })}
                          aria-label={t("workflowAppMain").replace("{name}", name)} />
                {t("workflowAppMainShort")}
              </label>
            </Hint>
          )}
          {options.length > 0 && (
            <Button variant="outline" size="xs" className="shrink-0" aria-expanded={choosing} onClick={() => setChoosing(!choosing)}>
              {one.choices && one.choices.length > 0
                ? t("workflowAppChoices").replace("{n}", String(one.choices.length)).replace("{total}", String(options.length))
                : t("workflowAppChoicesAll").replace("{total}", String(options.length))}
            </Button>
          )}
        </div>
      )}
      {choosing && options.length > 0 && (
        <ChoiceList
          name={name}
          options={options}
          value={one.choices}
          onChange={(choices) => onChange({ choices })}
        />
      )}
    </li>
  );
}

/** 收窄可选值:勾上的才许挑;一个都不勾 = 不收窄(全部都许)。几百个模型文件时先搜。 */
function ChoiceList({
  name,
  options,
  value,
  onChange,
}: {
  name: string;
  options: string[];
  value: string[] | null;
  onChange: (next: string[] | null) => void;
}) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const picked = new Set(value ?? []);
  const needle = query.trim().toLowerCase();
  const shown = options.filter((one) => !needle || one.toLowerCase().includes(needle)).slice(0, 200);
  const toggle = (option: string) => {
    const next = options.filter((one) => (one === option ? !picked.has(one) : picked.has(one)));
    onChange(next.length > 0 ? next : null);
  };
  return (
    <div className="grid gap-1.5 rounded-md bg-secondary/50 p-2">
      <div className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 flex-1 text-ui-xs text-muted-foreground">{t("workflowAppChoicesTitle")}</span>
        {value && (
          <Button variant="ghost" size="xs" onClick={() => onChange(null)}>{t("workflowAppChoicesClear")}</Button>
        )}
      </div>
      {options.length > 12 && (
        <Input size="xs" value={query} placeholder={t("workflowAppSearch")}
               aria-label={t("workflowAppChoicesSearch").replace("{name}", name)} onChange={(event) => setQuery(event.target.value)} />
      )}
      <ul aria-label={t("workflowAppChoicesTitle")} className="m-0 grid max-h-48 list-none gap-0.5 overflow-y-auto p-0">
        {shown.map((option) => (
          <li key={option}>
            <label className="flex min-w-0 cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-ui-xs text-foreground hover:bg-secondary">
              <Checkbox checked={picked.has(option)} onCheckedChange={() => toggle(option)} aria-label={option} />
              <Truncate className="min-w-0 flex-1">{option}</Truncate>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * 预览:按草稿拼出来的描述符(见 workflowAppForm.previewOption),用生成面板同一组读法和控件画 —— 提示词框、素材槽位
 * (每格的名字)、种子 / 尺寸 / 跑几遍、参数表。值只在这里改着看,不存。
 */
function AppPreview({ option, title, note }: { option: GenerationOption; title: string; note: string }) {
  const t = useI18n();
  const [values, setValues] = React.useState<Record<string, string>>({});
  const set = (key: string, value: string) => setValues((current) => ({ ...current, [key]: value }));
  const mode = promptMode(option);
  const roles = SOURCE_ROLES.filter((role) => supportsParameter(option, role));
  const sizes = sizeOptions(option);
  return (
    <div className="grid gap-3" data-app-preview>
      <div className="grid gap-0.5">
        <span className="text-ui-md font-semibold text-foreground">{title}</span>
        {note.trim() && (
          <span className="text-ui-xs leading-relaxed text-muted-foreground"><InlineMarkdown text={note} /></span>
        )}
      </div>
      {mode === "none" ? (
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppPromptNone")}</p>
      ) : (
        <ParameterField label={t("genPromptLabel")}>
          <Textarea className="min-h-20 rounded-lg border-border bg-field text-ui-sm" value={values.prompt ?? ""}
                    onChange={(event) => set("prompt", event.target.value)} />
        </ParameterField>
      )}
      {supportsParameter(option, "negative_prompt") && (
        <ParameterField label={t("genNegativePrompt")}>
          <Textarea className="min-h-14 rounded-lg border-border bg-field text-ui-sm" value={values.negative ?? ""}
                    onChange={(event) => set("negative", event.target.value)} />
        </ParameterField>
      )}
      {roles.map((role) => (
        <PreviewSlots key={role} role={role} t={t} names={sourceLabels(option, role)} count={sourceLimit(option, role)} />
      ))}
      {sizes.length > 0 && (
        <ParameterField label={t("genSize")}>
          <OptionPicker className={PARAMETER_CONTROL_CLASS} value={values.size ?? sizes[0]}
                        onChange={(next) => set("size", next)} options={sizes.map((one) => ({ value: one, label: one }))} />
        </ParameterField>
      )}
      {supportsParameter(option, "num_images") && (
        <ParameterField label={t("genRuns")}>
          <Input className={PARAMETER_CONTROL_CLASS} type="number" min={1} max={4} value={values.runs ?? "1"}
                 onChange={(event) => set("runs", event.target.value)} />
        </ParameterField>
      )}
      {supportsParameter(option, "seed") && (
        <ParameterField label={t("genSeed")}>
          <Input className={PARAMETER_CONTROL_CLASS} type="number" placeholder="auto" value={values.seed ?? ""}
                 onChange={(event) => set("seed", event.target.value)} />
        </ParameterField>
      )}
      {declaredParameters(option).map((parameter) => (
        <ParameterField key={parameter.key} label={parameter.label} title={parameter.description || undefined}>
          <DeclaredParameterControl parameter={parameter} value={values[parameter.key] ?? ""}
                                    onChange={(next) => set(parameter.key, next)} />
        </ParameterField>
      ))}
    </div>
  );
}

/** 一个角色的槽位:几格虚线框,每格写着它的名字(`source_labels`)。 */
function PreviewSlots({ role, names, count, t }: { role: SourceRole; names: string[]; count: number; t: Translate }) {
  const label = t(ROLE_COPY[role].label);
  return (
    <div className="grid gap-1.5 text-ui-xs font-semibold text-muted-foreground">
      <span>{label}</span>
      <ul aria-label={label} className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-1.5 p-0">
        {Array.from({ length: count }, (_, index) => (
          <li key={index} className="grid h-14 place-items-center rounded-lg border border-dashed border-border bg-muted/40 px-1.5">
            <Truncate className="max-w-full text-ui-xs font-medium text-foreground">{names[index] || `${label} ${index + 1}`}</Truncate>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * 工作流库详情里「应用」那一节:有没有应用表单、叫什么、几项、标成结果的节点;对不上的那几项列出来(工作流在 ComfyUI 里
 * 改过了),能**一键去掉**(先确认,和存一样只改 mosael 那几处标记、带着改动时间去)。「编辑应用表单」打开编辑器。
 * 插件没报应用表单(这张转不过来)就不出这一节。
 */
export function WorkflowAppSection({
  instance,
  flow,
  onEdit,
  onSaved,
}: {
  instance: PluginInstance;
  flow: WorkflowFile;
  onEdit: () => void;
  onSaved: () => void;
}) {
  const t = useI18n();
  const [asking, setAsking] = React.useState(false);
  const [failure, setFailure] = React.useState("");
  const drop = useMutation({
    mutationFn: async () => {
      const data = await getWorkflowApp(instance.id, flow.path);
      const draft = dropInvalid(initialDraft(data), (data.outputs ?? []).map((one) => one.node ?? ""));
      return annotateWorkflow(instance.id, annotatePayload(data.path, data.modified ?? 0, draft));
    },
    onSuccess: () => {
      setAsking(false);
      onSaved();
    },
    onError: (error) => {
      setAsking(false);
      setFailure(isStale(error) ? t("workflowAppStale").replace("{name}", flow.label) : errorText(error));
    },
  });
  const app = flow.app;
  if (!app) return null;
  const broken = (app.items ?? []).filter((one) => one.problem);
  return (
    <LibrarySection
      title={t("workflowApp")}
      count={app.app ? app.fields : undefined}
      action={
        <Hint label={t("workflowAppEditHint")}>
          <Button variant="outline" size="sm" onClick={onEdit}>{t("workflowAppEdit")}</Button>
        </Hint>
      }
    >
      {app.status === "unsupported" ? (
        <Notice tone="warning">{t("workflowAppUnsupported").replace("{version}", app.version || "?")}</Notice>
      ) : app.app ? (
        <div className="grid gap-2">
          {(app.title || app.description) && (
            <p className="m-0 grid gap-0.5 text-ui-sm text-foreground">
              {app.title && <span className="font-medium">{app.title}</span>}
              {app.description && (
                <span className="text-ui-xs text-muted-foreground"><InlineMarkdown text={app.description} /></span>
              )}
            </p>
          )}
          <ul aria-label={t("workflowAppChosen")} className="m-0 flex min-w-0 list-none flex-wrap gap-1.5 p-0">
            {(app.items ?? []).filter((one) => !one.problem).map((one) => (
              <li key={one.key} className="min-w-0 max-w-full">
                <Hint label={one.key}>
                  <span className="inline-flex h-7 max-w-full items-center rounded-full bg-secondary px-2.5 text-ui-xs text-foreground">
                    <Truncate>{one.label || one.title || one.key}</Truncate>
                  </span>
                </Hint>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppNone")}</p>
      )}
      {(app.results ?? []).length > 0 && app.status === "ok" && (
        <p className="m-0 text-ui-xs text-muted-foreground">
          {t("workflowAppResultsMarked").replace("{nodes}", (app.results ?? []).map((one) => `#${one}`).join(t("listSeparator")))}
        </p>
      )}
      {app.status === "ok" && (app.invalid ?? 0) > 0 && (
        <div role="alert" className="grid gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
          <span className="flex items-start gap-2">
            <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
            <span className="min-w-0">{t("workflowAppInvalidCount").replace("{n}", String(app.invalid))}</span>
          </span>
          {broken.length > 0 && (
            <ul className="m-0 grid list-none gap-1 p-0 text-ui-xs text-muted-foreground">
              {broken.map((one) => (
                <li key={one.key} className="break-words">
                  {t("workflowAppInvalidItem").replace("{name}", one.label || one.key).replace("{why}", one.problem ?? "")}
                </li>
              ))}
            </ul>
          )}
          <Button variant="outline" size="sm" className="justify-self-start" loading={drop.isPending}
                  onClick={() => { setFailure(""); setAsking(true); }}>
            {t("workflowAppDropInvalidSaved")}
          </Button>
        </div>
      )}
      {failure && <p role="alert" className="m-0 text-ui-sm text-destructive">{failure}</p>}
      {asking && (
        <ConfirmDialog
          open
          title={t("workflowAppSaveTitle").replace("{server}", instance.name).replace("{path}", flow.path)}
          body={t("workflowAppDropInvalidBody")}
          confirmLabel={t("workflowAppSaveConfirm")}
          pending={drop.isPending}
          onCancel={() => setAsking(false)}
          onConfirm={() => drop.mutate()}
        />
      )}
    </LibrarySection>
  );
}
