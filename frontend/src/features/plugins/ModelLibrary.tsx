import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CircleAlert,
  Copy,
  Download,
  Library,
  RefreshCcw,
  Workflow,
  X,
} from "lucide-react";

import {
  cancelJob,
  getJob,
  getModelDetail,
  getModelLibrary,
  resolveModelLink,
  startModelDownload,
  type Job,
  type MissingModel,
  type ModelFile,
  type ModelLibrary,
  type ModelResolved,
  type PluginInstance,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n, usePreferences } from "@/app/preferences";
import { CatalogBadge, CatalogDetail, CatalogDialog, CatalogSection } from "@/components/app/CatalogDialog";
import { ModalShell } from "@/components/app/modals";
import { SettingsRow } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Progress } from "@/components/ui/progress";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { ModelThumb, folderIcon, modelBaseName, modelSubFolder, normModelName } from "@/components/generation/ModelThumb";
import { formatBytes } from "@/lib/bytes";
import { isImeKeystroke } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

/**
 * 模型库(ADR 0034):一个连接**那台服务器上的模型文件**。任何认领了 `model_library` 的插件连接都走这里,不认识哪一家。
 *
 * 版式是插件市场同一个目录弹窗(CatalogDialog):按目录分的页签、按底模筛、搜索,卡片网格(有预览图用预览图,没有就是
 * 按目录分的占位),点开是一页详情(元数据、触发词、在用的工作流)。网格上面是两组「要处理的事」:工作流缺的模型(一键下载)
 * 和下载中的任务(进度、取消)。下载框先解析链接(文件名、大小、建议的目录),同名文件不覆盖 —— 要求换名。
 *
 * 列表每次打开现问插件(不存库);下载的进度读任务本身,不反复让插件把几百个文件再列一遍。
 */

type Translate = ReturnType<typeof useI18n>;

const ALL = "__all__";
const UNKNOWN_FAMILY = "__unknown__";

const keyOf = (model: { folder: string; name: string }) => `${model.folder}/${model.name}`;
const norm = normModelName;
const baseName = modelBaseName;
const subFolder = modelSubFolder;

/** 一个不撞名的建议:`x.safetensors` → `x (1).safetensors`、`x (2).safetensors`……按用户此刻选的目录算(他可能改了目录)。 */
export function freeName(name: string, taken: Set<string>): string {
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : "";
  for (let index = 1; index < 1000; index += 1) {
    const candidate = `${stem} (${index})${ext}`;
    if (!taken.has(norm(candidate))) return candidate;
  }
  return name;
}

/** 文件名只能是一段(插件和宿主都会再查一遍)。 */
const plainName = (name: string) => {
  const text = name.trim();
  return Boolean(text) && text !== "." && text !== ".." && !/[\\/:]/.test(text);
};

const ACTIVE = new Set(["queued", "running"]);

export function ModelLibraryRow({ instance, workspaceId }: { instance: PluginInstance; workspaceId: string }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  return (
    <SettingsRow label={t("modelLibrary")} description={t("modelLibraryDesc")}>
      <Button variant="outline" disabled={Boolean(instance.blocked_reason)} onClick={() => setOpen(true)}>
        <Library size={13} />
        {t("modelLibraryOpen")}
      </Button>
      {open && <ModelLibraryDialog open={open} onOpenChange={setOpen} instance={instance} workspaceId={workspaceId} />}
    </SettingsRow>
  );
}

type DownloadSeed = { url?: string; folder?: string; name?: string };

export function ModelLibraryDialog({
  open,
  onOpenChange,
  instance,
  workspaceId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: PluginInstance;
  workspaceId: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const queryKey = React.useMemo(() => ["model-library", instance.id], [instance.id]);
  const library = useQuery({ queryKey, queryFn: () => getModelLibrary(instance.id), enabled: open, staleTime: 30_000 });
  const [folder, setFolder] = React.useState(ALL);
  const [family, setFamily] = React.useState(ALL);
  const [query, setQuery] = React.useState("");
  const [detailKey, setDetailKey] = React.useState<string | null>(null);
  const [seed, setSeed] = React.useState<DownloadSeed | null>(null);
  //: 这次打开之后发起的下载(列表里的那份是打开时的快照)。
  const [started, setStarted] = React.useState<Job[]>([]);

  const models = React.useMemo(() => library.data?.models ?? [], [library.data]);
  const folders = React.useMemo(
    () => [...(library.data?.folders ?? [])].filter((one) => one.count > 0).sort((a, b) => b.count - a.count),
    [library.data],
  );
  const inFolder = folder === ALL ? models : models.filter((model) => model.folder === folder);
  const families = React.useMemo(() => {
    const counts = new Map<string, number>();
    for (const model of inFolder) counts.set(model.family || UNKNOWN_FAMILY, (counts.get(model.family || UNKNOWN_FAMILY) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [inFolder]);
  const needle = query.trim().toLowerCase();
  const shown = inFolder.filter((model) => {
    if (family !== ALL && (model.family || UNKNOWN_FAMILY) !== family) return false;
    if (!needle) return true;
    return `${model.name} ${model.title ?? ""} ${model.family ?? ""} ${(model.triggers ?? []).join(" ")}`.toLowerCase().includes(needle);
  });
  const detail = detailKey ? models.find((model) => keyOf(model) === detailKey) ?? null : null;

  const downloads = useDownloads(library.data, started, () => {
    void qc.invalidateQueries({ queryKey });
    // 生成表单的下拉、工作流节点:下好的文件要马上选得到(宿主那边已经刷新了这个连接的目录)
    invalidatePluginDependents(qc);
  });

  const placeholder = library.isLoading ? (
    <p className="m-0 max-w-[420px] text-center text-ui-sm text-muted-foreground">{t("modelLibraryLoading")}</p>
  ) : library.isError ? (
    <p className="m-0 max-w-[520px] text-center text-ui-sm text-destructive">
      {t("modelLibraryError").replace("{error}", errorText(library.error))}
    </p>
  ) : (
    <p className="m-0 text-ui-sm text-muted-foreground">{models.length ? t("modelLibraryNoMatch") : t("modelLibraryEmpty")}</p>
  );

  return (
    <CatalogDialog<ModelFile>
      open={open}
      onOpenChange={onOpenChange}
      title={t("modelLibraryTitle").replace("{name}", instance.name)}
      description={t("modelLibraryDescription")}
      searchLabel={t("modelLibrarySearch").replace("{n}", String(models.length))}
      query={query}
      onQueryChange={setQuery}
      headerActions={
        <>
          <Button variant="outline" loading={library.isFetching} onClick={() => void library.refetch()}>
            <RefreshCcw size={13} />
            {t("modelLibraryRefresh")}
          </Button>
          <Button onClick={() => setSeed({})} disabled={!library.data}>
            <Download size={13} />
            {t("modelLibraryDownload")}
          </Button>
        </>
      }
      filters={
        folders.length
          ? {
              label: t("modelLibraryFolders"),
              value: folder,
              onChange: (value) => {
                setFolder(value);
                setFamily(ALL);
              },
              items: [
                { value: ALL, label: t("modelLibraryAll"), count: models.length },
                ...folders.map((one) => ({ value: one.name, label: one.name, count: one.count })),
              ],
            }
          : undefined
      }
      refine={
        families.length > 1 ? (
          <OptionPicker
            className="w-[200px]"
            ariaLabel={t("modelLibraryFamilyLabel")}
            value={family}
            onChange={setFamily}
            options={[
              { value: ALL, label: t("modelLibraryFamilyAll") },
              ...families.map(([value, count]) => ({
                value,
                label: `${value === UNKNOWN_FAMILY ? t("modelLibraryFamilyUnknown") : value} · ${count}`,
              })),
            ]}
          />
        ) : undefined
      }
      notice={
        library.data && ((library.data.missing ?? []).length > 0 || downloads.length > 0) ? (
          <div className="grid gap-3">
            {downloads.length > 0 && <DownloadList jobs={downloads} />}
            {(library.data.missing ?? []).length > 0 && (
              <MissingList missing={library.data.missing ?? []} onDownload={(one) => setSeed({ url: one.url, folder: one.folder, name: one.name })} />
            )}
          </div>
        ) : undefined
      }
      items={library.data ? shown : []}
      itemKey={keyOf}
      renderCard={(model, openDetail) => <ModelCard instanceId={instance.id} model={model} onOpen={openDetail} />}
      placeholder={placeholder}
      detail={detail}
      onDetailChange={setDetailKey}
      renderDetail={(model) => <ModelDetailPage instanceId={instance.id} model={model} />}
      backLabel={t("modelLibraryBack")}
    >
      {seed && library.data && (
        <ModelDownloadDialog
          instance={instance}
          workspaceId={workspaceId}
          library={library.data}
          seed={seed}
          onClose={() => setSeed(null)}
          onStarted={(job) => setStarted((current) => [job, ...current])}
        />
      )}
    </CatalogDialog>
  );
}

/**
 * 要盯着的下载:打开时列表里带的那几条 + 这次发起的。在跑的隔一会儿读一次任务本身(不让插件把几百个文件再列一遍);
 * 有一条成功了就让模型库重新列一遍(`onSucceeded`)。
 */
function useDownloads(library: ModelLibrary | undefined, started: Job[], onSucceeded: () => void): Job[] {
  const known = React.useMemo(() => {
    //: 列表重新列过之后,它带的那一份比「发起时」的那一份新:先认它的。
    const listed = library?.downloads ?? [];
    const ids = new Set(listed.map((job) => job.id));
    return [...started.filter((job) => !ids.has(job.id)), ...listed];
  }, [library, started]);
  const watching = known.filter((job) => ACTIVE.has(job.status)).map((job) => job.id);
  const live = useQuery({
    queryKey: ["model-downloads", watching],
    queryFn: () => Promise.all(watching.map((id) => getJob(id))),
    enabled: watching.length > 0,
    refetchInterval: 1500,
  });
  const fresh = new Map((live.data ?? []).map((job) => [job.id, job]));
  const merged = known.map((job) => fresh.get(job.id) ?? job);
  const succeeded = merged.filter((job) => job.status === "succeeded" && watching.includes(job.id)).map((job) => job.id).join(",");
  const callback = React.useRef(onSucceeded);
  callback.current = onSucceeded;
  React.useEffect(() => {
    if (succeeded) callback.current();
  }, [succeeded]);
  return merged;
}

function DownloadList({ jobs }: { jobs: Job[] }) {
  const t = useI18n();
  const cancel = useMutation({ mutationFn: (id: string) => cancelJob(id) });
  return (
    <section className="grid min-w-0 gap-2 rounded-xl border border-border bg-panel p-3" aria-label={t("modelDownloadsTitle")}>
      <h3 className="m-0 text-ui-sm font-semibold text-foreground">{t("modelDownloadsTitle")}</h3>
      <ul className="m-0 grid list-none gap-2 p-0">
        {jobs.map((job) => {
          const name = String((job.payload as Record<string, unknown>).filename ?? "");
          const folder = String((job.payload as Record<string, unknown>).folder ?? "");
          const active = ACTIVE.has(job.status);
          return (
            <li key={job.id} className="grid min-w-0 gap-1.5">
              <div className="flex min-w-0 items-center gap-2">
                <span className="flex min-w-0 flex-1 items-baseline gap-2">
                  <Truncate className="text-ui-sm text-foreground">{name}</Truncate>
                  <span className="shrink-0 text-ui-xs text-muted-foreground">{folder}</span>
                </span>
                {job.status === "succeeded" && (
                  <CatalogBadge tone="success" icon={<Check />}>{t("modelDownloadDone")}</CatalogBadge>
                )}
                {job.status === "failed" && (
                  <CatalogBadge tone="warning" icon={<CircleAlert />}>{t("modelDownloadFailedLabel")}</CatalogBadge>
                )}
                {active && (
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={t("modelDownloadCancelLabel").replace("{name}", name)}
                    loading={cancel.isPending && cancel.variables === job.id}
                    onClick={() => cancel.mutate(job.id)}
                  >
                    <X size={13} />
                    {t("modelDownloadCancel")}
                  </Button>
                )}
              </div>
              {active && <Progress value={Math.round((job.progress || 0) * 100)} aria-label={name} />}
              <p
                className={cn(
                  "m-0 min-w-0 break-words text-ui-xs leading-relaxed",
                  job.status === "failed" ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {job.status === "failed" ? job.error || job.message : job.message}
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function MissingList({ missing, onDownload }: { missing: MissingModel[]; onDownload: (one: MissingModel) => void }) {
  const t = useI18n();
  return (
    <section className="grid min-w-0 gap-2 rounded-xl border border-warning/40 bg-panel p-3" aria-label={t("modelMissingTitle")}>
      <div className="grid gap-0.5">
        <h3 className="m-0 text-ui-sm font-semibold text-foreground">{t("modelMissingTitle")}</h3>
        <p className="m-0 text-ui-xs text-muted-foreground">{t("modelMissingDesc")}</p>
      </div>
      <ul className="m-0 grid list-none gap-2 p-0">
        {missing.map((one) => (
          <li key={keyOf(one)} className="flex min-w-0 items-center gap-3">
            <span className="grid min-w-0 flex-1 gap-0.5">
              <span className="flex min-w-0 items-baseline gap-2">
                <Truncate className="text-ui-sm text-foreground" hint={one.url}>{one.name}</Truncate>
                <span className="shrink-0 text-ui-xs text-muted-foreground">{one.folder}</span>
              </span>
              <Truncate className="text-ui-xs text-muted-foreground">
                {t("modelMissingFor").replace("{workflows}", (one.workflows ?? []).map((flow) => flow.label).join(t("listSeparator")))}
              </Truncate>
            </span>
            <Button variant="outline" size="sm" onClick={() => onDownload(one)}>
              <Download size={13} />
              {t("modelMissingDownload")}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FamilyBadge({ model }: { model: ModelFile }) {
  const t = useI18n();
  if (!model.family) return null;
  return (
    <Hint label={model.family_source === "filename" ? t("modelFamilySourceFilename") : t("modelFamilySourceMetadata")}>
      <span className="inline-flex">
        <CatalogBadge tone={model.family_source === "filename" ? "muted" : "primary"}>{model.family}</CatalogBadge>
      </span>
    </Hint>
  );
}

function ModelCard({ instanceId, model, onOpen }: { instanceId: string; model: ModelFile; onOpen: () => void }) {
  const t = useI18n();
  const sub = subFolder(model.name);
  const meta = [model.folder + (sub ? `/${sub}` : ""), model.size != null ? formatBytes(model.size) : ""].filter(Boolean).join(" · ");
  const used = model.used_by?.length ?? 0;
  return (
    <article
      data-catalog-card={keyOf(model)}
      className={cn(
        "relative grid min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_1fr] overflow-hidden rounded-xl border border-border bg-panel transition-colors",
        "hover:border-border-strong hover:bg-panel-subtle",
        "has-[[data-catalog-open]:focus-visible]:border-primary has-[[data-catalog-open]:focus-visible]:ring-2 has-[[data-catalog-open]:focus-visible]:ring-ring",
      )}
    >
      <ModelThumb instanceId={instanceId} model={model} className="aspect-[4/3] w-full" />
      <div className="grid min-w-0 content-start gap-1.5 p-3">
        <h3 className="m-0 min-w-0 text-ui-sm font-semibold leading-snug text-foreground">
          <button
            type="button"
            data-catalog-open
            className="block max-w-full cursor-pointer text-left after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none"
            onClick={onOpen}
          >
            <Truncate>{baseName(model.name)}</Truncate>
          </button>
        </h3>
        <Truncate as="p" className="m-0 text-ui-xs text-muted-foreground">{meta}</Truncate>
        {(model.family || used > 0 || (model.triggers?.length ?? 0) > 0) && (
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <FamilyBadge model={model} />
            {used > 0 && <CatalogBadge tone="success" icon={<Workflow />}>{t("modelUsedCount").replace("{n}", String(used))}</CatalogBadge>}
            {(model.triggers?.length ?? 0) > 0 && (
              <CatalogBadge tone="muted">{t("modelTriggerCount").replace("{n}", String(model.triggers?.length ?? 0))}</CatalogBadge>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <Button
      variant="outline"
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      }}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      {label}
    </Button>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 gap-0.5">
      <dt className="text-ui-xs text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 break-words text-ui-sm text-foreground">{children}</dd>
    </div>
  );
}

function ModelDetailPage({ instanceId, model }: { instanceId: string; model: ModelFile }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const meta = useQuery({
    queryKey: ["model-library-detail", instanceId, model.folder, model.name],
    queryFn: () => getModelDetail(instanceId, model.folder, model.name),
  });
  const Icon = folderIcon(model.folder);
  const entries = Object.entries(meta.data?.metadata ?? {});
  const triggers = model.triggers ?? [];
  return (
    <CatalogDetail
      icon={<Icon />}
      title={baseName(model.name)}
      badges={<FamilyBadge model={model} />}
      meta={[model.folder, model.size != null ? formatBytes(model.size) : ""].filter(Boolean).join(" · ")}
      actions={<CopyButton text={model.name} label={t("modelCopyName")} />}
      aside={
        <CatalogSection title={t("modelFileFacts")}>
          <dl className="m-0 grid gap-3">
            <Fact label={t("modelFolder")}>{model.folder}</Fact>
            <Fact label={t("modelFileName")}>{model.name}</Fact>
            {model.size != null && <Fact label={t("modelSize")}>{formatBytes(model.size)}</Fact>}
            {model.modified != null && (
              <Fact label={t("modelModified")}>{new Date(model.modified * 1000).toLocaleString(locale)}</Fact>
            )}
            {model.family && (
              <Fact label={t("modelFamily")}>
                {model.family}
                <span className="block text-ui-xs text-muted-foreground">
                  {model.family_source === "filename" ? t("modelFamilySourceFilename") : t("modelFamilySourceMetadata")}
                </span>
              </Fact>
            )}
          </dl>
        </CatalogSection>
      }
    >
      {model.has_preview && (
        <ModelThumb instanceId={instanceId} model={model} className="max-h-[420px] w-full rounded-xl object-contain" />
      )}
      {triggers.length > 0 && (
        <CatalogSection title={t("modelTriggers")} count={triggers.length}>
          {model.triggers_source === "tags" && <p className="m-0 text-ui-xs text-muted-foreground">{t("modelTriggersFromTags")}</p>}
          <div className="flex min-w-0 flex-wrap gap-1.5">
            {triggers.map((word) => (
              <Hint key={word} label={t("modelTriggerCopy").replace("{word}", word)}>
                <button
                  type="button"
                  className="cursor-pointer rounded-full bg-secondary px-2.5 py-1 text-ui-xs text-foreground hover:bg-secondary/70"
                  onClick={() => void navigator.clipboard?.writeText(word)}
                >
                  {word}
                </button>
              </Hint>
            ))}
          </div>
        </CatalogSection>
      )}
      <CatalogSection title={t("modelUsedBy")} count={model.used_by?.length ?? 0}>
        {(model.used_by?.length ?? 0) > 0 ? (
          <ul className="m-0 grid list-none gap-1 p-0">
            {(model.used_by ?? []).map((flow) => (
              <li key={flow.id} className="flex min-w-0 items-center gap-2 text-ui-sm text-foreground">
                <Workflow size={13} className="shrink-0 text-muted-foreground" />
                <Truncate hint={flow.id !== flow.label ? flow.id : undefined}>{flow.label}</Truncate>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("modelUsedByNone")}</p>
        )}
      </CatalogSection>
      {(meta.data?.tags?.length ?? 0) > 0 && (
        <CatalogSection title={t("modelTags")} count={meta.data?.tags?.length}>
          <div className="flex min-w-0 flex-wrap gap-1.5">
            {(meta.data?.tags ?? []).slice(0, 60).map((one) => (
              <span key={one.tag} className="rounded-full bg-secondary px-2.5 py-1 text-ui-xs text-foreground">
                {one.tag}
                <span className="ml-1 tabular-nums text-muted-foreground">{one.count}</span>
              </span>
            ))}
          </div>
        </CatalogSection>
      )}
      <CatalogSection title={t("modelMetadata")} count={entries.length || undefined}>
        {meta.isLoading ? (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("modelMetadataLoading")}</p>
        ) : meta.isError ? (
          <p className="m-0 text-ui-xs text-destructive">{errorText(meta.error)}</p>
        ) : entries.length === 0 ? (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("modelMetadataEmpty")}</p>
        ) : (
          <dl className="m-0 grid min-w-0 grid-cols-[minmax(120px,max-content)_minmax(0,1fr)] gap-x-4 gap-y-1.5">
            {entries.map(([key, value]) => (
              <React.Fragment key={key}>
                <Truncate as="dt" className="text-ui-xs text-muted-foreground">{key}</Truncate>
                <Truncate as="dd" lines={3} className="m-0 break-all text-ui-xs text-foreground">{value}</Truncate>
              </React.Fragment>
            ))}
          </dl>
        )}
      </CatalogSection>
    </CatalogDetail>
  );
}

function sourceLabel(t: Translate, resolved: ModelResolved): string {
  if (resolved.source === "huggingface") return t("modelDownloadSourceHuggingface");
  if (resolved.source === "civitai") return t("modelDownloadSourceCivitai");
  let host = "";
  try {
    host = new URL(resolved.url).host;
  } catch {
    host = resolved.url;
  }
  return t("modelDownloadSourceDirect").replace("{host}", host);
}

function ModelDownloadDialog({
  instance,
  workspaceId,
  library,
  seed,
  onClose,
  onStarted,
}: {
  instance: PluginInstance;
  workspaceId: string;
  library: ModelLibrary;
  seed: DownloadSeed;
  onClose: () => void;
  onStarted: (job: Job) => void;
}) {
  const t = useI18n();
  const [url, setUrl] = React.useState(seed.url ?? "");
  const [filename, setFilename] = React.useState(seed.name ?? "");
  const [folder, setFolder] = React.useState(seed.folder ?? "");
  const resolve = useMutation({
    mutationFn: (link: string) => resolveModelLink(instance.id, link),
    onSuccess: (found) => {
      setFilename((current) => current || seed.name || found.filename);
      setFolder((current) => current || seed.folder || found.folder);
    },
  });
  const start = useMutation({
    mutationFn: () =>
      startModelDownload(instance.id, {
        workspace_id: workspaceId,
        url: resolve.data?.url ?? url.trim(),
        folder,
        filename: filename.trim(),
      }),
    onSuccess: (job) => {
      onStarted(job);
      onClose();
    },
  });
  const resolveRef = React.useRef(resolve.mutate);
  resolveRef.current = resolve.mutate;
  React.useEffect(() => {
    if (seed.url) resolveRef.current(seed.url);
  }, [seed.url]);

  const taken = React.useMemo(
    () => new Set((library.models ?? []).filter((model) => model.folder === folder).map((model) => norm(model.name))),
    [library.models, folder],
  );
  const exists = Boolean(folder && filename.trim() && taken.has(norm(filename)));
  const route = library.download?.route ?? "none";
  const resolved = resolve.data;
  const nameOk = plainName(filename);
  const canStart = Boolean(resolved && folder && nameOk && !exists && route !== "none");
  const folderOptions = [...(library.folders ?? [])]
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
    .map((one) => ({ value: one.name, label: t("modelDownloadFolderOption").replace("{name}", one.name).replace("{n}", String(one.count)) }));

  return (
    <ModalShell
      open
      onOpenChange={(open) => !open && onClose()}
      title={t("modelDownloadTitle").replace("{name}", instance.name)}
      className="w-[560px] max-w-[calc(100vw-32px)]"
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={!canStart} loading={start.isPending} onClick={() => start.mutate()}>
            <Download size={13} />
            {t("modelDownloadConfirm").replace("{folder}", folder || "…")}
          </Button>
        </div>
      }
    >
      <div className="grid min-w-0 gap-4">
        <label className="grid min-w-0 gap-1.5">
          <span className="text-ui-sm font-medium text-foreground">{t("modelDownloadLink")}</span>
          <div className="flex min-w-0 gap-2">
            <Input
              className="min-w-0 flex-1"
              value={url}
              placeholder={t("modelDownloadLinkPlaceholder")}
              onChange={(event) => setUrl(event.target.value)}
              onKeyDown={(event) => {
                if (isImeKeystroke(event)) return;
                if (event.key === "Enter" && url.trim()) resolve.mutate(url.trim());
              }}
            />
            <Button variant="outline" disabled={!url.trim()} loading={resolve.isPending} onClick={() => resolve.mutate(url.trim())}>
              {t("modelDownloadResolve")}
            </Button>
          </div>
        </label>
        {resolve.isError && <p className="m-0 break-words text-ui-sm text-destructive">{errorText(resolve.error)}</p>}
        {resolved && (
          <>
            <dl className="m-0 grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3 rounded-lg bg-secondary/50 p-3">
              <Fact label={t("modelDownloadSource")}>{sourceLabel(t, resolved)}</Fact>
              <Fact label={t("modelDownloadSize")}>
                {resolved.size != null ? formatBytes(resolved.size) : t("modelDownloadSizeUnknown")}
              </Fact>
              {resolved.title && <Fact label={t("modelFileName")}>{resolved.title}</Fact>}
              {resolved.family && <Fact label={t("modelFamily")}>{resolved.family}</Fact>}
              {(resolved.triggers ?? []).length > 0 && (
                <div className="col-span-2">
                  <Fact label={t("modelTriggers")}>{(resolved.triggers ?? []).join(t("listSeparator"))}</Fact>
                </div>
              )}
            </dl>
            <label className="grid min-w-0 gap-1.5">
              <span className="text-ui-sm font-medium text-foreground">{t("modelDownloadFilename")}</span>
              <Input value={filename} onChange={(event) => setFilename(event.target.value)} aria-invalid={!nameOk || exists} />
              {!nameOk && filename && <span className="text-ui-xs text-destructive">{t("modelDownloadFilenameBad")}</span>}
            </label>
            <div className="grid min-w-0 gap-1.5">
              <span className="text-ui-sm font-medium text-foreground">{t("modelDownloadFolder")}</span>
              <OptionPicker
                ariaLabel={t("modelDownloadFolder")}
                value={folder}
                onChange={setFolder}
                options={folderOptions}
                placeholder={t("modelDownloadFolderPick")}
                searchPlaceholder={t("modelDownloadFolderSearch")}
              />
            </div>
            {exists && (
              <div role="alert" className="grid gap-2 rounded-lg border border-warning/40 p-3 text-ui-sm text-foreground">
                <span>{t("modelDownloadExists").replace("{folder}", folder).replace("{name}", filename.trim())}</span>
                <span>
                  <Button variant="outline" size="sm" onClick={() => setFilename(freeName(filename.trim(), taken))}>
                    {t("modelDownloadUseSuggestion").replace("{name}", freeName(filename.trim(), taken))}
                  </Button>
                </span>
              </div>
            )}
            <p className={cn("m-0 break-words text-ui-xs leading-relaxed", route === "none" ? "text-destructive" : "text-muted-foreground")}>
              {route === "none" && <strong className="mr-1">{t("modelDownloadCannot")}</strong>}
              {library.download?.note}
              {route === "local" && ` ${t("modelDownloadDiskLocal")}`}
              {route === "manager" && ` ${t("modelDownloadDiskRemote")}`}
            </p>
            {start.isError && <p className="m-0 break-words text-ui-sm text-destructive">{errorText(start.error)}</p>}
          </>
        )}
      </div>
    </ModalShell>
  );
}
