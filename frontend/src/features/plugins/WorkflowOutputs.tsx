import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EyeOff, Music, Play, RotateCcw, ShieldAlert, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import {
  assetThumbnailUrl,
  getWorkflowOutputs,
  markWorkflowOutputNsfw,
  type Asset,
  type ModelNsfw,
  type WorkflowRecentOutput,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { ActionContextMenuItems, ActionMenu, type MenuAction } from "@/components/app/ActionMenu";
import { AssetInlinePreview, assetPreviewItem } from "@/components/app/asset-preview";
import { useImagePreview } from "@/components/app/image-preview";
import { LibrarySection } from "@/components/app/LibraryBrowser";
import { ModelPreviewSettingsButton } from "@/components/generation/ModelPreviewSettingsButton";
import { NsfwMark, previewBlurClass } from "@/components/generation/ModelThumb";
import { previewTreatment, useModelPreviewSettings } from "@/components/generation/modelPreviewSettings";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuTrigger, openContextMenuFromKeyboard } from "@/components/ui/context-menu";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { useAssetDetails } from "@/lib/assetQueries";
import { cn } from "@/lib/utils";

/** 先摆几张;多的点「显示全部」(最多后端交的那么多,更早的在素材库里)。 */
export const OUTPUTS_SHOWN = 8;

export const workflowOutputsKey = (instanceId: string, workspaceId: string, path: string) =>
  ["workflow-outputs", instanceId, workspaceId, path] as const;

/**
 * 工作流库详情里「最近的产出」:这张工作流在这个工作区里的产出,**一组**,不是一张(维护者:「工作流产出这里应该是个图片集
 * 然后要支持nsfw过滤」)。
 *
 * - 用它生成的、当工具在工作流 / 智能体里跑的,一批出的每一张都在,新的在前(后端 workflow_library.outputs);
 *   先摆 OUTPUTS_SHOWN 张,「显示全部」展开;更早的那些在素材库里;
 * - 点一张开全站同一个灯箱,左右翻这一组里看得见的那几张(按设置不显示、也没点开的不进);视频在灯箱里播;音频一行一条播放条;
 * - **NSFW 和模型库同一套**(modelPreviewSettings):眼睛那颗改「预览图」「NSFW 预览」两组设置,和模型库、工作台改的是同一份;
 *   判成 NSFW 的按设置模糊(悬停 / 键盘聚焦看清)或不显示(点「显示这一张」只看这一张);角标的悬停说凭什么;判错了右键或 ⋯
 *   标成是 / 不是 / 改回自动判断(记在素材上,手动的压过本机识别)。
 */
export function WorkflowOutputs({ instanceId, workspaceId, path, label }: {
  instanceId: string;
  workspaceId: string;
  path: string;
  /** 这张工作流叫什么(替代文字用) */
  label: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const key = workflowOutputsKey(instanceId, workspaceId, path);
  const query = useQuery({
    queryKey: key,
    queryFn: () => getWorkflowOutputs(instanceId, workspaceId, path),
    enabled: Boolean(workspaceId),
    staleTime: 30_000,
  });
  const [all, setAll] = React.useState(false);
  const [revealed, setRevealed] = React.useState<ReadonlySet<string>>(() => new Set());
  const [settings] = useModelPreviewSettings();
  const { openImagePreview } = useImagePreview();
  const outputs = query.data?.outputs ?? [];
  const details = useAssetDetails(outputs.map((one) => one.asset_id)).byId;
  const mark = useMutation({
    mutationFn: ({ asset, nsfw }: { asset: string; nsfw: boolean | null }) =>
      markWorkflowOutputNsfw(instanceId, { workspace_id: workspaceId, asset_id: asset, nsfw }),
    onSuccess: (verdict, { asset }) => {
      qc.setQueryData(key, (previous: typeof query.data) =>
        previous && { ...previous, outputs: previous.outputs.map((one) => (one.asset_id === asset ? { ...one, nsfw: verdict } : one)) });
      //: 卡片上那一张(最近的那份)也带着判断:让工作流库重新问
      void qc.invalidateQueries({ queryKey: ["workflow-library", instanceId] });
    },
    onError: (error) => toast.error(errorText(error)),
  });
  if (!query.data || outputs.length === 0) return null;

  const treatmentOf = (one: WorkflowRecentOutput) =>
    revealed.has(one.asset_id) ? "clear" : previewTreatment(settings, Boolean(one.nsfw?.flagged));
  const visual = outputs.filter((one) => one.kind !== "audio");
  const audio = outputs.filter((one) => one.kind === "audio");
  const shown = all ? visual : visual.slice(0, OUTPUTS_SHOWN);
  //: 灯箱里翻的这一组:看得见的那几张(藏起来又没点开的不进 —— 灯箱里是看清的原图)
  const gallery = visual
    .filter((one) => treatmentOf(one) !== "hidden")
    .flatMap((one) => {
      const asset = details.get(one.asset_id);
      const item = asset ? assetPreviewItem(asset) : null;
      return item ? [{ asset: one.asset_id, item }] : [];
    });
  const open = (one: WorkflowRecentOutput) => {
    const found = gallery.find((entry) => entry.asset === one.asset_id);
    if (found) openImagePreview({ ...found.item, gallery: gallery.map((entry) => entry.item) });
  };
  const actionsOf = (one: WorkflowRecentOutput): MenuAction[] => {
    const nsfw: ModelNsfw = one.nsfw ?? { flagged: false, manual: null, reasons: [] };
    return [
      {
        label: t(nsfw.flagged ? "modelNsfwUnmark" : "modelNsfwMark"),
        icon: nsfw.flagged ? <ShieldCheck /> : <ShieldAlert />,
        onSelect: () => mark.mutate({ asset: one.asset_id, nsfw: !nsfw.flagged }),
      },
      ...(nsfw.manual != null
        ? [{ label: t("modelNsfwClearMark"), icon: <RotateCcw />, onSelect: () => mark.mutate({ asset: one.asset_id, nsfw: null }) }]
        : []),
    ];
  };

  return (
    <LibrarySection
      title={t("workflowLastOutput")}
      count={outputs.length}
      action={
        <span className="flex items-center gap-1">
          {visual.length > OUTPUTS_SHOWN && (
            <Button variant="ghost" size="sm" className="text-muted-foreground" aria-expanded={all} onClick={() => setAll(!all)}>
              {all ? t("modelMetaCollapse") : t("modelTagsAll").replace("{n}", String(visual.length))}
            </Button>
          )}
          {/* 和模型库那颗是同一份设置:这里改了,模型库、工作台跟着变 */}
          <ModelPreviewSettingsButton compact />
        </span>
      }
    >
      {shown.length > 0 && (
        <ul data-workflow-outputs="" className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(96px,1fr))] gap-2 p-0">
          {shown.map((one) => (
            <OutputTile
              key={one.asset_id}
              output={one}
              asset={details.get(one.asset_id)}
              treatment={treatmentOf(one)}
              alt={t("workflowLastOutputAlt").replace("{name}", label)}
              actions={actionsOf(one)}
              onOpen={() => open(one)}
              onReveal={() => setRevealed(new Set([...revealed, one.asset_id]))}
            />
          ))}
        </ul>
      )}
      {audio.length > 0 && (
        <ul className="m-0 grid list-none gap-2 p-0">
          {audio.map((one) => {
            const asset = details.get(one.asset_id);
            return (
              <li key={one.asset_id} data-workflow-output={one.asset_id} className="grid min-w-0 gap-1">
                <span className="flex min-w-0 items-center gap-1.5 text-ui-xs text-muted-foreground">
                  <Music size={12} aria-hidden className="shrink-0" />
                  <Truncate>{asset?.name || asset?.original_filename || one.asset_id}</Truncate>
                </span>
                {asset && <AssetInlinePreview assetId={asset.id} name={asset.name} kind="audio" className="w-full" />}
              </li>
            );
          })}
        </ul>
      )}
      {query.data.more && all && <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowOutputsMore")}</p>}
    </LibrarySection>
  );
}

/**
 * 一格:缩略图(视频是第一帧,角上一枚播放),按设置清晰 / 模糊 / 不显示;判成 NSFW 的角上一枚角标(悬停说凭什么);
 * 右上角悬停出现 ⋯,右键是同一份菜单(标成是 / 不是 NSFW、改回自动判断)。
 */
function OutputTile({ output, asset, treatment, alt, actions, onOpen, onReveal }: {
  output: WorkflowRecentOutput;
  asset: Asset | undefined;
  treatment: ReturnType<typeof previewTreatment>;
  alt: string;
  actions: MenuAction[];
  onOpen: () => void;
  onReveal: () => void;
}) {
  const t = useI18n();
  const name = asset?.name || asset?.original_filename || alt;
  const hidden = treatment === "hidden";
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild onKeyDown={openContextMenuFromKeyboard}>
        <li
          data-workflow-output={output.asset_id}
          data-treatment={treatment}
          className="group/thumb group relative aspect-square min-w-0 overflow-hidden rounded-lg border border-border bg-secondary"
        >
          {hidden ? (
            <div data-hidden-preview="" className="grid size-full place-items-center content-center gap-1.5 bg-[color-mix(in_srgb,var(--primary)_8%,var(--panel))] p-1 text-center text-primary">
              <EyeOff size={16} aria-hidden className="opacity-70" />
              <span className="text-ui-2xs text-muted-foreground">{t("modelPreviewHidden")}</span>
              <Button variant="secondary" size="xs" onClick={onReveal} aria-label={`${t("modelShowHiddenPreview")}:${name}`}>
                {t("modelShowHiddenPreview")}
              </Button>
            </div>
          ) : (
            <IconButton
              unstyled
              label={t("viewFullSizeOf").replace("{name}", name)}
              className="block size-full cursor-zoom-in border-0 bg-transparent p-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
              onClick={onOpen}
            >
              <img
                src={assetThumbnailUrl(output.asset_id)}
                alt={name}
                loading="lazy"
                draggable={false}
                className={cn("block size-full object-cover", previewBlurClass(treatment))}
              />
            </IconButton>
          )}
          {output.kind === "video" && !hidden && (
            <span aria-hidden className="pointer-events-none absolute bottom-1 left-1 grid size-5 place-items-center rounded-full bg-black/55 text-white">
              <Play size={10} className="fill-current" />
            </span>
          )}
          <span className="pointer-events-none absolute left-1 top-1 [&>*]:pointer-events-auto">
            <NsfwMark nsfw={output.nsfw} />
          </span>
          <span
            className="absolute right-1 top-1 rounded-md bg-panel opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 has-[[data-state=open]]:opacity-100"
            onClick={(event) => event.stopPropagation()}
          >
            <ActionMenu label={t("workflowOutputActions").replace("{name}", name)} actions={actions} />
          </span>
        </li>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ActionContextMenuItems actions={actions} />
      </ContextMenuContent>
    </ContextMenu>
  );
}
