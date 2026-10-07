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
 * 放它交回的东西(装节点包的按钮),`missingNodesNote` 放在那一节底下(装到哪了、要不要重启)。导入前的预览都不给 ——
 * 那时这张还没存进去。
 */
export function WorkflowFacts({
  facts,
  onShowModel,
  packAction,
  missingNodesNote,
}: {
  facts: WorkflowFactsSource;
  onShowModel?: (focus: ModelFocus) => void;
  packAction?: (pack: WorkflowNodePack) => React.ReactNode;
  missingNodesNote?: React.ReactNode;
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
          <ul className={FACT_LIST}>
            {(facts.models ?? []).map((one) => (
              <FactRow
                key={`${one.folder}/${one.name}`}
                data-model-row=""
                primary={one.name}
                meta={one.folder}
                status={
                  <CatalogBadge tone={one.present ? "success" : "warning"}>
                    {one.present ? t("workflowModelPresent") : t("workflowModelMissing")}
                  </CatalogBadge>
                }
                //: 缺的在下面「缺的模型」那一节里下载;这里只给在的那几个跳到模型库。缺的那行照样留着那一格,「在 / 缺」对成一列
                action={
                  onShowModel ? (
                    one.present ? (
                      <IconButton
                        size="icon-xs"
                        className="text-muted-foreground"
                        label={t("workflowShowInModelLibrary").replace("{name}", one.name)}
                        onClick={() => onShowModel({ model: { folder: one.folder, name: one.name } })}
                      >
                        <Library size={13} />
                      </IconButton>
                    ) : null
                  ) : undefined
                }
              />
            ))}
          </ul>
        ) : (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowModelsNone")}</p>
        )}
      </LibrarySection>
      {(facts.missing_nodes?.length ?? 0) > 0 && (
        <LibrarySection title={t("workflowMissingNodes")} count={facts.missing_nodes?.length}>
          <ul className={FACT_LIST}>
            {(facts.missing_nodes ?? []).map((one) => (
              <li key={one.type} data-missing-node="" className="grid min-w-0 pb-1">
                <FactLine primary={one.type} meta={`×${one.count}`} />
                {/* 节点 → 出自哪几个节点包:缩进一级、左边一道细线,一眼看出这几行属于上面那个节点 */}
                <ul data-node-packs="" className="m-0 ml-1.5 grid list-none border-l border-divider p-0 pl-3">
                  {(one.packs?.length ?? 0) > 0 ? (
                    (one.packs ?? []).map((pack) => (
                      <FactRow
                        key={pack.id}
                        data-node-pack=""
                        primary={pack.title}
                        hint={pack.id !== pack.title ? pack.id : undefined}
                        secondary={pack.installed ? t("workflowPackInstalledNotLoaded") : t("workflowPackNotInstalled")}
                        warn={pack.installed}
                        action={packAction ? packAction(pack) : undefined}
                      />
                    ))
                  ) : (
                    <FactRow data-node-pack="" primary={t("workflowPackUnknown")} muted action={packAction ? null : undefined} />
                  )}
                </ul>
              </li>
            ))}
          </ul>
          {missingNodesNote}
        </LibrarySection>
      )}
      {(facts.missing_models?.length ?? 0) > 0 && (
        <LibrarySection title={t("workflowMissingModels")} count={facts.missing_models?.length}>
          <ul className={FACT_LIST}>
            {(facts.missing_models ?? []).map((one) => (
              <FactRow
                key={`${one.folder}/${one.name}`}
                data-missing-model=""
                primary={one.name}
                meta={one.folder}
                secondary={one.url ? new URL(one.url).host : t("workflowMissingModelNoUrl")}
                action={
                  onShowModel ? (
                    <Button variant="outline" size="xs" aria-label={t("workflowDownloadInModelLibrary").replace("{name}", one.name)}
                            onClick={() => onShowModel({ download: { folder: one.folder, name: one.name, ...(one.url ? { url: one.url } : {}) } })}>
                      <Download size={12} />
                      {t("modelMissingDownload")}
                    </Button>
                  ) : undefined
                }
              />
            ))}
          </ul>
        </LibrarySection>
      )}
    </>
  );
}

/** 三节(用到的模型、缺的节点、缺的模型)的列表:行与行之间一道细线,行距由行自己的高度定。 */
const FACT_LIST = "m-0 grid list-none divide-y divide-divider p-0";
/** 最右那一格动作的宽度:「装上」「下载」(xs 按钮带图标)放得下,跳到模型库的方按钮靠右 —— 三节的动作对成一列。 */
const FACT_SLOT = "flex w-[4.5rem] shrink-0 items-center justify-end";

type FactLineProps = {
  /** 主行:名字(放不下截断,悬停看全文) */
  primary: string;
  /** 和名字同一条基线、靠右的一点说明:目录、个数 */
  meta?: string;
  /** 主行下面一行灰字:从哪下、装没装 */
  secondary?: string;
  /** 名字之外要补一句的(节点包的 id) */
  hint?: string;
  /** 主行本身就是一句说明(「不知道是哪个节点包」):灰字 */
  muted?: boolean;
  /** 灰字那一行要提醒(装了却没加载) */
  warn?: boolean;
  status?: React.ReactNode;
  /**
   * 最右那一格:给了东西就放它;`null` 是这一行没有动作,但同一节的别的行有 —— 照样留出那一格,对成一列;
   * 不给(`undefined`)是这一节都没有动作(导入前的预览),不留。
   */
  action?: React.ReactNode;
};

/**
 * 一行的样子 —— 三节一个样:主行(名字 + 同一条基线上的目录 / 个数)、需要时一行灰字、状态、最右一格同样宽的动作。
 * 至少 40px 高(28px 的按钮上下各留 6px),一行字和两行字的行都在这个高度里垂直居中:有按钮的行不再比没按钮的高一截。
 */
function FactLine({ primary, meta, secondary, hint, muted, warn, status, action }: FactLineProps) {
  const reserved = action !== undefined;
  return (
    <div className="flex min-h-10 min-w-0 items-center gap-2 py-1">
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="flex min-w-0 items-baseline gap-2">
          <Truncate hint={hint} className={cn("min-w-0 flex-1 text-ui-sm", muted ? "text-muted-foreground" : "text-foreground")}>
            {primary}
          </Truncate>
          {meta && <span className="shrink-0 text-ui-xs tabular-nums text-muted-foreground">{meta}</span>}
        </span>
        {secondary && (
          <Truncate className={cn("text-ui-xs", warn ? "text-warning" : "text-muted-foreground")}>{secondary}</Truncate>
        )}
      </span>
      {status}
      {reserved && <span data-fact-slot="" className={FACT_SLOT}>{action}</span>}
    </div>
  );
}

function FactRow({ "data-model-row": modelRow, "data-node-pack": nodePack, "data-missing-model": missingModel, ...line }:
  FactLineProps & { "data-model-row"?: string; "data-node-pack"?: string; "data-missing-model"?: string }) {
  return (
    <li data-fact-row="" data-model-row={modelRow} data-node-pack={nodePack} data-missing-model={missingModel} className="min-w-0">
      <FactLine {...line} />
    </li>
  );
}
