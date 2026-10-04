import React from "react";
import { Download, Library } from "lucide-react";

import type { WorkflowFile, WorkflowNodePack } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { LibrarySection } from "@/components/app/LibraryBrowser";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import type { ModelFocus } from "@/features/plugins/libraryLinks";
import { cn } from "@/lib/utils";

type Translate = ReturnType<typeof useI18n>;

/** 一张工作流「是什么样」的那几样:工作流库的详情、导入前的预览是同一份。 */
export type WorkflowFactsSource = Pick<WorkflowFile, "inputs" | "parameters" | "outputs" | "models" | "missing_nodes" | "missing_models">;

export const kindName = (t: Translate, kind: string) =>
  kind === "image" || kind === "video" || kind === "audio" ? t(`workflowKind_${kind}`) : t("workflowKind_unknown");

export const mediaName = (t: Translate, media: string) =>
  media === "image" || media === "video" || media === "audio" || media === "text" ? t(`workflowMedia_${media}`) : media;

/**
 * 能填什么 / 能调什么 / 交出什么、用到的模型(在不在)、缺的节点(出自哪个节点包、装没装)、缺的模型(声明的下载地址)。
 *
 * `onShowModel` 给了才有跳到模型库的入口(在的停到那一项,缺的打开下载框);`packAction` 给了,「缺的节点」每个节点包后面
 * 放它交回的东西(装节点包的按钮)。导入前的预览两样都不给 —— 那时这张还没存进去。
 */
export function WorkflowFacts({
  facts,
  onShowModel,
  packAction,
}: {
  facts: WorkflowFactsSource;
  onShowModel?: (focus: ModelFocus) => void;
  packAction?: (pack: WorkflowNodePack) => React.ReactNode;
}) {
  const t = useI18n();
  const parameters = facts.parameters ?? [];
  const [allParameters, setAllParameters] = React.useState(false);
  return (
    <>
      {(facts.inputs?.length ?? 0) > 0 && (
        <LibrarySection title={t("workflowInputs")} count={facts.inputs?.length}>
          <ul className="m-0 grid list-none gap-1 p-0">
            {(facts.inputs ?? []).map((one) => (
              <li key={`${one.node}-${one.role}`} className="flex min-w-0 items-baseline gap-2 text-ui-sm text-foreground">
                <Truncate className="min-w-0 flex-1">{one.title}</Truncate>
                <span className="shrink-0 text-ui-xs text-muted-foreground">{mediaName(t, one.media)}</span>
              </li>
            ))}
          </ul>
        </LibrarySection>
      )}
      {parameters.length > 0 && (
        <LibrarySection
          title={t("workflowParameters")}
          count={parameters.length}
          action={
            parameters.length > 12 ? (
              <Button variant="ghost" size="sm" className="text-muted-foreground" aria-expanded={allParameters}
                      onClick={() => setAllParameters(!allParameters)}>
                {allParameters ? t("modelMetaCollapse") : t("modelTagsAll").replace("{n}", String(parameters.length))}
              </Button>
            ) : undefined
          }
        >
          <ul className="m-0 flex min-w-0 list-none flex-wrap gap-1.5 p-0">
            {(allParameters ? parameters : parameters.slice(0, 12)).map((one) => (
              <li key={one.key} className="min-w-0 max-w-full">
                <Hint label={one.key}>
                  <span className="inline-flex h-7 max-w-full items-center rounded-full bg-secondary px-2.5 text-ui-xs text-foreground">
                    <Truncate>{one.title}</Truncate>
                  </span>
                </Hint>
              </li>
            ))}
          </ul>
        </LibrarySection>
      )}
      {(facts.outputs?.length ?? 0) > 0 && (
        <LibrarySection title={t("workflowOutputs")} count={facts.outputs?.length}>
          <ul className="m-0 grid list-none gap-1 p-0">
            {(facts.outputs ?? []).map((one) => (
              <li key={one.node} className="flex min-w-0 items-baseline gap-2 text-ui-sm text-foreground">
                <Truncate className="min-w-0 flex-1">{one.title}</Truncate>
                <span className="shrink-0 text-ui-xs text-muted-foreground">{mediaName(t, one.media)}</span>
              </li>
            ))}
          </ul>
        </LibrarySection>
      )}
      <LibrarySection title={t("workflowModels")} count={facts.models?.length ?? 0}>
        {(facts.models?.length ?? 0) > 0 ? (
          <ul className="m-0 grid list-none gap-1 p-0">
            {(facts.models ?? []).map((one) => (
              <li key={`${one.folder}/${one.name}`} className="flex min-w-0 items-center gap-2 text-ui-sm text-foreground">
                <Truncate className="min-w-0 flex-1">{one.name}</Truncate>
                <span className="shrink-0 text-ui-xs text-muted-foreground">{one.folder}</span>
                <CatalogBadge tone={one.present ? "success" : "warning"}>
                  {one.present ? t("workflowModelPresent") : t("workflowModelMissing")}
                </CatalogBadge>
                {/* 缺的在下面「缺的模型」那一节里下载;这里只给在的那几个跳到模型库 */}
                {onShowModel && one.present && (
                  <IconButton
                    size="sm"
                    className="shrink-0 text-muted-foreground"
                    label={t("workflowShowInModelLibrary").replace("{name}", one.name)}
                    onClick={() => onShowModel({ model: { folder: one.folder, name: one.name } })}
                  >
                    <Library size={13} />
                  </IconButton>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowModelsNone")}</p>
        )}
      </LibrarySection>
      {(facts.missing_nodes?.length ?? 0) > 0 && (
        <LibrarySection title={t("workflowMissingNodes")} count={facts.missing_nodes?.length}>
          <ul className="m-0 grid list-none gap-2 p-0">
            {(facts.missing_nodes ?? []).map((one) => (
              <li key={one.type} className="grid min-w-0 gap-0.5">
                <span className="flex min-w-0 items-baseline gap-2 text-ui-sm text-foreground">
                  <Truncate className="min-w-0">{one.type}</Truncate>
                  <span className="shrink-0 text-ui-xs tabular-nums text-muted-foreground">×{one.count}</span>
                </span>
                {(one.packs?.length ?? 0) > 0 ? (
                  (one.packs ?? []).map((pack) => (
                    <span key={pack.id} className="flex min-w-0 items-center gap-2 text-ui-xs text-muted-foreground">
                      <Truncate hint={pack.id !== pack.title ? pack.id : undefined}>{pack.title}</Truncate>
                      <span className={cn("shrink-0", pack.installed && "text-warning")}>
                        {pack.installed ? t("workflowPackInstalledNotLoaded") : t("workflowPackNotInstalled")}
                      </span>
                      {packAction?.(pack)}
                    </span>
                  ))
                ) : (
                  <span className="text-ui-xs text-muted-foreground">{t("workflowPackUnknown")}</span>
                )}
              </li>
            ))}
          </ul>
        </LibrarySection>
      )}
      {(facts.missing_models?.length ?? 0) > 0 && (
        <LibrarySection title={t("workflowMissingModels")} count={facts.missing_models?.length}>
          <ul className="m-0 grid list-none gap-1 p-0">
            {(facts.missing_models ?? []).map((one) => (
              <li key={`${one.folder}/${one.name}`} className="flex min-w-0 items-center gap-3">
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <span className="flex min-w-0 items-baseline gap-2 text-ui-sm text-foreground">
                    <Truncate className="min-w-0 flex-1">{one.name}</Truncate>
                    <span className="shrink-0 text-ui-xs text-muted-foreground">{one.folder}</span>
                  </span>
                  <Truncate className="text-ui-xs text-muted-foreground">
                    {one.url ? new URL(one.url).host : t("workflowMissingModelNoUrl")}
                  </Truncate>
                </span>
                {onShowModel && (
                  <Button variant="outline" size="sm" aria-label={t("workflowDownloadInModelLibrary").replace("{name}", one.name)}
                          onClick={() => onShowModel({ download: { folder: one.folder, name: one.name, ...(one.url ? { url: one.url } : {}) } })}>
                    <Download size={13} />
                    {t("modelMissingDownload")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </LibrarySection>
      )}
    </>
  );
}
