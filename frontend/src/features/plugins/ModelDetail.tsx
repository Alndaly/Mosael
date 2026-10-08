import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  Copy,
  ExternalLink,
  Eye,
  FolderTree,
  ImageUp,
  RotateCcw,
  Search,
  SearchCheck,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";

import {
  getModelDetail,
  getModelLookup,
  markModelNsfw,
  modelPreviewUrl,
  modelThumbnailUrl,
  saveModelPreview,
  startModelLookup,
  type Job,
  type ModelFile,
  type ModelLibrary,
  type ModelLookupFound,
  type ModelNsfw,
  type ModelPreviewTools,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n, usePreferences } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { LibraryDetail, LibrarySection } from "@/components/app/LibraryBrowser";
import { useImagePreview } from "@/components/app/image-preview";
import { ConfirmDialog } from "@/components/app/modals";
import { VideoPlayer } from "@/components/app/media-playback";
import { ViewFullSizeButton } from "@/components/app/view-full-size";
import {
  ModelThumb,
  PreviewOriginMark,
  folderIcon,
  modelBaseName,
  modelSubFolder,
  nsfwSummary,
} from "@/components/generation/ModelThumb";
import {
  previewPick,
  previewTreatment,
  useModelPreviewSettings,
  type ModelPreviewSettings,
} from "@/components/generation/modelPreviewSettings";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { ModelActionsContext, type ModelActions } from "@/features/plugins/modelActions";
import { EncoderBadge, EncoderOverview, useEncoderNote } from "@/features/plugins/ModelEncoder";
import {
  familySource,
  generationTargets,
  targetNote,
  withLookupFound,
  withPreviewSaved,
  type GenerationTarget,
} from "@/features/plugins/modelLibraryView";
import { formatBytes } from "@/lib/bytes";
import { formedGroups } from "@/lib/entryNames";
import { GENERATION_KINDS } from "@/lib/generationCapabilities";
import { handOffToGeneration } from "@/lib/generationHandoff";
import { useGenerationOptions } from "@/lib/generationOptions";
import { cn } from "@/lib/utils";

/**
 * 一个模型文件的详情页,和它背后的那几样本事(菜单、详情里的按钮要的:在 Civitai 上找、存为预览图、标 NSFW、看大图、
 * 用它生成……)。模型库弹窗(ModelLibrary)和 ComfyUI 工作台的模型库面板(workbench/ModelsPanel)用的是**同一份**:
 * 详情页的骨架是 LibraryDetail,本事由 `useModelActionsHost` 造出来、经 ModelActionsContext 交给卡片、行、详情页。
 * 在哪打开详情由用的那一处定(模型库里是弹窗里换一页,工作台里是一个大弹窗)。
 */

const ACTIVE = new Set(["queued", "running"]);
const keyOf = (model: { folder: string; name: string }) => `${model.folder}/${model.name}`;
const baseName = modelBaseName;
const subFolder = modelSubFolder;

/**
 * 菜单和详情页要的那几样本事,连同它们背后的后台任务(在 Civitai 上找)和确认框(存为预览图写的是那台服务器,先问)。
 * 交回本事(放进 ModelActionsContext)、在跑的查找(模型库的「补图」也记在这里)和要摆出来的确认框。
 */
export function useModelActionsHost({
  instanceId,
  instanceName,
  workspaceId,
  queryKey,
  shown,
  tools,
  onOpen,
}: {
  instanceId: string;
  instanceName: string;
  workspaceId: string;
  /** 模型库那份查询的键(标了 NSFW 当场改它,见 useModelLibrary) */
  queryKey: readonly unknown[];
  /** 「看大图」能跟着左右翻的那一批 */
  shown: ModelFile[];
  tools: ModelPreviewTools | undefined;
  /** 打开详情(`section`:直接跳到哪一节) */
  onOpen: (model: ModelFile, section: "used" | null) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [settings] = useModelPreviewSettings();
  //: 找完一批、存回一张之后作废的是这个连接的模型库(不管挑法是哪一种)
  const libraryPrefix = React.useMemo(() => ["model-library", instanceId], [instanceId]);
  //: 「在 Civitai 上找」「补图」:后台任务,这次打开之后发起的。做完了先把对上的那几条当场改进记着的模型库(原链接、预览图
  //: 从哪来、NSFW —— 不等重列),再在后台重新列一遍
  const lookups = useLookupJobs(
    instanceId,
    (found) => qc.setQueriesData<ModelLibrary>({ queryKey: libraryPrefix }, (old) => withLookupFound(old, found)),
    () => void qc.invalidateQueries({ queryKey: libraryPrefix }),
  );
  //: 「存为预览图」先确认:写的是那台服务器
  const [saving, setSaving] = React.useState<ModelFile | null>(null);
  const save = useMutation({
    mutationFn: ({ model, confirmed }: { model: ModelFile; confirmed: boolean }) =>
      saveModelPreview(instanceId, { folder: model.folder, name: model.name, pick: previewPick(settings), confirmed }),
    onSuccess: (_saved, { model }) => {
      setSaving(null);
      //: 存好了那一条当场就是那台服务器上的:「存为预览图」不会在重列回来之前又亮起来、能再点一次
      qc.setQueriesData<ModelLibrary>({ queryKey: libraryPrefix }, (old) => withPreviewSaved(old, model));
      void qc.invalidateQueries({ queryKey: libraryPrefix });
    },
  });
  const actions = useModelActions({
    instanceId,
    workspaceId,
    queryKey,
    shown,
    settings,
    tools,
    lookingUp: lookups.running,
    previewSaving: save.isPending ? save.variables.model : null,
    onLookup: lookups.add,
    onSave: setSaving,
    onOpen,
  });
  const dialogs = (
    <ConfirmDialog
      open={saving !== null}
      title={t("modelSavePreviewTitle").replace("{name}", saving ? baseName(saving.name) : "")}
      body={[
        //: 视频写回去 ComfyUI 自己看不到(它和 pysssss 只认图):照实说,不说「ComfyUI 里也看得到」
        t(saving?.preview_kind === "video" ? "modelSavePreviewBodyVideo" : "modelSavePreviewBody")
          .replace("{server}", instanceName).replace("{place}", saving ? placeOf(saving) : ""),
        saving?.source?.how === "filename" ? t("modelSavePreviewFilenameMatch") : "",
        save.isError ? errorText(save.error) : "",
      ].filter(Boolean).join("\n\n")}
      confirmLabel={t("modelSavePreview")}
      pending={save.isPending}
      onCancel={() => {
        save.reset();
        setSaving(null);
      }}
      onConfirm={() => saving && save.mutate({ model: saving, confirmed: saving.source?.how === "filename" })}
    />
  );
  return { actions, lookups, dialogs };
}

/**
 * 卡片、列表行、详情页的菜单要的那几样本事(见 ModelMenu)。生成选项、标记的改动、灯箱都在这里接上。
 * 标 NSFW 之后**不**让插件再列一遍:宿主回的是新的判断,直接改进模型库的那份缓存 —— 生成表单的下拉、工作台面板
 * 读的是同一份,跟着变。
 */
function useModelActions({
  instanceId,
  workspaceId,
  queryKey,
  shown,
  settings,
  tools,
  lookingUp,
  previewSaving,
  onLookup,
  onSave,
  onOpen,
}: {
  instanceId: string;
  workspaceId: string;
  queryKey: readonly unknown[];
  shown: ModelFile[];
  settings: ModelPreviewSettings;
  tools: ModelPreviewTools | undefined;
  /** 有任务在找的文件(`目录/名字`) */
  lookingUp: Set<string>;
  /** 正在存回预览图的那一个(确认之后、存好之前) */
  previewSaving: ModelFile | null;
  onLookup: (job: Job) => void;
  onSave: (model: ModelFile) => void;
  onOpen: (model: ModelFile, section: "used" | null) => void;
}): ModelActions {
  const t = useI18n();
  const qc = useQueryClient();
  const generation = useGenerationOptions(GENERATION_KINDS);
  const { openImagePreview } = useImagePreview();
  const mark = useMutation({
    mutationFn: ({ model, nsfw }: { model: ModelFile; nsfw: boolean | null }) =>
      markModelNsfw(instanceId, { folder: model.folder, name: model.name, nsfw }),
    onSuccess: (verdict, { model }) => {
      qc.setQueryData<ModelLibrary>(queryKey, (old) =>
        old ? { ...old, models: (old.models ?? []).map((one) => (keyOf(one) === keyOf(model) ? { ...one, nsfw: verdict } : one)) } : old,
      );
    },
  });
  //: 菜单在打开那一刻才读这些(见 ModelMenu):放在一个 ref 里,本事本身不跟着变 —— 它在上下文里,一变,画着的几百张卡
  //: 都要重画(搜索框里打一个字,筛出来的那份清单就是新的)。
  const onLookupRef = React.useRef(onLookup);
  onLookupRef.current = onLookup;
  const lookup = useMutation({
    mutationFn: ({ model, pick }: { model: ModelFile; pick: "safest" | "cover" }) => startModelLookup(instanceId, {
      workspace_id: workspaceId, files: [{ folder: model.folder, name: model.name }], refresh: true, pick,
    }),
    onSuccess: (job) => onLookupRef.current(job),
  });
  //: 点下去到任务建好之间(发起的那个请求还没回来)也算在找:不然按钮要等请求回来才转圈,中间那一下能再点一次
  const starting = lookup.isPending ? keyOf(lookup.variables.model) : null;
  const latest = React.useRef({ onOpen, shown, settings, generation, openImagePreview, mark: mark.mutate, t, tools, lookingUp,
                                starting, previewSaving, onLookup, onSave, lookup: lookup.mutate });
  latest.current = { onOpen, shown, settings, generation, openImagePreview, mark: mark.mutate, t, tools, lookingUp, starting,
                     previewSaving, onLookup, onSave, lookup: lookup.mutate };
  return React.useMemo<ModelActions>(() => {
    //: 能跟着翻的:看得清的(模糊着、不显示的不进来 —— 点开一张是明确要看这一张,翻到别的就等于没经同意替人把它们都看清了)
    const visible = (model: ModelFile) =>
      model.has_preview && previewTreatment(latest.current.settings, Boolean(model.nsfw?.flagged)) === "clear";
    const lookupRunning = (model: ModelFile) =>
      latest.current.starting === keyOf(model) || latest.current.lookingUp.has(keyOf(model));
    return {
      open: (model) => latest.current.onOpen(model, null),
      openUsed: (model) => latest.current.onOpen(model, "used"),
      targets: (model) => generationTargets(latest.current.generation.options, instanceId, model),
      targetsLoading: () => latest.current.generation.pending,
      generate: (model, target) =>
        handOffToGeneration({
          providerProfileId: target.option.provider_profile_id,
          kind: target.option.kind,
          model: target.option.model,
          declared: { [target.key]: target.value },
          promptWords: model.triggers_source === "metadata" ? model.triggers ?? [] : [],
        }),
      largeUnavailable: (model) => (!model.has_preview ? latest.current.t("modelNoPreview") : null),
      showLarge: (model) => {
        const pick = previewPick(latest.current.settings);
        const item = (one: ModelFile) => ({
          src: modelPreviewUrl(instanceId, one.folder, one.name, pick),
          title: baseName(one.name),
          ...(one.preview_kind === "video" ? { video: true } : {}),
        });
        //: 能左右翻的是当前筛出来的、看得清的那一批;点的是模糊着、不显示的那一张时只开它
        const gallery = visible(model)
          ? latest.current.shown.filter((one) => keyOf(one) === keyOf(model) || visible(one)).map(item)
          : [item(model)];
        latest.current.openImagePreview({ ...item(model), gallery });
      },
      markNsfw: (model, nsfw) => latest.current.mark({ model, nsfw }),
      openSource: (model) => {
        if (model.source?.page) window.open(model.source.page, "_blank", "noopener,noreferrer");
      },
      lookUp: (model) => latest.current.lookup({ model, pick: previewPick(latest.current.settings) }),
      lookupUnavailable: (model) => {
        const { tools: ways, t: say } = latest.current;
        if (lookupRunning(model)) return say("modelLookupRunning");
        if (ways && !ways.lookup) return say("modelLookupUnavailable");
        return null;
      },
      lookupRunning,
      savePreview: (model) => latest.current.onSave(model),
      saveUnavailable: () => {
        const { tools: ways, t: say } = latest.current;
        if (ways && !ways.save) return ways.save_note || say("modelSavePreviewUnavailable");
        return null;
      },
      savingPreview: (model) => {
        const { previewSaving } = latest.current;
        return previewSaving !== null && keyOf(previewSaving) === keyOf(model);
      },
    };
  }, [instanceId]);
}

/**
 * 这次打开之后发起的「在 Civitai 上找」「补图」任务:在跑的隔一会儿读一次(模型库自己的那个口,做完了带着对上的那几条
 * 现在的样子)。有一个做完了:先把对上的交给 `onFound`(当场改记着的模型库),再 `onDone`(后台重列)。
 * 交出哪些文件正在找(详情里那颗「在 Civitai 上找」转圈)、有没有一批补图在跑。
 */
function useLookupJobs(
  instanceId: string,
  onFound: (found: ModelLookupFound[]) => void,
  onDone: () => void,
): { add: (job: Job) => void; running: Set<string>; batchRunning: boolean } {
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const watching = jobs.filter((job) => ACTIVE.has(job.status)).map((job) => job.id);
  const live = useQuery({
    queryKey: ["model-lookups", instanceId, watching],
    queryFn: () => Promise.all(watching.map((id) => getModelLookup(instanceId, id))),
    enabled: watching.length > 0,
    refetchInterval: 1500,
  });
  const callback = React.useRef({ onFound, onDone });
  callback.current = { onFound, onDone };
  React.useEffect(() => {
    const fresh = live.data ?? [];
    if (!fresh.length) return;
    setJobs((list) => list.map((job) => fresh.find((one) => one.job.id === job.id)?.job ?? job));
    const done = fresh.filter((one) => !ACTIVE.has(one.job.status));
    if (!done.length) return;
    const found = done.flatMap((one) => one.result?.found ?? []);
    if (found.length) callback.current.onFound(found);
    callback.current.onDone();
  }, [live.data]);
  const add = React.useCallback((job: Job) => setJobs((list) => [job, ...list]), []);
  const active = jobs.filter((job) => ACTIVE.has(job.status));
  const running = new Set(active.flatMap((job) =>
    ((job.payload as { files?: { folder: string; name: string }[] }).files ?? []).map((one) => keyOf(one))));
  const batchRunning = active.some((job) => (job.payload as { save?: boolean }).save === true);
  return { add, running, batchRunning };
}

export function FamilyBadge({ model, pairs = false }: { model: ModelFile; pairs?: boolean }) {
  const t = useI18n();
  const source = familySource(model);
  //: 文件头那台 ComfyUI 自己也读不了(0 字节、没下完、截断):只这一个文件说一句,别的照常列。叠在卡片名字那颗按钮盖满整张卡的
  //: `after:` 上面,悬停得到说明(和卡片上「几张工作流在用」同一个做法)
  if (model.broken) {
    return (
      <Hint label={t("modelBrokenHint")}>
        <span className="relative z-10 inline-flex" data-model-broken="">
          <CatalogBadge tone="warning">{t("modelBroken")}</CatalogBadge>
        </span>
      </Hint>
    );
  }
  //: 文本编码器不贴底模:写它是哪一种(列表里那一格接着写常配哪几种)
  if (model.encoder) return <EncoderBadge encoder={model.encoder} pairs={pairs} />;
  if (!model.family || !source) return null;
  return (
    <Hint label={t(source.hint)}>
      <span className="inline-flex">
        <CatalogBadge tone={source.certain ? "primary" : "muted"}>{model.family}</CatalogBadge>
      </span>
    </Hint>
  );
}

/** 文件所在的位置:目录,带子目录时接上子目录(`loras/sub`)。 */
export const placeOf = (model: ModelFile) => {
  const sub = subFolder(model.name);
  return model.folder + (sub ? `/${sub}` : "");
};

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

/** 概要里的一行:左边名字,右边内容;内容下面可以跟一行弱一档的说明(判据)。 */
function OverviewRow({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 grid-cols-[88px_minmax(0,1fr)] items-baseline gap-x-3">
      <dt className="text-ui-xs text-muted-foreground">{label}</dt>
      <dd className="m-0 grid min-w-0 gap-1 text-ui-sm text-foreground">
        {children}
        {note && <span className="text-ui-xs leading-relaxed text-muted-foreground">{note}</span>}
      </dd>
    </div>
  );
}

/** 「存为预览图」:把 Mosael 里显示的那张别处的示例图(或那段示例视频)写回那台服务器(先确认);写不回时点不了并说缺什么。 */
function SavePreviewButton({ model, actions, className }: { model: ModelFile; actions: ModelActions; className?: string }) {
  const t = useI18n();
  const why = actions.saveUnavailable(model);
  return (
    <Hint label={t(model.preview_kind === "video" ? "modelSavePreviewHintVideo" : "modelSavePreviewHint")} disabledReason={why}>
      <Button variant="secondary" size="sm" className={cn("shadow-[var(--shadow-floating)]", className)} disabled={Boolean(why)}
              loading={actions.savingPreview(model)} onClick={() => actions.savePreview(model)}>
        <ImageUp size={13} />
        {t("modelSavePreview")}
      </Button>
    </Hint>
  );
}

const HOW_NOTES = {
  download: "modelSourceHowDownload",
  sha256: "modelSourceHowSha256",
  filename: "modelSourceHowFilename",
  metadata: "modelSourceHowMetadata",
} as const;

/**
 * 概要里的「原链接」一行:原站上那一页(Civitai 的版本页、HuggingFace / ModelScope 的文件页),下面一行说是怎么知道的;
 * 没有就说没有、怎么补(经 Mosael 下载的会记下,别的「在 Civitai 上找」)—— 不按文件名猜一个链接。
 */
function SourceRow({ model }: { model: ModelFile }) {
  const t = useI18n();
  const actions = React.useContext(ModelActionsContext);
  const source = model.source;
  const how = source ? HOW_NOTES[source.how as keyof typeof HOW_NOTES] : undefined;
  //: 在找的时候转圈,直到任务做完(不是发起任务的那个请求回来);说明里照旧写为什么点不了(正在找、这台找不了)
  const why = actions?.lookupUnavailable(model);
  const find = actions && (
    <Hint label={t("modelLookupHint")} disabledReason={why}>
      <Button variant="ghost" size="sm" disabled={Boolean(why)} loading={actions.lookupRunning(model)}
              onClick={() => actions.lookUp(model)}>
        <SearchCheck size={13} />
        {t(model.has_preview ? "modelLookup" : "modelLookupPreview")}
      </Button>
    </Hint>
  );
  return (
    <OverviewRow label={t("modelSourceRow")} note={source ? (how ? t(how) : undefined) : t("modelSourceNone")}>
      <span className="flex min-w-0 flex-wrap items-center gap-1.5">
        {source ? (
          <a href={source.page} target="_blank" rel="noreferrer noopener" data-model-source=""
             className="inline-flex min-w-0 max-w-full items-center gap-1 text-primary no-underline hover:underline">
            <ExternalLink size={13} aria-hidden className="shrink-0" />
            <Truncate>{source.page.replace(/^https?:\/\//, "")}</Truncate>
          </a>
        ) : (
          <span className="text-muted-foreground">{t("modelSourceUnknown")}</span>
        )}
        {find}
      </span>
    </OverviewRow>
  );
}

/**
 * 概要里的 NSFW 一行:结论(手动标的说是手动标的)、每一条依据;按钮改手动标记 —— 判错了能改,标过的能改回自动判断。
 * 改了马上生效(宿主回新的判断,模型库那份缓存跟着改)。
 */
function NsfwRow({ model }: { model: ModelFile }) {
  const t = useI18n();
  const actions = React.useContext(ModelActionsContext);
  const nsfw: ModelNsfw = model.nsfw ?? { flagged: false, manual: null, reasons: [] };
  const summary = nsfwSummary(nsfw, t);
  return (
    <OverviewRow label={t("modelNsfwRow")} note={summary.reasons.join(" · ") || undefined}>
      <span className="flex min-w-0 flex-wrap items-center gap-1.5">
        <CatalogBadge tone={nsfw.flagged ? "warning" : "muted"}>{summary.label}</CatalogBadge>
        {actions && (
          <>
            <Button variant="ghost" size="sm" onClick={() => actions.markNsfw(model, !nsfw.flagged)}>
              {nsfw.flagged ? <ShieldCheck size={13} /> : <ShieldAlert size={13} />}
              {t(nsfw.flagged ? "modelNsfwUnmark" : "modelNsfwMark")}
            </Button>
            {nsfw.manual != null && (
              <Button variant="ghost" size="sm" onClick={() => actions.markNsfw(model, null)}>
                <RotateCcw size={13} />
                {t("modelNsfwClearMark")}
              </Button>
            )}
          </>
        )}
      </span>
    </OverviewRow>
  );
}

/** 一个触发词:点一下复制,复制了就打个勾。 */
function TriggerChip({ word }: { word: string }) {
  const t = useI18n();
  const [copied, setCopied] = React.useState(false);
  return (
    <Hint label={copied ? t("modelTriggerCopied") : t("modelTriggerCopy").replace("{word}", word)}>
      <button
        type="button"
        className="inline-flex h-7 max-w-full cursor-pointer items-center gap-1 rounded-full bg-secondary px-2.5 text-ui-xs text-foreground hover:bg-secondary/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => {
          void navigator.clipboard?.writeText(word);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        }}
      >
        <Truncate>{word}</Truncate>
        {copied && <Check size={12} aria-hidden className="shrink-0 text-success" />}
      </button>
    </Hint>
  );
}

/** 元数据值里那段 JSON(合并模型的 sd_merge_models、训练参数……)按两格缩进排开;不是 JSON 就是 null。 */
function prettyJson(value: string): string | null {
  const text = value.trim();
  if (!(text.startsWith("{") || text.startsWith("["))) return null;
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return null;
  }
}

/** 训练标签先摆这么多个(出现最多的那些),其余点「显示全部」。 */
const TAGS_SHOWN = 24;

/** 长于这个(或带换行、或是 JSON)的值默认折叠成一行预览。 */
const LONG_VALUE = 120;

/**
 * 元数据的一行:键 + 值。短值直接摆;长值默认折成一行预览(截在 JS 里,悬停不弹一整段几千字的说明),能展开、
 * 能复制;JSON 展开后按缩进排开。展开的值在自己的框里横竖都能滚,不撑宽右栏。
 */
function MetadataRow({ name, value }: { name: string; value: string }) {
  const t = useI18n();
  const pretty = React.useMemo(() => prettyJson(value), [value]);
  const long = Boolean(pretty) || value.length > LONG_VALUE || value.includes("\n");
  const [open, setOpen] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const flat = value.replace(/\s+/g, " ");
  return (
    <div data-meta-row="" className="grid min-w-0 grid-cols-[minmax(96px,32%)_minmax(0,1fr)] gap-x-3 border-b border-divider py-2 last:border-b-0">
      <Truncate as="dt" className="pt-0.5 font-mono text-ui-2xs text-muted-foreground">{name}</Truncate>
      <dd className="m-0 grid min-w-0 gap-1.5">
        {!long ? (
          <span className="min-w-0 break-all text-ui-xs text-foreground">{value}</span>
        ) : (
          <>
            {open ? (
              <pre
                className={cn(
                  "m-0 max-h-80 min-w-0 overflow-auto rounded-md bg-muted/60 p-2.5 font-mono text-ui-2xs leading-[1.55] text-foreground",
                  pretty ? "whitespace-pre" : "whitespace-pre-wrap break-all",
                )}
              >
                {pretty ?? value}
              </pre>
            ) : (
              <span className="min-w-0 break-all font-mono text-ui-2xs leading-relaxed text-foreground">
                {flat.length > LONG_VALUE ? `${flat.slice(0, LONG_VALUE)}…` : flat}
              </span>
            )}
            <span className="flex flex-wrap items-center gap-1">
              <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" aria-expanded={open} onClick={() => setOpen(!open)}>
                <ChevronDown className={cn("transition-transform duration-100", open && "rotate-180")} />
                {open ? t("modelMetaCollapse") : t("modelMetaExpand")}
              </Button>
              <IconButton
                label={t("modelMetaCopy").replace("{key}", name)}
                className="text-muted-foreground"
                onClick={() => {
                  void navigator.clipboard?.writeText(value);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 1200);
                }}
              >
                {copied ? <Check className="text-success" /> : <Copy />}
              </IconButton>
              <span className="text-ui-2xs tabular-nums text-muted-foreground">{t("modelMetaLength").replace("{n}", String(value.length))}</span>
            </span>
          </>
        )}
      </dd>
    </div>
  );
}

/** 元数据:搜索框 + 键值表。几百个键的(训练脚本写的 ss_*)靠搜。 */
function MetadataSection({ entries, loading, error }: { entries: [string, string][]; loading: boolean; error: unknown }) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? entries.filter(([key, value]) => key.toLowerCase().includes(needle) || value.toLowerCase().includes(needle))
    : entries;
  return (
    <LibrarySection title={t("modelMetadata")} count={entries.length || undefined}>
      {loading ? (
        <p className="m-0 text-ui-xs text-muted-foreground">{t("modelMetadataLoading")}</p>
      ) : error ? (
        <p className="m-0 text-ui-xs text-destructive">{errorText(error)}</p>
      ) : entries.length === 0 ? (
        <p className="m-0 text-ui-xs text-muted-foreground">{t("modelMetadataEmpty")}</p>
      ) : (
        <>
          {entries.length > 1 && (
            <label className="relative min-w-0">
              <Search size={14} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="search"
                className="pl-9"
                placeholder={t("modelMetaSearch")}
                aria-label={t("modelMetaSearch")}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
          )}
          {shown.length > 0 ? (
            <dl className="m-0 grid min-w-0">
              {shown.map(([key, value]) => (
                <MetadataRow key={key} name={key} value={value} />
              ))}
            </dl>
          ) : (
            <p className="m-0 text-ui-xs text-muted-foreground">{t("modelMetaNoMatch")}</p>
          )}
        </>
      )}
    </LibrarySection>
  );
}

/**
 * 「用它生成」:交给 AI 工作台,选中那张工作流、那一格填上这个文件。只有一张能选它的就直接去;几张就让人挑
 * (在用它的排前面,写着「已经在用它」);一张都没有就点不了并说为什么。
 */
function UseToGenerate({
  targets,
  loading,
  onPick,
}: {
  targets: GenerationTarget[];
  loading: boolean;
  onPick: (target: GenerationTarget) => void;
}) {
  const t = useI18n();
  const formed = formedGroups(targets.map((target) => target.option));
  if (targets.length === 0) {
    return (
      <Hint label={t("modelUseToGenerateDesc")} disabledReason={loading ? t("modelUseToGenerateLoading") : t("modelUseToGenerateNone")}>
        <Button disabled>
          <Sparkles size={13} />
          {t("modelUseToGenerate")}
        </Button>
      </Hint>
    );
  }
  if (targets.length === 1) {
    return (
      <Hint label={t("modelUseToGenerateWith").replace("{workflow}", targets[0].name)}>
        <Button onClick={() => onPick(targets[0])}>
          <Sparkles size={13} />
          {t("modelUseToGenerate")}
        </Button>
      </Hint>
    );
  }
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button>
          <Sparkles size={13} />
          {t("modelUseToGenerate")}
          <ChevronDown />
        </Button>
      </PopoverTrigger>
      <MenuContent label={t("modelUseToGenerateMenu")} align="end">
        {targets.map((target) => (
          <MenuItem
            key={target.option.id}
            label={target.name}
            truncate
            description={targetNote(target, formed, t) || undefined}
            onClick={() => onPick(target)}
          />
        ))}
      </MenuContent>
    </Popover>
  );
}

/**
 * 详情左栏的预览框:占满这一栏的宽,高度有上限 —— 并排时 640,上下排(整页一起滚)时半屏,不把概要顶到一屏以外。
 * 预览图按自己的比例收进去(object-contain);没有预览图的占位是和卡片一样的 3:4,也受这个上限。
 */
const DETAIL_PREVIEW_FRAME = "max-h-[640px] w-full [[data-library-detail-scroll=both]_&]:max-h-[50dvh]";

/** 详情里的预览视频:框按片子自己的比例(元数据回来之前先按 16:9),静音、循环,第一帧是缩略图。 */
function DetailVideo({ src, poster, label, onFailed }: { src: string; poster: string; label: string; onFailed: () => void }) {
  const [ratio, setRatio] = React.useState(16 / 9);
  return (
    <div data-detail-video="" className={cn(DETAIL_PREVIEW_FRAME, "block")} style={{ aspectRatio: ratio }}>
      <VideoPlayer assetSrc={src} poster={poster} loop muted label={label} onError={onFailed}
                   onNaturalSize={(width, height) => setRatio(width / height)} className="bg-secondary" />
    </div>
  );
}

/**
 * 一个模型文件的详情(LibraryDetail 的骨架):头上是名字、目录 · 大小 · 底模和常用操作;左栏预览(照预览图那两组设置:
 * 模糊的悬停或点「看清」才清楚,不显示的点「显示这一张」才去取);右栏概要(底模和判据、NSFW 和凭什么、触发词点一下复制、
 * 文件、改动时间)、在用的工作流、训练标签、元数据。`section` 是打开时直接跳到的那一节(菜单里的「在用的工作流」)。
 */
export function ModelDetail({
  instanceId,
  model,
  settings,
  section,
  onShowWorkflow,
  onBack,
  backLabel,
}: {
  instanceId: string;
  model: ModelFile;
  settings: ModelPreviewSettings;
  section: "used" | null;
  onShowWorkflow?: (path: string) => void;
  onBack: () => void;
  /** 头上「返回」那颗按钮叫什么:模型库里是「返回模型库」,工作台的详情弹窗里是「关闭详情」。 */
  backLabel?: string;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const meta = useQuery({
    queryKey: ["model-library-detail", instanceId, model.folder, model.name],
    queryFn: () => getModelDetail(instanceId, model.folder, model.name),
  });
  const actions = React.useContext(ModelActionsContext);
  const [revealed, setRevealed] = React.useState(false);
  //: 说有预览图、这张却没取到:和没有预览图一样,画那个 3:4 的框。这不是少见的情况 —— 新版 ComfyUI 给每个文件都报
  //: 预览地址,有没有图要取了才知道(没有就 404),没配预览图的文件走的都是这条。不能留给 ModelThumb 自己的占位:
  //: 它沿用给图片的 max-h,自己没有高度,缩成顶上一条图标、下面整栏空着;外面那层的「看清」按钮也没东西可看。
  //: 记的是「从哪来的那张」没取到:预览图从哪来变了(刚在 Civitai 上找到一张、存回了那台服务器),换一张再试
  const [failedOrigin, setFailedOrigin] = React.useState<string | null>(null);
  const previewFailed = failedOrigin === (model.preview_origin ?? "");
  const setPreviewFailed = (failed: boolean) => setFailedOrigin(failed ? model.preview_origin ?? "" : null);
  const [allTags, setAllTags] = React.useState(false);
  //: 「用它生成」能交给哪几张工作流:生成选项里这个连接上、有一格能选这个文件的
  const generation = useGenerationOptions(GENERATION_KINDS);
  const targets = React.useMemo(() => generationTargets(generation.options, instanceId, model), [generation.options, instanceId, model]);
  const generate = (target: GenerationTarget) =>
    handOffToGeneration({
      providerProfileId: target.option.provider_profile_id,
      kind: target.option.kind,
      model: target.option.model,
      declared: { [target.key]: target.value },
      // 只带作者写明的触发词;从训练标签里数出来的那几个不一定是触发词,不替人塞进提示词(生成表单里那一格下面能一键加)
      promptWords: model.triggers_source === "metadata" ? model.triggers ?? [] : [],
    });
  const tags = meta.data?.tags ?? [];
  const usedRef = React.useRef<HTMLElement>(null);
  const Icon = folderIcon(model.folder);
  const entries = Object.entries(meta.data?.metadata ?? {});
  const triggers = model.triggers ?? [];
  const used = model.used_by ?? [];
  const source = familySource(model);
  const encoderNote = useEncoderNote(model.encoder);
  const familyNote = encoderNote ?? (source ? t(source.hint) : undefined);
  const jumpToUsed = () => {
    const found = usedRef.current;
    if (!found) return;
    found.scrollIntoView({ block: "start", behavior: "smooth" });
    found.querySelector<HTMLElement>("h4")?.focus({ preventScroll: true });
  };
  //: 从菜单的「在用的工作流」打开:挂上之后跳过去(一次)
  React.useEffect(() => {
    if (section === "used") jumpToUsed();
    // 只在打开这一页时跳一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const treatment = revealed ? "clear" : previewTreatment(settings, Boolean(model.nsfw?.flagged));

  const media = model.has_preview && !previewFailed && treatment === "hidden" ? (
    <div
      data-detail-placeholder={model.folder}
      data-hidden-preview=""
      className={cn(
        DETAIL_PREVIEW_FRAME,
        "grid aspect-[3/4] place-items-center content-center gap-3 rounded-xl border border-border bg-[color-mix(in_srgb,var(--primary)_8%,var(--panel))] text-primary",
      )}
    >
      <Icon className="size-10 opacity-70" />
      <span className="px-4 text-center text-ui-xs text-muted-foreground">
        {t(model.nsfw?.flagged ? "modelPreviewHiddenNsfw" : "modelPreviewHiddenLevel")}
      </span>
      <Button variant="secondary" size="sm" onClick={() => setRevealed(true)}>
        <Eye size={13} />
        {t("modelShowHiddenPreview")}
      </Button>
    </div>
  ) : model.has_preview && !previewFailed ? (
    <div className="group/thumb group/preview relative overflow-hidden rounded-xl bg-secondary">
      {actions && (
        //: 「看大图」:全站共用的灯箱,能左右翻当前筛出来的那一批;视频的那一枚抬到播放控件上面,不压着它
        <ViewFullSizeButton name={baseName(model.name)} onOpen={() => actions.showLarge(model)}
                            className={model.preview_kind === "video" && treatment === "clear" ? "bottom-14 right-3" : "bottom-3 right-3"} />
      )}
      {model.preview_kind === "video" && treatment === "clear" ? (
        // 预览是一段视频:能播(静音、循环,全站同一副播放器,不是浏览器自带的控件条);模糊着时上面那一枚是它的第一帧,不自己播
        <DetailVideo
          src={modelPreviewUrl(instanceId, model.folder, model.name, previewPick(settings))}
          poster={modelThumbnailUrl(instanceId, model.folder, model.name, previewPick(settings))}
          label={t("modelPreviewVideo").replace("{name}", baseName(model.name))}
          onFailed={() => setPreviewFailed(true)}
        />
      ) : (
        <ModelThumb
          instanceId={instanceId}
          model={model}
          full
          treatment={treatment}
          onFailed={() => setPreviewFailed(true)}
          className={cn(DETAIL_PREVIEW_FRAME, "object-contain")}
        />
      )}
      <span className="absolute left-3 top-3 flex gap-1">
        <PreviewOriginMark origin={model.preview_origin} />
      </span>
      {actions && model.preview_origin && model.preview_origin !== "server" && (
        <SavePreviewButton model={model} actions={actions} className="absolute right-3 top-3" />
      )}
      {(treatment === "light" || treatment === "heavy") && (
        <Button
          variant="secondary"
          size="sm"
          className="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-[var(--shadow-floating)]"
          onClick={() => setRevealed(true)}
        >
          <Eye size={13} />
          {t("modelRevealPreview")}
        </Button>
      )}
    </div>
  ) : (
    <div
      data-detail-placeholder={model.folder}
      className={cn(
        DETAIL_PREVIEW_FRAME,
        // 描一圈边:浅色主题下这层底色和弹窗表面几乎一样,没有边就只看得见一枚图标浮在栏中间,框不像框
        "grid aspect-[3/4] place-items-center content-center gap-2 rounded-xl border border-border bg-[color-mix(in_srgb,var(--primary)_8%,var(--panel))] text-primary",
      )}
    >
      <Icon className="size-10 opacity-70" />
      <span className="text-ui-xs text-muted-foreground">{t("modelNoPreview")}</span>
    </div>
  );

  return (
    <LibraryDetail
      backLabel={backLabel ?? t("modelLibraryBack")}
      onBack={onBack}
      title={baseName(model.name)}
      meta={
        <>
          <span>{placeOf(model)}</span>
          {model.size != null && <span aria-hidden>·</span>}
          {model.size != null && <span className="tabular-nums">{formatBytes(model.size)}</span>}
          <FamilyBadge model={model} />
        </>
      }
      actions={
        <>
          <UseToGenerate targets={targets} loading={generation.pending} onPick={generate} />
          <CopyButton text={model.name} label={t("modelCopyName")} />
          <Hint label={t("modelUsedByJump")} disabledReason={used.length ? undefined : t("modelUsedByNone")}>
            <Button variant="outline" disabled={used.length === 0} onClick={jumpToUsed}>
              <Workflow size={13} />
              {t("modelUsedCount").replace("{n}", String(used.length))}
            </Button>
          </Hint>
        </>
      }
      media={media}
    >
      <LibrarySection title={t("modelOverview")}>
        <dl className="m-0 grid min-w-0 gap-3">
          <OverviewRow label={t("modelFamily")} note={familyNote}>
            {model.encoder ? (
              <EncoderOverview encoder={model.encoder} />
            ) : model.family ? (
              <span className="flex">
                <CatalogBadge tone={source?.certain ? "primary" : "muted"}>{model.family}</CatalogBadge>
              </span>
            ) : (
              <span className="text-muted-foreground">
                {t(model.family_source === "not_applicable" ? "modelLibraryFamilyNotApplicable" : "modelLibraryFamilyUnknown")}
              </span>
            )}
          </OverviewRow>
          <SourceRow model={model} />
          <NsfwRow model={model} />
          {triggers.length > 0 && (
            <OverviewRow label={t("modelTriggers")} note={model.triggers_source === "tags" ? t("modelTriggersFromTags") : undefined}>
              <span className="flex min-w-0 flex-wrap gap-1.5">
                {triggers.map((word) => (
                  <TriggerChip key={word} word={word} />
                ))}
              </span>
            </OverviewRow>
          )}
          {model.title && model.title !== baseName(model.name) && (
            <OverviewRow label={t("modelTitle")}>
              <span className="break-words">{model.title}</span>
            </OverviewRow>
          )}
          <OverviewRow label={t("modelFileName")}>
            <span className="break-all">{model.name}</span>
          </OverviewRow>
          {model.modified != null && (
            <OverviewRow label={t("modelModified")}>
              <span className="tabular-nums">{new Date(model.modified * 1000).toLocaleString(locale)}</span>
            </OverviewRow>
          )}
        </dl>
      </LibrarySection>
      <LibrarySection ref={usedRef} title={t("modelUsedBy")} count={used.length}>
        {used.length > 0 ? (
          <ul className="m-0 grid list-none gap-1 p-0">
            {used.map((flow) => {
              //: 点了就用这张工作流生成(选中它、那一格填上这个文件);不在生成模型里的(没启用、转不过来)只列名字
              const target = targets.find((one) => one.option.model === flow.id);
              return (
                <li key={flow.id} className="flex min-w-0 items-center gap-1">
                  {target ? (
                    <Hint label={t("modelUseToGenerateWith").replace("{workflow}", flow.label)}>
                      <button
                        type="button"
                        onClick={() => generate(target)}
                        className="-mx-2 flex h-8 min-w-0 max-w-full cursor-pointer items-center gap-2 rounded-md px-2 text-left text-ui-sm text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <Workflow size={13} aria-hidden className="shrink-0 text-muted-foreground" />
                        <Truncate>{flow.label}</Truncate>
                        <Sparkles size={12} aria-hidden className="shrink-0 text-primary" />
                      </button>
                    </Hint>
                  ) : (
                    <span className="flex h-8 min-w-0 items-center gap-2 text-ui-sm text-foreground">
                      <Workflow size={13} aria-hidden className="shrink-0 text-muted-foreground" />
                      <Truncate hint={t("modelUsedByNotRunnable")}>{flow.label}</Truncate>
                    </span>
                  )}
                  {onShowWorkflow && (
                    <IconButton
                      size="sm"
                      className="ml-auto shrink-0 text-muted-foreground"
                      label={t("modelShowInWorkflowLibrary").replace("{workflow}", flow.label)}
                      onClick={() => onShowWorkflow(flow.id)}
                    >
                      <FolderTree size={13} />
                    </IconButton>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("modelUsedByNone")}</p>
        )}
      </LibrarySection>
      {tags.length > 0 && (
        <LibrarySection
          title={t("modelTags")}
          count={tags.length}
          action={
            tags.length > TAGS_SHOWN ? (
              <Button variant="ghost" size="sm" className="text-muted-foreground" aria-expanded={allTags} onClick={() => setAllTags(!allTags)}>
                {allTags ? t("modelMetaCollapse") : t("modelTagsAll").replace("{n}", String(tags.length))}
              </Button>
            ) : undefined
          }
        >
          {/* 训练标签动辄上百个:先摆出现最多的二十几个,不把元数据挤到很下面 */}
          <div className="flex min-w-0 flex-wrap gap-1.5">
            {(allTags ? tags : tags.slice(0, TAGS_SHOWN)).map((one) => (
              <span key={one.tag} className="rounded-full bg-secondary px-2.5 py-1 text-ui-xs text-foreground">
                {one.tag}
                <span className="ml-1 tabular-nums text-muted-foreground">{one.count}</span>
              </span>
            ))}
          </div>
        </LibrarySection>
      )}
      <MetadataSection entries={entries} loading={meta.isLoading} error={meta.isError ? meta.error : null} />
    </LibraryDetail>
  );
}
