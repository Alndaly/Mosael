import React from "react";
import { useMutation } from "@tanstack/react-query";
import { Download, FolderOpen, Plus } from "lucide-react";

import { type ModelFile } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { ModelPreviewSettingsButton } from "@/components/generation/ModelPreviewSettingsButton";
import { ModelThumb, NsfwMark, PreviewOriginMark, modelBaseName } from "@/components/generation/ModelThumb";
import { previewTreatment, useModelPreviewSettings } from "@/components/generation/modelPreviewSettings";
import { useModelLibrary } from "@/components/generation/useModelLibrary";
import { Chip } from "@/components/ui/chip";
import { GRID_CARD_BODY, GRID_CARD_MEDIA, GridCardButton } from "@/components/ui/grid-card";
import { IconButton } from "@/components/ui/icon-button";
import { OverChromeModals } from "@/components/ui/overChromeModal";
import { SearchInput } from "@/components/ui/search-input";
import { Truncate } from "@/components/ui/truncate";
import type { Focused, ModelFocus } from "@/features/plugins/libraryLinks";
import { useNodeModelSlots } from "@/features/plugins/workbench/useNodeModelSlots";
import type { WorkbenchNode } from "@/features/plugins/workbench/workbenchLogic";
import { PanelEmpty, PanelLoading, PanelNote } from "@/features/plugins/workbench/workbenchParts";
import { workbenchCall, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";
import { formatBytes } from "@/lib/bytes";
import { cn } from "@/lib/utils";

/**
 * 模型库弹窗按需加载:工作台一进来先画已安装的模型;候选搜索/下载(模型库的大模块)等真正点下载时再取。
 * 这也让模型页签在模型库模块加载失败时仍然能显示已安装列表,不会整块空掉。
 */
const ModelLibraryDialog = React.lazy(() => import("@/features/plugins/ModelLibrary").then((module) => ({ default: module.ModelLibraryDialog })));

/**
 * 工作台的「模型」页签:全局模型库,不依赖画布上选中了哪个节点。
 *
 * 已安装模型按目录浏览、按名字/标题/触发词搜索;搜索与下载新模型交给模型库同一张弹窗
 * (ModelLibraryDialog),不再在窄侧栏里复制一套候选页面。节点相关的模型槽在「节点」页签。
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
  const [folder, setFolder] = React.useState("all");
  const [query, setQuery] = React.useState("");
  const [libraryOpen, setLibraryOpen] = React.useState(false);
  const [focus, setFocus] = React.useState<Focused<ModelFocus> | null>(null);
  const [settings] = useModelPreviewSettings();
  const library = useModelLibrary(target.instanceId, { staleTime: 30_000 });
  const { slots } = useNodeModelSlots(target, node);

  const models = library.data?.models ?? [];
  const folders = library.data?.folders ?? [];
  const shown = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    return models
      .filter((model) => folder === "all" || model.folder === folder)
      .filter((model) => !needle || `${model.name} ${model.title} ${(model.triggers ?? []).join(" ")}`.toLowerCase().includes(needle))
      .slice(0, 120);
  }, [models, folder, query]);

  const openModel = (model: ModelFile) => {
    setFocus({ model: { folder: model.folder, name: model.name }, at: 1 });
    setLibraryOpen(true);
  };
  const canFill = Boolean(node && capabilities?.setWidget);
  const fill = useMutation({
    mutationFn: ({ nodeId, widget, name }: { nodeId: string; widget: string; name: string }) =>
      workbenchCall({ op: "setWidget", node: nodeId, widget, value: name }),
  });
  //: 搜索/下载走模型库弹窗的下载那一页;空的 seed 就是「搜一个新的」,不是停在已安装列表
  const openDownload = () => {
    setFocus({ download: { folder: "", name: "" }, at: 1 });
    setLibraryOpen(true);
  };

  let body: React.ReactNode;
  if (library.isPending) {
    body = <PanelLoading label={t("workbenchModelsLoading")} />;
  } else if (library.isError) {
    body = <PanelNote tone="error">{library.error.message}</PanelNote>;
  } else if (models.length === 0) {
    body = <PanelEmpty icon={FolderOpen}>{t("workbenchModelsEmptyAll")}</PanelEmpty>;
  } else if (shown.length === 0) {
    body = <PanelEmpty icon={FolderOpen}>{t("workbenchModelsEmpty")}</PanelEmpty>;
  } else {
    body = (
      <ul aria-label={t("workbenchModelsTitle")} className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-3 p-0">
        {shown.map((model) => {
          const name = model.title || modelBaseName(model.name);
          const matches = canFill ? slots.filter((slot) => slot.folder === model.folder) : [];
          const slot = matches.length === 1 ? matches[0] : null;
          return (
            <li key={`${model.folder}/${model.name}`} className="relative min-w-0">
              <GridCardButton
                className="group/thumb h-full"
                onClick={() => openModel(model)}
                aria-label={t("workbenchModelsOpenNamed").replace("{name}", name)}
              >
                <span className={cn(GRID_CARD_MEDIA, "relative block aspect-[3/4]")} data-model-thumb={model.name}>
                  {/* ModelThumb 的加载占位是 absolute:父层必须是定位盒子,否则会按 aside 定位、盖住整列 */}
                  <ModelThumb
                    instanceId={target.instanceId}
                    model={model}
                    treatment={previewTreatment(settings, Boolean(model.nsfw?.flagged))}
                    className="absolute inset-0 size-full object-[50%_20%]"
                  />
                  <span className="pointer-events-none absolute left-1.5 top-1.5 z-10 flex gap-1">
                    <NsfwMark nsfw={model.nsfw} />
                    <PreviewOriginMark origin={model.preview_origin} />
                  </span>
                </span>
                <span className={GRID_CARD_BODY}>
                  <Truncate className="text-ui-xs font-medium text-foreground">{name}</Truncate>
                  <span className="flex min-w-0 items-center justify-between gap-2 text-ui-2xs text-muted-foreground">
                    <Truncate className="min-w-0">{model.folder}</Truncate>
                    <span className="shrink-0 tabular-nums">{model.size != null ? formatBytes(model.size) : ""}</span>
                  </span>
                </span>
              </GridCardButton>
              {slot && node && (
                <IconButton
                  variant="default"
                  size="icon-2xs"
                  className="absolute right-1.5 top-1.5 z-20 [-webkit-app-region:no-drag]"
                  label={t("workbenchModelsFillNamed").replace("{node}", node.title || node.type).replace("{widget}", slot.widget)}
                  disabled={fill.isPending}
                  onClick={() => fill.mutate({ nodeId: node.id, widget: slot.widget, name: model.name })}
                >
                  <Plus />
                </IconButton>
              )}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3" data-workbench-models="">
      <div className="flex min-w-0 items-center gap-2">
        <SearchInput
          className="min-w-0 flex-1"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("workbenchModelsSearchAll")}
          aria-label={t("workbenchModelsSearchAll")}
        />
        <ModelPreviewSettingsButton tier="md" />
        <IconButton
          variant="outline"
          size="icon"
          label={t("workbenchModelsDownload")}
          onClick={openDownload}
        >
          <Download size={13} />
        </IconButton>
      </div>
      {/* 目录可能有几十个:横着排、自己滚,不能让它折成十几行把模型列表挤出可视区 */}
      <div
        role="group"
        aria-label={t("workbenchModelsFolder")}
        data-workbench-models-folders=""
        className="flex min-w-0 flex-nowrap gap-1 overflow-x-auto pb-1"
      >
        <Chip selected={folder === "all"} onClick={() => setFolder("all")} role="radio">
          {t("workbenchModelsAll")} {models.length}
        </Chip>
        {folders.map((one) => (
          <Chip key={one.name} selected={folder === one.name} onClick={() => setFolder(one.name)} role="radio">
            {one.name} {one.count}
          </Chip>
        ))}
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{body}</div>
      {libraryOpen && (
        //: 工作台右栏是 DOM、外面盖着 ComfyUI 的原生视图:模型库弹窗要抬到外壳之上并让原生视图退开,否则点了像没反应
        <OverChromeModals.Provider value>
          <React.Suspense fallback={<PanelLoading label={t("workbenchModelsLoading")} />}>
            <ModelLibraryDialog
              open={libraryOpen}
              onOpenChange={(open) => {
                setLibraryOpen(open);
                if (!open) setFocus(null);
              }}
              instance={{ id: target.instanceId, name: target.instanceName }}
              workspaceId={target.workspaceId}
              focus={focus}
            />
          </React.Suspense>
        </OverChromeModals.Provider>
      )}
    </div>
  );
}
