import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookImage, Clapperboard, Layers, LayoutGrid, Plus, ShieldAlert, ShieldCheck, Trash2, Workflow as WorkflowIcon, X, Check } from "lucide-react";
import { toast } from "sonner";

import {
  createVariant,
  deleteEntity,
  dismissLostReferences,
  entityKeys,
  getEntity,
  getEntityUsage,
  assetPreviewUrl,
  assetThumbnailUrl,
  listSceneModels,
  listScenes,
  fetchVoicePreview,
  fetchWorkflowFieldOptions,
  updateEntity,
  type Entity,
  type EntityKind,
  type EntityPatch,
  type EntitySummary,
} from "@/api/client";
import { sceneKeys } from "@/api/queryKeys";
import { errorText } from "@/api/errorMessage";
import { useImagePreview } from "@/components/app/image-preview";
import { SpeakButton } from "@/features/entities/SpeakDialog";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { CollectionTabs } from "@/components/layout/StudioPage";
import { Button } from "@/components/ui/button";
import { DraftInput, DraftTextarea } from "@/components/ui/draft-text";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { fieldTriggerClass } from "@/components/ui/field-trigger";
import { OptionPicker } from "@/components/ui/option-picker";
import { Skeleton } from "@/components/ui/skeleton";
import { usePageTrail } from "@/components/layout/pageTrail";
import { VoicePreviewButton } from "@/components/app/VoicePreviewButton";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { openBoard } from "@/lib/deepLink";
import { aiStudioHref, openCreationSession } from "@/lib/aiStudioLink";
import { cn } from "@/lib/utils";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { EntityGrid, EntitySelectionBar, useEntityCollection } from "@/features/entities/EntityCollection";
import { ReferenceWall, referenceGallery } from "@/features/entities/ReferenceWall";
import { entityDisplayName, entityKindIcon, useCatalogLabels } from "@/features/entities/entityMeta";
import { CLONE_ENGINE } from "@/api/domains/speech";

const FIELD = "w-full rounded-md border border-border bg-field px-3 py-2 text-ui-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring";
const NONE = "__none__";
//: 变体卡片和参考图墙同一档:同样的最小列宽、同样的间距(见 ReferenceWall 的 Wall)。
const VARIANT_GRID = "grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-4";
//: 顶部那一块里「看起来是正文、点进去能改」的输入框:平时没有框,悬停和聚焦才出现。
const INLINE_FIELD =
  "w-full rounded-md border border-transparent bg-transparent px-2 py-1 text-foreground outline-none transition-colors placeholder:text-muted-foreground hover:border-border focus-visible:border-primary";

type DetailTab = "references" | "variants" | "settings" | "usage";
const DETAIL_TABS: readonly DetailTab[] = ["references", "variants", "settings", "usage"];

/**
 * 一个资产的详情,照「角色卡」排:
 *
 * - **顶上是它是谁**:一张大封面,旁边是名字、种类、描述、标签,和一行速览(几张参考图、几个变体、音色、
 *   人偶颜色、真人还是虚构)—— 不点进任何地方就认得出这是哪一个;
 * - **下面按页签分开**:参考图 / 变体 / 设定 / 用在哪里。一次只看一块,不再是好几段空着的区块叠在一起、
 *   旁边再挂一长条表单。
 *
 * 字段离开时保存(一段编辑一次请求),和笔记、画板便签同一种草稿框(DraftTextarea):正在打字的人才是这段字的主人。
 */
export function EntityDetail({
  workspaceId,
  entityId,
  onBack,
  onOpen,
}: {
  workspaceId: string;
  entityId: string;
  onBack: () => void;
  onOpen: (id: string) => void;
}) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const qc = useQueryClient();
  const labels = useCatalogLabels();
  const entity = useQuery({ queryKey: entityKeys.detail(workspaceId, entityId), queryFn: () => getEntity(entityId) });
  const [deleting, setDeleting] = React.useState(false);
  const [variantOpen, setVariantOpen] = React.useState(false);
  const [tab, setTab] = usePersistentTab<DetailTab>("entity-detail", "references", DETAIL_TABS);
  //: 在哪一层写在顶栏的路径里(「资产 / 小美 / 中年」,见 pageTrail),正文里不再摆「← 返回」。
  const shown = entity.data;
  usePageTrail(
    shown
      ? {
          onRoot: onBack,
          segments: shown.parent_id
            ? [{ label: shown.parent_name, onSelect: () => onOpen(shown.parent_id!) }, { label: shown.name }]
            : [{ label: shown.name }],
        }
      : { onRoot: onBack, segments: [] },
  );

  const settle = (next: Entity) => {
    qc.setQueryData(entityKeys.detail(workspaceId, next.id), next);
    void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });
  };
  const patch = useMutation({
    mutationFn: (body: EntityPatch) => updateEntity(entityId, body),
    onSuccess: settle,
    onError: (error) => toast.error(errorText(error)),
  });
  const dismiss = useMutation({
    mutationFn: () => dismissLostReferences(entityId),
    onSuccess: settle,
    onError: (error) => toast.error(errorText(error)),
  });
  const remove = useMutation({
    mutationFn: () => deleteEntity(entityId, (entity.data?.variants.length ?? 0) > 0),
    onSuccess: () => {
      setDeleting(false);
      void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });
      if (entity.data?.parent_id) onOpen(entity.data.parent_id);
      else onBack();
    },
    onError: (error) => toast.error(errorText(error)),
  });
  const variant = useMutation({
    mutationFn: (name: string) => createVariant(entityId, { name }),
    onSuccess: (made) => {
      setVariantOpen(false);
      void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });
      onOpen(made.id);
    },
    onError: (error) => toast.error(errorText(error)),
  });

  if (entity.isPending) {
    return (
      <div role="status" aria-busy="true" className="grid gap-4">
        <span className="sr-only">{t("pageLoading")}</span>
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-64 w-full rounded-lg" />
      </div>
    );
  }
  if (entity.isError) {
    return (
      <EmptyState
        icon={<Layers />}
        title={t("pageLoadError")}
        body={entity.error.message}
        action={<Button variant="secondary" onClick={onBack}>{t("back")}</Button>}
      />
    );
  }
  const data = entity.data;
  const KindIcon = entityKindIcon(data.kind);
  const variantCount = data.variants.length;

  const tabs = DETAIL_TABS.filter((one) => one !== "variants" || !data.parent_id);
  const current: DetailTab = tabs.includes(tab) ? tab : "references";
  const tabLabel: Record<DetailTab, string> = {
    references: t("entityReferences"),
    variants: t("entityVariants"),
    settings: t("entitySettings"),
    usage: t("entityUsage"),
  };
  const tabCount: Partial<Record<DetailTab, number>> = { references: data.references.length, variants: variantCount };
  const cover = data.display_cover_asset_id;
  //: 封面点开,左右翻的是**这个资产的整面参考图墙**(和墙上点开是同一组、同一个先后),从封面那张开始。
  //: 封面若不在墙上(变体沿用母本的封面),就只看这一张 —— 塞进别人的画廊,会从第一张而不是封面开始。
  const openCover = (id: string) => {
    const wall = referenceGallery(data.references);
    const at = data.references.findIndex((ref) => ref.asset_id === id);
    openImagePreview(at >= 0 ? { ...wall[at], gallery: wall } : { src: assetPreviewUrl(id), title: data.name });
  };

  return (
    <div className="grid min-w-0 gap-7" data-entity-detail={data.id}>
      <header className="grid min-w-0 gap-6 sm:grid-cols-[180px_minmax(0,1fr)] sm:items-start" data-entity-hero="">
        {/* 有封面就放大看它;还没有图就带去参考图那一页传一张。 */}
        <IconButton
          unstyled
          type="button"
          onClick={() => (cover ? openCover(cover) : setTab("references"))}
          label={t(cover ? "imagePreviewTitle" : "entityReferences")}
          className={cn("relative grid aspect-[4/5] w-full max-w-[180px] place-items-center overflow-hidden rounded-xl border border-border bg-panel-inset p-0 text-muted-foreground transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", cover ? "cursor-zoom-in" : "cursor-pointer")}
        >
          {data.display_cover_asset_id ? (
            <img src={assetThumbnailUrl(data.display_cover_asset_id)} alt="" className="absolute inset-0 size-full object-cover" />
          ) : (
            <KindIcon size={36} strokeWidth={1.2} />
          )}
        </IconButton>
        <div className="grid min-w-0 content-start gap-2">
          <div className="flex min-w-0 items-start justify-between gap-3">
            <span className="flex min-w-0 flex-wrap items-center gap-2 px-2 text-ui-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5 rounded-md bg-secondary px-2 py-0.5">
                <KindIcon size={12} />
                {labels.kind(data.kind)}
              </span>
              {data.parent_id && <span>{t("entityVariantOf").replace("{name}", data.parent_name)}</span>}
            </span>
            <span className="flex shrink-0 items-center gap-2">
              {/* 人物能说话(数字人,ADR 0028):它自己的嗓子 + 正面图。门槛(授权、音色、模型)由服务端查,原因写在弹窗里。 */}
              {data.kind === "character" && <SpeakButton entity={data} workspaceId={workspaceId} />}
              <Button variant="outline" size="sm" className="shrink-0 hover:border-destructive/50 hover:text-destructive" onClick={() => setDeleting(true)}>
                <Trash2 />
                {t("delete")}
              </Button>
            </span>
          </div>
          <DraftInput
            aria-label={t("entityName")}
            className={cn(INLINE_FIELD, "text-ui-title font-semibold leading-tight tracking-tight")}
            value={data.name}
            commit="blur"
            onValueChange={(name) => name.trim() && patch.mutate({ name })}
          />
          <DraftTextarea
            aria-label={t("entityDescription")}
            placeholder={t("entityDescriptionHint")}
            rows={1}
            //: 按内容撑高(field-sizing):空着时只占一行,不在描述和标签之间留一截空白。
            className={cn(INLINE_FIELD, "resize-none text-ui-md leading-relaxed text-muted-foreground [field-sizing:content] focus-visible:text-foreground")}
            value={data.description}
            commit="blur"
            onValueChange={(description) => patch.mutate({ description })}
          />
          <DraftInput
            aria-label={t("entityTags")}
            placeholder={t("entityTagsPlaceholder")}
            className={cn(INLINE_FIELD, "text-ui-sm")}
            value={data.tags.join(", ")}
            commit="blur"
            onValueChange={(text) => patch.mutate({ tags: text.split(/[,，]/).map((one) => one.trim()).filter(Boolean) })}
          />
          <Facts entity={data} workspaceId={workspaceId} />
        </div>
      </header>

      {data.lost_references.length > 0 && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-ui-sm">
          <ShieldAlert size={16} className="text-warning" />
          <span className="min-w-0 flex-1">
            {t("entityLostReferences")
              .replace("{n}", String(data.lost_references.length))
              .replace("{names}", data.lost_references.map((one) => `${one.name} · ${labels.role(one.role)}`).join(", "))}
          </span>
          <Button variant="ghost" size="sm" loading={dismiss.isPending} onClick={() => dismiss.mutate()}>
            {t("entityDismiss")}
          </Button>
        </div>
      )}

      <div className="grid min-w-0 gap-6">
        <div className="border-b border-divider">
          <CollectionTabs
            value={current}
            onChange={setTab}
            label={t("entitySections")}
            items={tabs.map((one) => ({ value: one, label: tabLabel[one], count: tabCount[one] }))}
          />
        </div>

        {current === "references" && <ReferenceWall entity={data} workspaceId={workspaceId} />}

        {current === "variants" && <VariantsTab workspaceId={workspaceId} kind={data.kind} variants={data.variants} onOpen={onOpen} onNew={() => setVariantOpen(true)} />}

        {current === "settings" && (
          <div className="grid min-w-0 gap-8" aria-label={t("entityFields")} data-entity-settings="">
            <Field label={t("entityPrompt")} hint={t(data.parent_id ? `entityVariantPromptHint_${data.kind}` : `entityPromptHint_${data.kind}`)}>
              <DraftTextarea
                aria-label={t("entityPrompt")}
                className={cn(FIELD, "min-h-32 resize-y font-mono text-ui-sm leading-relaxed")}
                value={data.prompt}
                commit="blur"
                onValueChange={(prompt) => patch.mutate({ prompt })}
              />
            </Field>
            <KindFields entity={data} workspaceId={workspaceId} onPatch={(body) => patch.mutate(body)} />
          </div>
        )}

        {current === "usage" && <UsageSection workspaceId={workspaceId} entityId={data.id} />}
      </div>

      <ConfirmDialog
        open={deleting}
        title={t("entityDeleteTitle").replace("{name}", entityDisplayName(data))}
        body={
          variantCount > 0
            ? t("entityDeleteWithVariants").replace("{n}", String(variantCount))
            : t("entityDeleteBody")
        }
        confirmLabel={t("delete")}
        pending={remove.isPending}
        onCancel={() => setDeleting(false)}
        onConfirm={() => remove.mutate()}
      />
      <RenameDialog
        open={variantOpen}
        title={t("entityVariantNew")}
        initialValue=""
        confirmLabel={t("entityCreate")}
        pending={variant.isPending}
        onCancel={() => setVariantOpen(false)}
        onSubmit={(name) => variant.mutate(name)}
      />
    </div>
  );
}

/**
 * 「变体」页签:和资产库列表同一套卡片 —— 右键(打开、重命名、编辑标签、删除)、「选择」之后批量打标签和删除
 * (见 EntityCollection)。变体下面不再挂变体,所以右键里没有「新建变体」。
 */
function VariantsTab({
  workspaceId,
  kind,
  variants,
  onOpen,
  onNew,
}: {
  workspaceId: string;
  /** 说明按种类说:人物换的是服装、年龄,场景是时间、天气,道具是新旧、颜色。 */
  kind: EntityKind;
  variants: EntitySummary[];
  onOpen: (id: string) => void;
  onNew: () => void;
}) {
  const t = useI18n();
  const collection = useEntityCollection(workspaceId, variants, { onOpen });
  const { selectMode, enter: enterSelectMode, exit } = collection.selection;
  return (
    <section className="grid gap-4" aria-label={t("entityVariants")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="m-0 max-w-2xl text-ui-sm text-muted-foreground">{t(`entityVariantsHint_${kind}`)}</p>
        <span className="flex flex-wrap gap-2">
          {variants.length > 0 && (
            <Button variant="outline" aria-pressed={selectMode} onClick={() => (selectMode ? exit() : enterSelectMode())}>
              {selectMode ? <X /> : <Check />}
              {selectMode ? t("cancel") : t("mediaSelectMode")}
            </Button>
          )}
          <Button variant="outline" onClick={onNew}>
            <Plus />
            {t("entityVariantNew")}
          </Button>
        </span>
      </div>
      <EntitySelectionBar collection={collection} rows={variants} />
      {variants.length === 0 ? (
        <EmptyState icon={<Layers size={22} />} title={t("entityVariantsEmpty")} />
      ) : (
        <EntityGrid collection={collection} rows={variants} className={VARIANT_GRID} tile />
      )}
      {collection.dialogs}
    </section>
  );
}

/** 「设定」页签里的一组:标题一行,字段在宽的时候两列排(`wide` 的一组单列,比如授权声明那几张说明卡)。 */
function PanelGroup({ title, wide = false, children }: { title: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <section className="grid min-w-0 gap-4 border-t border-divider pt-6" aria-label={title} data-panel-group="">
      <h3 className="m-0 text-ui-md font-semibold">{title}</h3>
      {/* 两列排;落单的最后一格占满那一行 —— 同一行不留半截空。 */}
      <div className={cn("grid min-w-0 gap-5", !wide && "md:grid-cols-2 md:[&>:last-child:nth-child(odd)]:col-span-2")}>
        {children}
      </div>
    </section>
  );
}

/**
 * 顶上那一行速览:几张参考图、几个变体,以及种类自己的几样(人物的音色、人偶颜色、真人还是虚构)。
 * 只读 —— 改在「设定」页签里;这一行是让人不点进去就认得出这是哪一个。
 */
function Facts({ entity, workspaceId }: { entity: Entity; workspaceId: string }) {
  const t = useI18n();
  const attributes = entity.attributes as Record<string, unknown>;
  const voiceId = String(attributes.voice_id ?? "");
  const { voices } = useVoiceOptions(workspaceId, voiceId ? String(attributes.voice_engine ?? VOICE_LIBRARY_ENGINE) : "");
  const voice = voiceId ? (voices.data?.find((one) => one.value === voiceId)?.label ?? voiceId) : "";
  const items: React.ReactNode[] = [
    t("entityRefCount").replace("{n}", String(entity.references.length)),
    ...(entity.parent_id ? [] : [t("entityVariantCount").replace("{n}", String(entity.variants.length))]),
  ];
  if (entity.kind === "character") {
    if (voice) items.push(`${t("entityVoice")} · ${voice}`);
    if (attributes.blockout_color) {
      items.push(
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-full border border-border" style={{ background: String(attributes.blockout_color) }} />
          {t("entityBlockoutColor")}
        </span>,
      );
    }
    items.push(
      <span className={cn("inline-flex items-center gap-1", !entity.usable_for_digital_human && "text-warning")}>
        {entity.usable_for_digital_human ? <ShieldCheck size={12} /> : <ShieldAlert size={12} />}
        {t(attributes.real_person ? "entityRealPerson" : "entityFictional")}
      </span>,
    );
  }
  if (entity.kind === "location" && attributes.time_of_day) items.push(String(attributes.time_of_day));
  return (
    <ul className="m-0 flex list-none flex-wrap items-center gap-x-4 gap-y-1 px-2 pt-1 text-ui-xs text-muted-foreground" data-entity-facts="">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <span className="text-ui-sm font-medium">{label}</span>
      {children}
      {hint && <span className="text-ui-xs leading-relaxed text-muted-foreground">{hint}</span>}
    </div>
  );
}

/** 种类的专有字段:人物的音色、人偶颜色、真人 / 虚构与授权声明;场景的 3D 场景、时间;道具的 3D 模型。 */
function KindFields({
  entity,
  workspaceId,
  onPatch,
}: {
  entity: Entity;
  workspaceId: string;
  onPatch: (body: EntityPatch) => void;
}) {
  const t = useI18n();
  const attributes = entity.attributes as Record<string, unknown>;
  const save = (changes: Record<string, unknown>) => {
    const next: Record<string, unknown> = { ...attributes, ...changes };
    for (const [key, value] of Object.entries(next)) if (value === "" || value === null || value === undefined) delete next[key];
    onPatch({ attributes: next });
  };

  if (entity.kind === "character") {
    return (
      <>
        <PanelGroup title={t("entityGroupCharacter")}>
          <VoiceField
            workspaceId={workspaceId}
            name={entity.name}
            engine={String(attributes.voice_engine ?? "")}
            voice={String(attributes.voice_id ?? "")}
            onChange={(next) => save(next)}
          />
          <Field label={t("entityBlockoutColor")} hint={t("entityBlockoutColorHint")}>
            <ColorField
              label={t("entityBlockoutColor")}
              value={String(attributes.blockout_color ?? "")}
              onChange={(blockout_color) => save({ blockout_color })}
            />
          </Field>
        </PanelGroup>
        <PanelGroup title={t("entityPersonTitle")} wide>
          <ConsentField entity={entity} onSave={save} />
        </PanelGroup>
      </>
    );
  }
  if (entity.kind === "location") {
    return (
      <PanelGroup title={t("entityGroupLocation")}>
        <SceneField workspaceId={workspaceId} value={String(attributes.scene_id ?? "")} onChange={(scene_id) => save({ scene_id })} />
        <Field label={t("entityTimeOfDay")} hint={t("entityTimeOfDayHint")}>
          <DraftInput
            aria-label={t("entityTimeOfDay")}
            className={FIELD}
            value={String(attributes.time_of_day ?? "")}
            commit="blur"
            onValueChange={(time_of_day) => save({ time_of_day })}
          />
        </Field>
      </PanelGroup>
    );
  }
  return (
    <PanelGroup title={t("entityGroupProp")}>
      <ModelField workspaceId={workspaceId} value={String(attributes.model_asset_id ?? "")} onChange={(model_asset_id) => save({ model_asset_id })} />
    </PanelGroup>
  );
}

/**
 * 颜色:和同一行的下拉框一样高、一样宽的一整条(色块 + 色值 + 清除),不是孤零零一小块 ——
 * 并排的两格字段宽度对不上,读起来就是「这排没排齐」。点整条都能打开取色器。
 */
function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (next: string) => void }) {
  const t = useI18n();
  return (
    <label className={cn(fieldTriggerClass(), "cursor-pointer gap-2.5")} data-color-field="">
      <input
        type="color"
        aria-label={label}
        className="size-5 shrink-0 cursor-pointer rounded border-0 bg-transparent p-0 [&::-webkit-color-swatch-wrapper]:p-0 [&::-webkit-color-swatch]:rounded [&::-webkit-color-swatch]:border [&::-webkit-color-swatch]:border-border"
        value={value || "#9aa0a6"}
        onChange={(event) => onChange(event.target.value)}
      />
      <span className={cn("font-mono text-ui-sm", !value && "font-sans text-muted-foreground")}>{value || t("entityNone")}</span>
      {value && (
        <IconButton
          unstyled
          type="button"
          label={t("entityClear")}
          onClick={(event) => {
            event.preventDefault();
            onChange("");
          }}
          className="ml-auto grid size-6 cursor-pointer place-items-center rounded border-0 bg-transparent p-0 text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          <X size={14} />
        </IconButton>
      )}
    </label>
  );
}

/** 本地克隆(音色库)这个引擎的名字,和后端 entities.catalog.VOICE_LIBRARY_ENGINE 同一个值。 */
const VOICE_LIBRARY_ENGINE = CLONE_ENGINE;

/** 引擎清单、某个引擎的音色清单:和工作流「念稿」节点问的是同一个接口,列出来的一样。 */
function useVoiceOptions(workspaceId: string, engine: string) {
  const engines = useQuery({
    queryKey: ["entity-voice-engines", workspaceId],
    queryFn: () => fetchWorkflowFieldOptions("speech_engines", workspaceId),
    staleTime: 60_000,
  });
  const voices = useQuery({
    queryKey: ["entity-voices", workspaceId, engine],
    queryFn: () => fetchWorkflowFieldOptions("speech_voices", workspaceId, engine),
    enabled: Boolean(engine),
    staleTime: 60_000,
  });
  return { engines, voices };
}

/**
 * 音色 = 引擎 + 那个引擎里的一把嗓子:本地克隆(音色库)、Edge、各家云端,哪个就绪哪个列出来。
 * 一行两个下拉,换了引擎就清掉嗓子(另一个引擎里没有这个 id)。
 */
function VoiceField({
  workspaceId,
  name,
  engine,
  voice,
  onChange,
}: {
  workspaceId: string;
  /** 试听念「你好,我是{name}」。 */
  name: string;
  engine: string;
  voice: string;
  onChange: (next: { voice_engine: string; voice_id: string }) => void;
}) {
  const t = useI18n();
  const [picked, setPicked] = React.useState(engine || VOICE_LIBRARY_ENGINE);
  //: 只跟着「存着的那个」走:换引擎会先清掉嗓子(存回来的引擎是空的),那一刻不能把刚挑的引擎又拨回默认。
  React.useEffect(() => {
    if (engine) setPicked(engine);
  }, [engine]);
  const { engines, voices } = useVoiceOptions(workspaceId, picked);
  //: 存着的音色只属于存着的那个引擎:切到别的引擎时下拉回到「无」,试听也没有可念的。
  const pickedVoice = voice && picked === (engine || VOICE_LIBRARY_ENGINE) ? voice : "";
  const engineOptions = engines.data ?? [];
  //: 存着的引擎现在没就绪(缺了 Key)也照样显示它,不把人已经选好的东西悄悄换掉。
  const withCurrent = engineOptions.some((one) => one.value === picked)
    ? engineOptions
    : [...engineOptions, { value: picked, label: picked }];
  return (
    <Field label={t("entityVoice")} hint={t("entityVoiceHint")}>
      <div className="grid min-w-0 grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] gap-2">
        <OptionPicker
          ariaLabel={t("entityVoiceEngine")}
          value={picked}
          onChange={(next) => {
            setPicked(next);
            if (voice) onChange({ voice_engine: "", voice_id: "" });
          }}
          options={withCurrent}
        />
        <OptionPicker
          ariaLabel={t("entityVoice")}
          value={pickedVoice || NONE}
          onChange={(next) => onChange(next === NONE ? { voice_engine: "", voice_id: "" } : { voice_engine: picked, voice_id: next })}
          options={[{ value: NONE, label: t("entityNone") }, ...(voices.data ?? [])]}
        />
        <VoicePreviewButton
          load={() => fetchVoicePreview({ workspace_id: workspaceId, engine: picked, voice: pickedVoice, text: t("entityVoicePreviewText").replace("{name}", name) })}
          disabled={!pickedVoice}
          disabledReason={t("entityVoicePreviewPick")}
        />
      </div>
    </Field>
  );
}

function SceneField({ workspaceId, value, onChange }: { workspaceId: string; value: string; onChange: (next: string) => void }) {
  const t = useI18n();
  const scenes = useQuery({ queryKey: sceneKeys.list(workspaceId), queryFn: () => listScenes(workspaceId) });
  return (
    <Field label={t("entityScene")} hint={t("entitySceneHint")}>
      <OptionPicker
        ariaLabel={t("entityScene")}
        value={value || NONE}
        onChange={(next) => onChange(next === NONE ? "" : next)}
        options={[{ value: NONE, label: t("entityNone") }, ...(scenes.data ?? []).map((scene) => ({ value: scene.id, label: scene.name }))]}
      />
    </Field>
  );
}

function ModelField({ workspaceId, value, onChange }: { workspaceId: string; value: string; onChange: (next: string) => void }) {
  const t = useI18n();
  const models = useQuery({ queryKey: ["scene-models", workspaceId], queryFn: () => listSceneModels(workspaceId) });
  return (
    <Field label={t("entityModel")} hint={t("entityModelHint")}>
      <OptionPicker
        ariaLabel={t("entityModel")}
        value={value || NONE}
        onChange={(next) => onChange(next === NONE ? "" : next)}
        options={[{ value: NONE, label: t("entityNone") }, ...(models.data ?? []).map((model) => ({ value: model.id, label: model.name }))]}
      />
    </Field>
  );
}

/**
 * 真人还是虚构,以及授权声明(数字人方案「合规」一节)。**每一项说清是什么意思** —— 说明来自后端的词表。
 * 真人要选「这是我本人」或「已取得本人同意」,之后才能用于数字人;谁、什么时候声明的由服务端记。
 */
function ConsentField({ entity, onSave }: { entity: Entity; onSave: (changes: Record<string, unknown>) => void }) {
  const t = useI18n();
  const labels = useCatalogLabels();
  const attributes = entity.attributes as Record<string, unknown>;
  const real = Boolean(attributes.real_person);
  const consent = (attributes.consent ?? null) as { kind?: string; declared_at?: string } | null;
  const options = labels.consent.filter((one) => (real ? one.kind !== "fictional" : one.kind === "fictional"));
  return (
    <fieldset className="m-0 grid gap-2 border-0 p-0" data-consent="">
      {/* 组标题已经写着「真人还是虚构」,图例只留给读屏。 */}
      <legend className="sr-only">{t("entityPersonTitle")}</legend>
      <div role="radiogroup" aria-label={t("entityPersonTitle")} className="flex gap-1">
        {[
          { value: false, label: t("entityFictional") },
          { value: true, label: t("entityRealPerson") },
        ].map((one) => (
          <button
            key={String(one.value)}
            type="button"
            role="radio"
            aria-checked={real === one.value}
            onClick={() => real !== one.value && onSave({ real_person: one.value, consent: null })}
            className={cn(
              "cursor-pointer rounded-full border-0 px-3 py-1 text-ui-xs transition-colors",
              real === one.value ? "bg-action text-action-foreground" : "bg-secondary text-muted-foreground hover:text-foreground",
            )}
          >
            {one.label}
          </button>
        ))}
      </div>
      <div role="radiogroup" aria-label={t("entityConsentTitle")} className="grid gap-1.5">
        {options.map((one) => (
          <label
            key={one.kind}
            className={cn(
              "grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] gap-x-2 rounded-md border px-3 py-2",
              consent?.kind === one.kind ? "border-primary bg-accent" : "border-border",
            )}
          >
            <input
              type="radio"
              name={`consent-${entity.id}`}
              className="mt-0.5"
              checked={consent?.kind === one.kind}
              onChange={() => onSave({ consent: { kind: one.kind } })}
            />
            <span className="text-ui-sm font-medium">{one.label}</span>
            <span className="col-start-2 text-ui-xs leading-relaxed text-muted-foreground">{toPlainText(one.help)}</span>
          </label>
        ))}
      </div>
      <p className={cn("m-0 flex items-center gap-1.5 text-ui-xs", entity.usable_for_digital_human ? "text-muted-foreground" : "text-warning")}>
        {entity.usable_for_digital_human ? <ShieldCheck size={13} /> : <ShieldAlert size={13} />}
        {t(entity.usable_for_digital_human ? "entityDigitalHumanOk" : "entityDigitalHumanBlocked")}
        {consent?.declared_at ? ` · ${t("entityConsentDeclaredAt").replace("{at}", consent.declared_at.slice(0, 10))}` : ""}
      </p>
    </fieldset>
  );
}

/**
 * 在哪里用过,按类分组:画板(资产格 / 提示词里 @ 了它)、生成记录(带结果的缩略图)、工作流。一格一条,点一下过去。
 * 页签上已经写着「在哪里用过」,这里不再重复标题;一条都没有时是空状态。
 */
function UsageSection({ workspaceId, entityId }: { workspaceId: string; entityId: string }) {
  const t = useI18n();
  const usage = useQuery({ queryKey: entityKeys.usage(workspaceId, entityId), queryFn: () => getEntityUsage(entityId) });
  const rows = usage.data;
  const go = (hash: string) => {
    window.location.hash = hash;
  };
  if (usage.isPending) {
    return (
      <div className={USAGE_GRID} aria-busy="true">
        {[0, 1, 2].map((one) => (
          <Skeleton key={one} className="h-16 w-full rounded-lg" />
        ))}
      </div>
    );
  }
  if (!rows || rows.boards.length + rows.generations.length + rows.workflows.length === 0) {
    return (
      <section aria-label={t("entityUsage")} data-entity-usage="">
        <EmptyState icon={<LayoutGrid size={22} />} title={t("entityUsageEmpty")} />
      </section>
    );
  }
  return (
    <section className="grid gap-7" aria-label={t("entityUsage")} data-entity-usage="">
      <UsageGroup title={t("entityUsageBoards")} count={rows.boards.length}>
        {rows.boards.map((board) => (
          <UsageCard
            key={`b-${board.id}`}
            lead={<LayoutGrid size={18} />}
            title={board.name}
            meta={t(board.how === "cell" ? "entityUsageCell" : "entityUsageMention")}
            onOpen={() => openBoard(board.id)}
          />
        ))}
      </UsageGroup>
      <UsageGroup title={t("entityUsageGenerations")} count={rows.generations.length}>
        {rows.generations.map((one) => (
          <UsageCard
            key={`g-${one.id}`}
            lead={
              one.result_asset_id ? (
                <img src={assetThumbnailUrl(one.result_asset_id)} alt="" loading="lazy" className="size-full object-cover" />
              ) : one.kind === "video" ? (
                <Clapperboard size={18} />
              ) : (
                <BookImage size={18} />
              )
            }
            title={one.prompt || one.model}
            meta={`${one.model} · ${one.created_at.slice(0, 10)}`}
            //: 打开那条创作会话(ADR 0055 §9);老记录没挂在会话上的去创作分区
            onOpen={() => (one.session_id ? openCreationSession(one.session_id) : go(aiStudioHref("create")))}
            thumb={one.result_asset_id}
            session={one.session_id}
          />
        ))}
      </UsageGroup>
      <UsageGroup title={t("entityUsageWorkflows")} count={rows.workflows.length}>
        {rows.workflows.map((flow) => (
          <UsageCard
            key={`w-${flow.id}`}
            lead={<WorkflowIcon size={18} />}
            title={flow.name}
            meta={t("entityUsageWorkflow")}
            onOpen={() => go("#/workflows")}
          />
        ))}
      </UsageGroup>
    </section>
  );
}

const USAGE_GRID = "grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3";

function UsageGroup({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  if (count === 0) return null;
  return (
    <div className="grid gap-3">
      <h3 className="m-0 flex items-center gap-2 text-ui-sm font-semibold">
        {title}
        <span className="text-ui-xs font-normal tabular-nums text-muted-foreground">{count}</span>
      </h3>
      <ul className={cn("m-0 list-none p-0", USAGE_GRID)}>{children}</ul>
    </div>
  );
}

function UsageCard({
  lead,
  title,
  meta,
  onOpen,
  thumb,
  session,
}: {
  lead: React.ReactNode;
  title: string;
  meta: string;
  onOpen: () => void;
  thumb?: string | null;
  session?: string | null;
}) {
  return (
    <li className="grid">
      <button
        type="button"
        data-usage-session={session ?? undefined}
        data-usage-result={thumb ?? undefined}
        onClick={onOpen}
        className="flex min-w-0 cursor-pointer items-center gap-3 rounded-lg border border-border bg-panel p-2.5 text-left transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="grid size-11 shrink-0 place-items-center overflow-hidden rounded-md bg-panel-inset text-muted-foreground">{lead}</span>
        <span className="grid min-w-0 flex-1 gap-0.5">
          <Truncate className="text-ui-sm font-medium text-foreground">
            {title}
          </Truncate>
          <Truncate className="text-ui-xs text-muted-foreground">{meta}</Truncate>
        </span>
      </button>
    </li>
  );
}
