import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageIcon, ImagePlus, Send, X } from "lucide-react";
import { toast } from "sonner";

import { assetKeys } from "@/api/queryKeys";
import {
  assetThumbnailUrl,
  listAssets,
  publishWorkflowToCommunity,
  type Asset,
  type CommunityPublishResult,
  type Workflow,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { PickListDialog } from "@/components/app/PickListDialog";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { COMMUNITY_STATUS_KEY } from "@/features/community/communityShared";
import { PublishedResult, parseTags } from "@/features/community/publishShared";

/**
 * 工作流的「发布到社区」(ADR 0026 §4)。发的是本机「导出」得到的那同一份文件,加上标题、简介、标签和
 * 一张封面(从素材库里挑)。发布即上架;第一次是一个新条目,之后再发就是**这一条的新版本**(后端记着 slug)。
 */
export function PublishWorkflowDialog({
  open,
  onOpenChange,
  workflow,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflow: Workflow;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [title, setTitle] = React.useState(workflow.name);
  const [summary, setSummary] = React.useState(workflow.description);
  const [tags, setTags] = React.useState("");
  const [cover, setCover] = React.useState<Asset | null>(null);
  const [picking, setPicking] = React.useState(false);
  const [result, setResult] = React.useState<CommunityPublishResult | null>(null);
  const republish = Boolean(workflow.community_slug);

  React.useEffect(() => {
    if (!open) return;
    setTitle(workflow.name);
    setSummary(workflow.description);
    setTags("");
    setCover(null);
    setResult(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, workflow.id]);

  const publish = useMutation({
    mutationFn: () =>
      publishWorkflowToCommunity(workflow.id, {
        title: title.trim(),
        summary: summary.trim(),
        tags: parseTags(tags),
        cover_asset_id: cover?.id ?? null,
      }),
    onSuccess: (published) => {
      setResult(published);
      void qc.invalidateQueries({ queryKey: ["workflows", workflow.workspace_id] });
    },
    onError: (error: Error) => {
      toast.error(error.message);
      void qc.invalidateQueries({ queryKey: COMMUNITY_STATUS_KEY });
    },
  });

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !publish.isPending && onOpenChange(next)}
      title={republish ? t("communityPublishNewVersion") : t("communityPublishWorkflow")}
      className="w-[520px]"
      footer={
        result ? (
          <Button onClick={() => onOpenChange(false)}>{t("communityDone")}</Button>
        ) : (
          <>
            <Button variant="outline" disabled={publish.isPending} onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button loading={publish.isPending} disabled={!title.trim()} onClick={() => publish.mutate()}>
              <Send /> {republish ? t("communityPublishNewVersion") : t("communityPublish")}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <PublishedResult result={result} />
      ) : (
        <div className="grid gap-4" data-testid="publish-workflow-form">
          <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">
            {republish ? t("communityPublishWorkflowAgain") : t("communityPublishWorkflowIntro")}
          </p>
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldTitle")}</span>
            <Input value={title} maxLength={120} onChange={(event) => setTitle(event.currentTarget.value)} />
          </label>
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldSummary")}</span>
            <Textarea value={summary} rows={3} maxLength={2000} onChange={(event) => setSummary(event.currentTarget.value)} />
          </label>
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldTags")}</span>
            <Input value={tags} placeholder={t("communityFieldTagsPlaceholder")} onChange={(event) => setTags(event.currentTarget.value)} />
          </label>
          <CoverField cover={cover} onPick={() => setPicking(true)} onClear={() => setCover(null)} />
        </div>
      )}
      <CoverPicker
        open={picking}
        workspaceId={workflow.workspace_id}
        onOpenChange={setPicking}
        onPick={(asset) => {
          setCover(asset);
          setPicking(false);
        }}
      />
    </ModalShell>
  );
}

/**
 * 封面:一格方形预览 + 一句「它出现在哪」。社区上工作流的封面画在卡片和详情页的头像位,都是方形裁切 ——
 * 预览照同样裁,挑的时候就看得出头像位上是什么样。空着时整格是一个「挑一张」的按钮。
 */
function CoverField({ cover, onPick, onClear }: { cover: Asset | null; onPick: () => void; onClear: () => void }) {
  const t = useI18n();
  return (
    <div className="grid gap-2" data-cover-field="">
      <span className="text-ui-sm font-medium text-foreground">{t("communityFieldCover")}</span>
      <div className="flex min-w-0 items-center gap-4">
        <button
          type="button"
          onClick={onPick}
          aria-label={cover ? t("communityCoverChange") : t("communityCoverPick")}
          title={cover ? t("communityCoverChange") : t("communityCoverPick")}
          className={cn(
            "group relative grid size-24 shrink-0 cursor-pointer place-items-center overflow-hidden rounded-lg p-0 transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            cover
              ? "border border-border bg-secondary"
              : "border border-dashed border-field-border bg-field text-muted-foreground hover:border-primary hover:text-foreground",
          )}
        >
          {cover ? (
            <>
              <img src={assetThumbnailUrl(cover.id)} alt="" className="absolute inset-0 size-full object-cover" />
              <span className="absolute inset-0 grid place-items-center bg-black/45 text-white opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
                <ImagePlus size={18} />
              </span>
            </>
          ) : (
            <ImagePlus size={20} strokeWidth={1.6} />
          )}
        </button>
        <div className="grid min-w-0 flex-1 content-center gap-2">
          <span className="truncate text-ui-sm text-foreground">{cover ? cover.name || cover.original_filename : t("communityCoverEmpty")}</span>
          <span className="text-ui-xs leading-relaxed text-muted-foreground">{t("communityCoverHint")}</span>
          <span className="flex flex-wrap gap-2">
            <Button variant="outline" size="xs" onClick={onPick}>
              <ImageIcon />
              {cover ? t("communityCoverChange") : t("communityCoverPick")}
            </Button>
            {cover && (
              <Button variant="ghost" size="xs" className="text-muted-foreground hover:text-destructive" onClick={onClear}>
                <X />
                {t("communityCoverRemove")}
              </Button>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}

/** 从素材库里挑一张图当封面。 */
function CoverPicker({
  open,
  workspaceId,
  onOpenChange,
  onPick,
}: {
  open: boolean;
  workspaceId: string;
  onOpenChange: (open: boolean) => void;
  onPick: (asset: Asset) => void;
}) {
  const t = useI18n();
  const [keyword, setKeyword] = React.useState("");
  const assets = useQuery({ queryKey: assetKeys.list(workspaceId), queryFn: () => listAssets(workspaceId), enabled: open });
  const images = React.useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    return (assets.data ?? []).filter(
      (asset: Asset) =>
        asset.kind === "image" && (!needle || `${asset.name ?? ""} ${asset.original_filename ?? ""}`.toLowerCase().includes(needle)),
    );
  }, [assets.data, keyword]);
  return (
    <PickListDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("communityCoverPick")}
      searchLabel={t("boardsSearchImages")}
      query={keyword}
      onQueryChange={setKeyword}
      items={images}
      itemKey={(asset) => asset.id}
      row={(asset) => ({
        lead: <img src={assetThumbnailUrl(asset.id)} alt="" loading="lazy" className="h-full w-full object-cover" />,
        title: asset.name || asset.original_filename || "",
      })}
      onPick={onPick}
      pending={assets.isLoading}
      error={assets.isError ? assets.error.message : null}
      onRetry={() => void assets.refetch()}
      empty={{ icon: <ImageIcon size={24} strokeWidth={1.5} />, text: t("boardsNoImages") }}
    />
  );
}
