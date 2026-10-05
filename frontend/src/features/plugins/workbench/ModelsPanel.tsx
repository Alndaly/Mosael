import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, MousePointerClick, RefreshCcw, Search } from "lucide-react";

import { getModelLibrary, getNodeFolders, modelPreviewUrl, type ModelFile } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { useImagePreview } from "@/components/app/image-preview";
import { ModelThumb, modelBaseName } from "@/components/generation/ModelThumb";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Truncate } from "@/components/ui/truncate";
import { ModelDownload } from "@/features/plugins/workbench/ModelDownload";
import {
  comboInputs,
  folderFamilies,
  folderModels,
  modelSlots,
  presentIn,
  type ModelSlot,
  type WorkbenchNode,
} from "@/features/plugins/workbench/workbenchLogic";
import { PANEL_ROOT, PanelEmpty, PanelLoading, PanelNote } from "@/features/plugins/workbench/workbenchParts";
import { workbenchCall, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

/** 一次最多摆多少个(一个目录里见过几百个 LoRA):多了先搜。 */
const LISTED = 120;

/**
 * 工作台的「模型库」面板(ADR 0038 §6):在画布上选中一个加载节点 → 问插件它那几格选的是哪个模型目录的文件 → 用模型库的数据
 * 只列那个目录的(缩略图、底模家族、触发词),能搜、能按家族筛 → 点一行,经桥填进那一格(桥先查它在下拉里);点缩略图看大图。
 * 现在那一格选的文件这台 ComfyUI 上没有,就地找下载地址或贴链接下到那个目录;下完经桥刷新下拉,新文件出现在下拉里。
 */
export function ModelsPanel({
  target,
  node,
  capabilities,
}: {
  target: WorkbenchTarget;
  node: WorkbenchNode | null;
  capabilities: ComfyWorkbenchState["capabilities"] | null;
}) {
  const t = useI18n();
  const inputs = React.useMemo(() => comboInputs(node), [node]);
  const folders = useQuery({
    queryKey: ["comfy-node-folders", target.instanceId, inputs.map((one) => `${one.class_type}:${one.input}`).join("|")],
    queryFn: () => getNodeFolders(target.instanceId, inputs),
    enabled: inputs.length > 0,
    staleTime: Infinity,
  });
  const library = useQuery({
    queryKey: ["model-library", target.instanceId],
    queryFn: () => getModelLibrary(target.instanceId),
    staleTime: 30_000,
  });
  const slots = modelSlots(node, folders.data?.folders ?? []);

  if (capabilities && (!capabilities.selection || !capabilities.setWidget)) {
    return <PanelNote tone="warning">{t("workbenchUnsupported").replace("{what}", t("workbenchCapSelection"))}</PanelNote>;
  }
  if (!node) return <PanelEmpty icon={MousePointerClick}>{t("workbenchModelsPick")}</PanelEmpty>;
  if (folders.isPending && inputs.length > 0) return <PanelLoading label={t("workbenchModelsLoading")} />;
  if (folders.isError) return <PanelNote tone="error">{errorText(folders.error)}</PanelNote>;
  if (slots.length === 0) {
    return <PanelEmpty icon={MousePointerClick}>{t("workbenchModelsNoSlot").replace("{node}", node.title || node.type)}</PanelEmpty>;
  }
  return (
    <div className={cn(PANEL_ROOT, "gap-4")}>
      {slots.map((slot) => (
        <SlotPicker
          key={`${node.id}:${slot.widget}`}
          target={target}
          node={node}
          slot={slot}
          models={library.data?.models ?? []}
          loading={library.isPending}
          error={library.isError ? errorText(library.error) : ""}
          canRefresh={capabilities?.refreshCombos !== false}
        />
      ))}
    </div>
  );
}

type Note = { tone: "info" | "warning" | "error"; text: string; refresh?: boolean };

function SlotPicker({
  target,
  node,
  slot,
  models,
  loading,
  error,
  canRefresh,
}: {
  target: WorkbenchTarget;
  node: WorkbenchNode;
  slot: ModelSlot;
  models: ModelFile[];
  loading: boolean;
  error: string;
  canRefresh: boolean;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const { openImagePreview } = useImagePreview();
  const [query, setQuery] = React.useState("");
  const [family, setFamily] = React.useState("");
  //: 填进去的结果那一句:**只在回话到了时换成新的一句**,填的过程中不先撤掉 —— 撤掉再放回来,下面整个列表会先往上
  //: 跳、再往下跳(维护者:「每次切换模型都会导致右侧这个窗口闪烁一下」)
  const [note, setNote] = React.useState<Note | null>(null);
  //: 说有预览图、取的时候却没取到的那几个:缩略图换成了占位,也就没有大图可看
  const [failed, setFailed] = React.useState<ReadonlySet<string>>(() => new Set());
  //: 模型库的「模糊预览图」记在本机,这里照着它(读同一个开关,不另起一个)
  const [blur] = usePersistentTab<"on" | "off">("model-library.blur", "off", ["on", "off"]);
  const blurred = blur === "on";
  const families = folderFamilies(models, slot.folder);
  const listed = folderModels(models, slot.folder, { query, family });
  const present = presentIn(models, slot.folder, slot.value);

  const pick = useMutation({
    mutationFn: (model: ModelFile) =>
      workbenchCall({ op: "setWidget", node: node.id, widget: slot.widget, value: model.name }),
    onSuccess: (result, model) => {
      if (result.ok) setNote({ tone: "info", text: t("workbenchModelsFilled").replace("{name}", modelBaseName(model.name)) });
      else if (result.error === "notInList") setNote({ tone: "warning", text: t("workbenchModelsNotInList"), refresh: true });
      else setNote({ tone: "error", text: t("workbenchCallFailed").replace("{why}", "message" in result && result.message ? result.message : result.error) });
    },
  });
  const refresh = useMutation({
    mutationFn: () => workbenchCall({ op: "refreshCombos" }),
    onSuccess: (result) => {
      setNote(result.ok ? { tone: "info", text: t("workbenchCombosRefreshed") } : { tone: "error", text: t("workbenchCallFailed").replace("{why}", result.error) });
      void qc.invalidateQueries({ queryKey: ["model-library", target.instanceId] });
    },
  });

  const previewable = (model: ModelFile) => model.has_preview && !failed.has(model.name);
  //: 看大图:这一页列着的、有预览图的成组翻(按列表的顺序)。开着「模糊预览图」时只开点的那一张 —— 点它是明确要看这一张,
  //: 翻到别的就等于没经同意替人把它们都看清了
  const preview = (model: ModelFile) => {
    const item = (one: ModelFile) => ({ src: modelPreviewUrl(target.instanceId, one.folder, one.name), title: one.title || modelBaseName(one.name) });
    const gallery = blurred ? [item(model)] : listed.slice(0, LISTED).filter(previewable).map(item);
    openImagePreview({ ...item(model), gallery });
  };

  return (
    <section aria-label={`${slot.widget} · ${slot.folder}`} className="grid gap-2.5">
      <header className="grid gap-1">
        <h3 className="m-0 flex min-w-0 items-center gap-1.5 text-ui-sm font-semibold text-foreground">
          <Truncate>{node.title || node.type}</Truncate>
          <span className="shrink-0 text-ui-xs font-normal text-muted-foreground">#{node.id} · {slot.widget}</span>
        </h3>
        {/* 固定一行的高:「这台 ComfyUI 上没有」那枚标签比字高,一出一没整块会跟着跳 */}
        <div className="flex h-6 min-w-0 items-center gap-1.5 text-ui-xs text-muted-foreground">
          <span className="shrink-0">{t("workbenchModelsCurrent")}</span>
          <Truncate className="min-w-0 text-foreground">{slot.value || "—"}</Truncate>
          {!loading && !error && !present && <CatalogBadge tone="warning">{t("workbenchModelsMissing")}</CatalogBadge>}
        </div>
      </header>
      {note && (
        <PanelNote
          tone={note.tone}
          action={note.refresh && canRefresh ? (
            <Button variant="outline" size="xs" className="shrink-0" loading={refresh.isPending} onClick={() => refresh.mutate()}>
              <RefreshCcw size={12} />
              {t("workbenchCombosRefresh")}
            </Button>
          ) : undefined}
        >
          {note.text}
        </PanelNote>
      )}
      {!loading && !error && !present && (
        <ModelDownload target={target} folder={slot.folder} wanted={slot.value}
                       doneLabel={t(canRefresh ? "workbenchDownloadDone" : "workbenchDownloadDoneManual")}
                       onDone={() => {
                         void qc.invalidateQueries({ queryKey: ["model-library", target.instanceId] });
                         if (canRefresh) refresh.mutate();
                       }} />
      )}
      <label className="relative">
        <Search size={13} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input size="xs" className="pl-8" value={query} placeholder={t("workbenchModelsSearch").replace("{folder}", slot.folder)}
               aria-label={t("workbenchModelsSearch").replace("{folder}", slot.folder)} onChange={(event) => setQuery(event.target.value)} />
      </label>
      {families.length > 1 && (
        <div role="group" aria-label={t("workbenchModelsFamily")} className="flex flex-wrap gap-1">
          {["", ...families].map((one) => (
            <button
              key={one || "all"}
              type="button"
              aria-pressed={family === one}
              className={cn(
                "h-6 cursor-pointer rounded-full border px-2 text-ui-xs",
                family === one ? "border-primary/50 bg-accent text-primary" : "border-border bg-transparent text-muted-foreground hover:bg-secondary",
              )}
              onClick={() => setFamily(one)}
            >
              {one || t("workbenchModelsFamilyAll")}
            </button>
          ))}
        </div>
      )}
      {loading ? (
        <LoadingState label={t("workbenchModelsLoading")} className="h-auto py-6" />
      ) : error ? (
        <PanelNote tone="error">{error}</PanelNote>
      ) : listed.length === 0 ? (
        <p className="m-0 text-ui-xs text-muted-foreground">{t("workbenchModelsEmpty")}</p>
      ) : (
        <ul aria-label={t("workbenchModelsList").replace("{folder}", slot.folder)} className="m-0 grid list-none gap-1 p-0">
          {listed.slice(0, LISTED).map((model) => {
            const chosen = model.name.replace(/\\/g, "/") === slot.value.replace(/\\/g, "/");
            const filling = pick.isPending && pick.variables?.name === model.name;
            const name = model.title || modelBaseName(model.name);
            const thumb = (
              <ModelThumb compact instanceId={target.instanceId} model={model} blurred={blurred}
                          onFailed={() => setFailed((current) => new Set([...current, model.name]))} />
            );
            return (
              <li
                key={model.name}
                data-model-row=""
                className={cn(
                  "group/thumb flex min-w-0 items-center gap-2.5 rounded-lg border p-1.5",
                  chosen ? "border-primary/50 bg-accent" : "border-transparent hover:bg-secondary",
                )}
              >
                {previewable(model) ? (
                  <IconButton
                    unstyled
                    type="button"
                    data-model-preview=""
                    label={t("workbenchModelsPreview").replace("{name}", name)}
                    className="size-11 shrink-0 cursor-zoom-in overflow-hidden rounded-md border-0 bg-transparent p-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring [&>*]:size-full"
                    onClick={() => preview(model)}
                  >
                    {thumb}
                  </IconButton>
                ) : (
                  <span className="size-11 shrink-0 overflow-hidden rounded-md [&>*]:size-full">{thumb}</span>
                )}
                <button
                  type="button"
                  aria-pressed={chosen}
                  aria-busy={filling || undefined}
                  disabled={pick.isPending}
                  className="flex min-w-0 flex-1 cursor-pointer items-center gap-2.5 self-stretch border-0 bg-transparent p-0 text-left disabled:cursor-default"
                  onClick={() => pick.mutate(model)}
                >
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <Truncate className="text-ui-xs font-medium text-foreground">{name}</Truncate>
                    <span className="flex min-w-0 items-center gap-1 text-ui-2xs text-muted-foreground">
                      {model.family && <CatalogBadge tone="muted">{model.family}</CatalogBadge>}
                      <Truncate>{(model.triggers ?? []).slice(0, 3).join(", ") || modelBaseName(model.name)}</Truncate>
                    </span>
                  </span>
                  {/* 同一格:填的过程中是转圈,填好了是对勾 —— 宽度不变,这一行不跳 */}
                  <span className="grid size-4 shrink-0 place-items-center">
                    {filling ? <Loader2 size={14} aria-hidden className="animate-mosael-spin text-muted-foreground" />
                      : chosen ? <Check size={14} aria-hidden className="text-primary" /> : null}
                  </span>
                </button>
              </li>
            );
          })}
          {listed.length > LISTED && (
            <li className="px-1.5 text-ui-xs text-muted-foreground">
              {t("workbenchModelsMore").replace("{n}", String(listed.length - LISTED))}
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
