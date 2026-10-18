import React from "react";
import { Download, Library } from "lucide-react";

import type { WorkflowFile, WorkflowNodePack } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { LibrarySection } from "@/components/app/LibraryBrowser";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import type { ModelFocus } from "@/features/plugins/libraryLinks";
import { cn } from "@/lib/utils";

type Translate = ReturnType<typeof useI18n>;

/** 图上要的那一版和装着的那一版:装的旧是「升级」、装的新是「降级」;比不了(git commit / 缺一个)是空串。 */
const SEMVER = /^[vV]?(\d+)\.(\d+)\.(\d+)/;
function versionRelation(wanted: string, installed: string): "upgrade" | "downgrade" | "same" | "" {
  const left = SEMVER.exec(wanted.trim());
  const right = SEMVER.exec(installed.trim());
  if (!left || !right) return "";
  const want = [Number(left[1]), Number(left[2]), Number(left[3])];
  const have = [Number(right[1]), Number(right[2]), Number(right[3])];
  const order = want.findIndex((value, index) => value !== have[index]);
  if (order < 0) return "same";
  return want[order] > have[order] ? "upgrade" : "downgrade";
}

/** 一个节点包那一行的灰字:不知道 / 没装 / 装了但被禁用 / 要哪一版装的是哪一版 / 装了没加载。 */
function packNote(t: Translate, pack: WorkflowNodePack): string {
  if (pack.state === "unknown") return t("workflowPackUnknownInstall");
  if (!pack.installed) return t("workflowPackNotInstalled");
  if (!pack.enabled) return t("workflowPackDisabled");
  const relation = pack.wanted_is_commit ? "" : versionRelation(pack.wanted_version ?? "", pack.installed_version ?? "");
  if (relation === "upgrade") {
    return t("workflowPackVersionUpgrade").replace("{wanted}", pack.wanted_version).replace("{installed}", pack.installed_version);
  }
  if (relation === "downgrade") {
    return t("workflowPackVersionDowngrade").replace("{wanted}", pack.wanted_version).replace("{installed}", pack.installed_version);
  }
  if (pack.wanted_is_commit && pack.wanted_version) {
    return t("workflowPackVersionCommit").replace("{version}", pack.wanted_version);
  }
  return t("workflowPackInstalledNotLoaded");
}

/** 一张工作流「是什么样」的那几样:工作流库的详情、导入前的预览是同一份。 */
export type WorkflowFactsSource = Pick<WorkflowFile, "models" | "missing_nodes" | "missing_models">;

export const kindName = (t: Translate, kind: string) =>
  kind === "image" || kind === "video" || kind === "audio" || kind === "text" ? t(`workflowKind_${kind}`) : t("workflowKind_unknown");

/**
 * 用到的模型(在不在)、缺的节点(出自哪个节点包、装没装)、缺的模型(声明的下载地址)。
 *
 * 「能填什么 / 能调什么 / 交出什么」不列在这里 —— 点那张表单进详情页就看得到(见 WorkflowLibrary 里表单那一行);
 * `outputs` 这份数据照旧有人读(表单编辑器的「结果取自」,见 WorkflowAppEditor),只是不再在这儿列一遍。
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
  return (
    <>
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
                //: 缺的在下面「缺的模型」那一节里下载;这里只给在的那几个跳到模型库。缺的没有动作,行尾那一格空着(那是动作的列,不是状态的位置)
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
              <li key={one.type} data-missing-node="" data-missing-core={one.core ? "" : undefined} className="grid min-w-0 pb-1">
                <FactLine primary={one.type} meta={`×${one.count}`}
                          secondary={one.core ? t("workflowMissingCore") : undefined} warn={one.core} />
                {/* 核心节点(图上写着 comfy-core):不是缺插件,是这台 ComfyUI 太老 —— 不列节点包,也不给「装上」。 */}
                {!one.core && (
                  <ul data-node-packs="" className="m-0 ml-1.5 grid list-none border-l border-divider p-0 pl-3">
                    {(one.packs?.length ?? 0) > 0 ? (
                      (one.packs ?? []).map((pack) => (
                        <FactRow
                          key={pack.id}
                          data-node-pack=""
                          primary={pack.title}
                          hint={pack.id !== pack.title ? pack.id : undefined}
                          secondary={packNote(t, pack)}
                          warn={pack.installed}
                          action={packAction ? packAction(pack) : undefined}
                        />
                      ))
                    ) : (
                      <FactRow data-node-pack="" primary={t("workflowPackUnknown")} muted action={packAction ? null : undefined} />
                    )}
                  </ul>
                )}
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
                meta={one.folder || t("workflowMissingModelUnknownFolder")}
                secondary={one.url ? new URL(one.url).host : t("workflowMissingModelNoUrl")}
                action={
                  onShowModel ? (
                    <Button variant="outline" size="xs" aria-label={t("workflowDownloadInModelLibrary").replace("{name}", one.name)}
                            onClick={() => onShowModel({ download: {
                              folder: one.folder, name: one.name,
                              ...(one.url ? { url: one.url } : {}),
                              //: 工作流自己声明的 SHA256:下载时一路带到插件,下完再算一遍对一对(见 ModelLibrary)。
                              ...(one.hash ? { hash: one.hash, hashType: one.hash_type ?? "" } : {}),
                            } })}>
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
  /** 紧跟在名字后面、同一条基线上的一点说明:目录、个数 */
  meta?: string;
  /** 主行下面一行灰字:从哪下、装没装 */
  secondary?: string;
  /** 名字之外要补一句的(节点包的 id) */
  hint?: string;
  /** 主行本身就是一句说明(「不知道是哪个节点包」):灰字 */
  muted?: boolean;
  /** 灰字那一行要提醒(装了却没加载) */
  warn?: boolean;
  /**
   * 状态(「在 / 缺」徽标):跟在目录名后面,一个正常的小间距 —— 它是这一行的状态,不是动作,
   * **不**推到行尾、也不占最右那一格(那一格只放动作,见 `action`)。
   */
  status?: React.ReactNode;
  /**
   * 最右那一格:给了东西就放它;`null` 是这一行没有动作,但同一节的别的行有 —— 照样留出那一格,对成一列;
   * 不给(`undefined`)是这一节都没有动作(导入前的预览),不留。
   */
  action?: React.ReactNode;
};

/**
 * 一行的样子 —— 三节一个样:主行(名字 + 紧跟其后的目录 / 个数 / 状态)、需要时一行灰字、最右一格同样宽的动作。
 * 名字那一格放不下时截断(悬停看全文),目录和状态 `shrink-0`:长名字压的是名字自己,不会把状态挤走,也不会
 * 把行撑出横向滚动。**只有动作**在最右那一格;状态跟在目录后面,不推到行尾 —— 否则会出现一条看起来像列、
 * 却和下面「下载」的右缘对不上的空当。
 * 至少 40px 高(28px 的按钮上下各留 6px),一行字和两行字的行都在这个高度里垂直居中:有按钮的行不再比没按钮的高一截。
 */
function FactLine({ primary, meta, secondary, hint, muted, warn, status, action }: FactLineProps) {
  const reserved = action !== undefined;
  return (
    <div className="flex min-h-10 min-w-0 items-center gap-2 py-1">
      <span className="grid min-w-0 flex-1 gap-0.5">
        {/*: 名字、目录、状态挨着排:名字不 flex-1 去撑满,目录和徽标才不会被顶到行尾(见本函数开头)。 */}
        <span data-fact-line="" className="flex min-w-0 items-baseline gap-2">
          <Truncate hint={hint} className={cn("text-ui-sm", muted ? "text-muted-foreground" : "text-foreground")}>
            {primary}
          </Truncate>
          {meta && <span className="shrink-0 text-ui-xs tabular-nums text-muted-foreground">{meta}</span>}
          {status}
        </span>
        {secondary && (
          <Truncate className={cn("text-ui-xs", warn ? "text-warning" : "text-muted-foreground")}>{secondary}</Truncate>
        )}
      </span>
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
