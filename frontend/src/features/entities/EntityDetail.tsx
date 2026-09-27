import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BookImage, Clapperboard, Layers, LayoutGrid, Plus, ShieldAlert, ShieldCheck, Trash2, Workflow as WorkflowIcon, X } from "lucide-react";
import { toast } from "sonner";

import {
  createVariant,
  deleteEntity,
  dismissLostReferences,
  entityKeys,
  getEntity,
  getEntityUsage,
  assetThumbnailUrl,
  listSceneModels,
  listScenes,
  listVoices,
  updateEntity,
  type Entity,
  type EntityPatch,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { CollectionTabs } from "@/components/layout/StudioPage";
import { Button } from "@/components/ui/button";
import { DraftInput, DraftTextarea } from "@/components/ui/draft-text";
import { fieldTriggerClass } from "@/components/ui/field-trigger";
import { OptionPicker } from "@/components/ui/option-picker";
import { Skeleton } from "@/components/ui/skeleton";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { EntityCard } from "@/features/entities/EntityCard";
import { ReferenceWall } from "@/features/entities/ReferenceWall";
import { entityDisplayName, entityKindIcon, useCatalogLabels } from "@/features/entities/entityMeta";

const FIELD = "w-full rounded-md border border-border bg-field px-3 py-2 text-ui-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring";
const NONE = "__none__";
//: 变体卡片和参考图同一档大小。
const VARIANT_GRID = "grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-5";
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
  const qc = useQueryClient();
  const labels = useCatalogLabels();
  const entity = useQuery({ queryKey: entityKeys.detail(workspaceId, entityId), queryFn: () => getEntity(entityId) });
  const [deleting, setDeleting] = React.useState(false);
  const [variantOpen, setVariantOpen] = React.useState(false);
  const [tab, setTab] = usePersistentTab<DetailTab>("entity-detail", "references", DETAIL_TABS);

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

  return (
    <div className="grid min-w-0 gap-7" data-entity-detail={data.id}>
      <div className="flex min-w-0 items-center justify-between gap-3">
        <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" onClick={data.parent_id ? () => onOpen(data.parent_id!) : onBack}>
          <ArrowLeft />
          {data.parent_id ? data.parent_name : t("navEntities")}
        </Button>
        <Button variant="outline" size="sm" className="hover:border-destructive/50 hover:text-destructive" onClick={() => setDeleting(true)}>
          <Trash2 />
          {t("delete")}
        </Button>
      </div>

      <header className="grid min-w-0 gap-6 sm:grid-cols-[180px_minmax(0,1fr)] sm:items-start" data-entity-hero="">
        <button
          type="button"
          onClick={() => setTab("references")}
          title={t("entityReferences")}
          aria-label={t("entityReferences")}
          className="relative grid aspect-[4/5] w-full max-w-[180px] cursor-pointer place-items-center overflow-hidden rounded-xl border border-border bg-panel-inset p-0 text-muted-foreground transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {data.display_cover_asset_id ? (
            <img src={assetThumbnailUrl(data.display_cover_asset_id)} alt="" className="absolute inset-0 size-full object-cover" />
          ) : (
            <KindIcon size={36} strokeWidth={1.2} />
          )}
        </button>
        <div className="grid min-w-0 content-start gap-2">
          <span className="flex min-w-0 flex-wrap items-center gap-2 px-2 text-ui-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5 rounded-md bg-secondary px-2 py-0.5">
              <KindIcon size={12} />
              {labels.kind(data.kind)}
            </span>
            {data.parent_id && <span>{t("entityVariantOf").replace("{name}", data.parent_name)}</span>}
          </span>
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

        {current === "variants" && (
          <section className="grid gap-4" aria-label={t("entityVariants")}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="m-0 max-w-2xl text-ui-sm text-muted-foreground">{t("entityVariantsHint")}</p>
              <Button variant="outline" onClick={() => setVariantOpen(true)}>
                <Plus />
                {t("entityVariantNew")}
              </Button>
            </div>
            {variantCount === 0 ? (
              <EmptyState icon={<Layers size={22} />} title={t("entityVariantsEmpty")} />
            ) : (
              <div className={VARIANT_GRID}>
                {data.variants.map((one) => (
                  <EntityCard key={one.id} entity={one} onOpen={() => onOpen(one.id)} />
                ))}
              </div>
            )}
          </section>
        )}

        {current === "settings" && (
          <div className="grid min-w-0 gap-8" aria-label={t("entityFields")} data-entity-settings="">
            <Field label={t("entityPrompt")} hint={data.parent_id ? t("entityVariantPromptHint") : t("entityPromptHint")}>
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

/** 「设定」页签里的一组:标题一行,字段在宽的时候两列排(`wide` 的一组单列,比如授权声明那几张说明卡)。 */
function PanelGroup({ title, wide = false, children }: { title: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <section className="grid min-w-0 gap-4 border-t border-divider pt-6" aria-label={title} data-panel-group="">
      <h3 className="m-0 text-ui-md font-semibold">{title}</h3>
      <div className={cn("grid min-w-0 gap-5", !wide && "md:grid-cols-2")}>{children}</div>
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
  const voices = useQuery({ queryKey: ["voices", workspaceId], queryFn: () => listVoices(workspaceId), enabled: Boolean(voiceId) });
  const voice = voices.data?.find((one) => one.id === voiceId)?.name;
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
          <VoiceField workspaceId={workspaceId} value={String(attributes.voice_id ?? "")} onChange={(voice_id) => save({ voice_id })} />
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
        <button
          type="button"
          aria-label={t("entityClear")}
          title={t("entityClear")}
          onClick={(event) => {
            event.preventDefault();
            onChange("");
          }}
          className="ml-auto grid size-6 cursor-pointer place-items-center rounded border-0 bg-transparent p-0 text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          <X size={14} />
        </button>
      )}
    </label>
  );
}

function VoiceField({ workspaceId, value, onChange }: { workspaceId: string; value: string; onChange: (next: string) => void }) {
  const t = useI18n();
  const voices = useQuery({ queryKey: ["voices", workspaceId], queryFn: () => listVoices(workspaceId) });
  return (
    <Field label={t("entityVoice")} hint={t("entityVoiceHint")}>
      <OptionPicker
        ariaLabel={t("entityVoice")}
        value={value || NONE}
        onChange={(next) => onChange(next === NONE ? "" : next)}
        options={[{ value: NONE, label: t("entityNone") }, ...(voices.data ?? []).map((voice) => ({ value: voice.id, label: voice.name }))]}
      />
    </Field>
  );
}

function SceneField({ workspaceId, value, onChange }: { workspaceId: string; value: string; onChange: (next: string) => void }) {
  const t = useI18n();
  const scenes = useQuery({ queryKey: ["scene-picker", workspaceId], queryFn: () => listScenes(workspaceId) });
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
  //: 从社区导入的真人:别人声明过授权,这台机器上还没人确认 —— 选一项就是确认。
  const pending = consent?.kind === "pending";
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
      {pending && (
        <div role="note" className="grid gap-1 rounded-md border border-warning/40 bg-warning/10 px-3 py-2" data-consent-pending="">
          <span className="flex items-center gap-1.5 text-ui-sm font-medium">
            <ShieldAlert size={14} className="text-warning" />
            {t("entityConsentPending")}
          </span>
          <span className="text-ui-xs leading-relaxed text-muted-foreground">{t("entityConsentPendingBody")}</span>
        </div>
      )}
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
        {consent?.declared_at && !pending ? ` · ${t("entityConsentDeclaredAt").replace("{at}", consent.declared_at.slice(0, 10))}` : ""}
      </p>
    </fieldset>
  );
}

/** 在哪里用过:画板(资产格 / 提示词里 @ 了它)、生成记录、工作流。点一下过去。 */
function UsageSection({ workspaceId, entityId }: { workspaceId: string; entityId: string }) {
  const t = useI18n();
  const usage = useQuery({ queryKey: entityKeys.usage(workspaceId, entityId), queryFn: () => getEntityUsage(entityId) });
  const rows = usage.data;
  const empty = rows && rows.boards.length + rows.generations.length + rows.workflows.length === 0;
  const go = (hash: string) => {
    window.location.hash = hash;
  };
  return (
    <section className="grid gap-3" aria-label={t("entityUsage")} data-entity-usage="">
      <h3 className="m-0 text-ui-md font-semibold">{t("entityUsage")}</h3>
      {usage.isPending ? (
        <Skeleton className="h-10 w-full" />
      ) : empty || !rows ? (
        <p className="m-0 text-ui-sm text-muted-foreground">{t("entityUsageEmpty")}</p>
      ) : (
        <ul className="m-0 grid list-none gap-1 p-0">
          {rows.boards.map((board) => (
            <UsageRow
              key={`b-${board.id}`}
              icon={<LayoutGrid size={14} />}
              title={board.name}
              meta={t(board.how === "cell" ? "entityUsageCell" : "entityUsageMention")}
              onOpen={() => go(`#/boards?board=${encodeURIComponent(board.id)}`)}
            />
          ))}
          {rows.generations.map((one) => (
            <UsageRow
              key={`g-${one.id}`}
              icon={one.kind === "video" ? <Clapperboard size={14} /> : <BookImage size={14} />}
              title={one.prompt || one.model}
              meta={`${t("entityUsageGeneration")} · ${one.model} · ${one.created_at.slice(0, 10)}`}
              onOpen={() => go("#/ai")}
              thumb={one.result_asset_id}
              session={one.session_id}
            />
          ))}
          {rows.workflows.map((flow) => (
            <UsageRow
              key={`w-${flow.id}`}
              icon={<WorkflowIcon size={14} />}
              title={flow.name}
              meta={t("entityUsageWorkflow")}
              onOpen={() => go("#/workflows")}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function UsageRow({
  icon,
  title,
  meta,
  onOpen,
  thumb,
  session,
}: {
  icon: React.ReactNode;
  title: string;
  meta: string;
  onOpen: () => void;
  thumb?: string | null;
  session?: string | null;
}) {
  return (
    <li>
      <button
        type="button"
        data-usage-session={session ?? undefined}
        data-usage-result={thumb ?? undefined}
        onClick={onOpen}
        className="flex w-full cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-1.5 text-left hover:bg-secondary"
      >
        <span className="text-muted-foreground">{icon}</span>
        <span className="min-w-0 flex-1 truncate text-ui-sm">{title}</span>
        <span className="shrink-0 text-ui-xs text-muted-foreground">{meta}</span>
      </button>
    </li>
  );
}
